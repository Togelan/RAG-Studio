from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI, Request
from qdrant_client import AsyncQdrantClient

from src.api.routes.saas_chat import create_saas_chat_router
from src.api.saas_auth_context import AuthContext
from src.api.saas_chat_models import ChatbotConfiguration
from src.api.saas_chat_persistence import TenantChatStore
from src.api.saas_chat_runtime import TenantChatRuntime
from src.api.saas_chat_scope import ExecutionKey, SaasChatScope
from src.api.saas_identity import JwtClaims
from src.api.saas_security import BffSessionHandle
from src.api.saas_sessions import BffSession, Membership, WorkspaceRole
from src.api.saas_tenant_context import TrustedWorkspaceContext
from src.vector_store.tenant_store import TenantRagStore
from tests.api.stage3_chatbot_test_support import EnabledChatbots
from tests.vector_store.test_tenant_rag_store import _store


@dataclass(slots=True)
class _AuthResolver:
    workspace_id: UUID
    user_id: UUID

    async def resolve(
        self, request: Request, *, require_workspace: bool
    ) -> AuthContext:
        del request, require_workspace
        session = BffSession(
            BffSessionHandle("opaque-tenant-execution"),
            self.user_id,
            "tenant@example.test",
            "server-access",
            "server-refresh",
            2_000_000_000.0,
            self.workspace_id,
        )
        return AuthContext(
            session,
            JwtClaims(self.user_id, session.email),
            Membership(self.workspace_id, WorkspaceRole.OWNER),
        )


@dataclass(frozen=True, slots=True)
class _StoreResolver:
    stores: dict[UUID, TenantRagStore]

    async def resolve(self, context: TrustedWorkspaceContext) -> TenantRagStore:
        return self.stores[context.workspace_id]


@dataclass(slots=True)
class _RecordingTenantGraphRunner:
    stores: list[TenantRagStore] = field(default_factory=list)

    async def stream(
        self,
        *,
        query: str,
        thread_id: ExecutionKey,
        configuration: ChatbotConfiguration,
        api_key: str | None,
        tenant_store: TenantRagStore,
    ) -> AsyncIterator[dict[str, object]]:
        del query, thread_id, configuration, api_key
        self.stores.append(tenant_store)
        yield {"type": "token", "token": "tenant answer"}
        yield {
            "type": "result",
            "result": {
                "final_answer": "tenant answer",
                "generated_from": "retrieval",
                "citations": [],
            },
        }


@pytest.mark.anyio
async def test_message_execution_binds_the_authorized_workspace_store(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: two physical tenant collections and one authenticated first workspace.
    qdrant = AsyncQdrantClient(location=":memory:")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "tenant-test-provider-key")
    user_id, first_workspace, second_workspace = uuid4(), uuid4(), uuid4()
    first_store = await _store(qdrant, first_workspace)
    second_store = await _store(qdrant, second_workspace)
    runtime = TenantChatRuntime(
        TenantChatStore(tmp_path / "tenant-chat.sqlite3"), b"tenant-execution-key", 1
    )
    await runtime.initialize()
    chatbot_id, session_id = uuid4(), uuid4()
    scope = SaasChatScope(first_workspace, user_id, chatbot_id, session_id)
    await runtime.store.create_session(scope, "Tenant chat")
    runner = _RecordingTenantGraphRunner()
    app = FastAPI()
    app.include_router(
        create_saas_chat_router(
            _AuthResolver(first_workspace, user_id),
            runtime,
            EnabledChatbots(
                ChatbotConfiguration(
                    provider="deepseek",
                    model_name="stage3-deterministic",
                    instructions="",
                    workspace_all=True,
                )
            ),
            store_resolver=_StoreResolver(
                {first_workspace: first_store, second_workspace: second_store}
            ),
            graph_runner=runner,
        )
    )
    path = (
        f"/api/saas/workspaces/{first_workspace}/chatbots/{chatbot_id}"
        f"/sessions/{session_id}/messages"
    )

    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            # When: the authenticated browser starts a real SaaS test message.
            response = await client.post(
                path, json={"content": "private", "locale": "en"}
            )

        # Then: execution receives only the authorized workspace-bound store.
        assert response.status_code == 200
        assert "tenant answer" in response.text
        assert runner.stores == [first_store]
        assert second_store not in runner.stores
    finally:
        await runtime.shutdown()
        await qdrant.close()
