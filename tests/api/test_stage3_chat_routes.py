from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

import anyio
import pytest
from fastapi import FastAPI, HTTPException, Request
from httpx import ASGITransport, AsyncClient
from qdrant_client import AsyncQdrantClient

from src.api.routes.saas_chat import create_saas_chat_router
from src.api.saas_auth_context import AuthContext
from src.api.saas_chat_models import ChatbotAvailability, ChatbotConfiguration
from src.api.saas_chat_persistence import TenantChatStore
from src.api.saas_chat_runtime import TenantChatRuntime
from src.api.saas_chat_scope import SaasChatScope
from src.api.saas_identity import JwtClaims
from src.api.saas_security import BffSessionHandle
from src.api.saas_sessions import BffSession, Membership, WorkspaceRole
from src.api.saas_tenant_context import TrustedWorkspaceContext
from src.vector_store.tenant_store import TenantRagStore
from tests.api.stage3_chatbot_test_support import EnabledChatbots
from tests.vector_store.test_tenant_rag_store import _store


@dataclass(frozen=True, slots=True)
class _FakeAuthResolver:
    context: AuthContext | None

    async def resolve(
        self, request: Request, *, require_workspace: bool
    ) -> AuthContext:
        del request, require_workspace
        if self.context is None:
            raise HTTPException(status_code=403, detail="Workspace is unavailable.")
        return self.context


@dataclass(frozen=True, slots=True)
class _StoreResolver:
    store: TenantRagStore

    async def resolve(self, context: TrustedWorkspaceContext) -> TenantRagStore:
        del context
        return self.store


class _UnusedGraphRunner:
    async def stream(
        self,
        **_kwargs: object,
    ) -> AsyncIterator[Mapping[str, object]]:
        yield {
            "type": "result",
            "result": {
                "final_answer": "unused",
                "generated_from": "retrieval",
                "citations": [],
            },
        }


def _auth_context(workspace_id: UUID, user_id: UUID) -> AuthContext:
    session = BffSession(
        handle=BffSessionHandle("opaque-test-handle"),
        user_id=user_id,
        email="member@example.test",
        access_token="server-only-access",
        refresh_token="server-only-refresh",
        expires_at=99_999_999_999.0,
        active_workspace_id=workspace_id,
    )
    return AuthContext(
        session=session,
        claims=JwtClaims(user_id=user_id, email=session.email),
        membership=Membership(workspace_id, WorkspaceRole.MEMBER),
    )


def _enabled_chatbots() -> EnabledChatbots:
    return EnabledChatbots(
        ChatbotConfiguration(
            provider="ollama",
            model_name="local-model",
            instructions="",
            workspace_all=True,
        )
    )


@pytest.mark.anyio
async def test_session_routes_scope_crud_feedback_and_workspace_tamper(
    tmp_path: Path,
) -> None:
    # Given: an authenticated member and isolated tenant chat runtime.
    workspace_id, user_id, chatbot_id, session_id = (
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
    )
    runtime = TenantChatRuntime(
        TenantChatStore(tmp_path / "tenant-chat.sqlite3"),
        b"server-side-test-key",
        10,
    )
    await runtime.initialize()
    app = FastAPI()
    chatbots = _enabled_chatbots()
    app.include_router(
        create_saas_chat_router(
            _FakeAuthResolver(_auth_context(workspace_id, user_id)), runtime, chatbots
        )
    )
    prefix = f"/api/saas/workspaces/{workspace_id}/chatbots/{chatbot_id}"

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        # When: the member creates, renames, feeds back on, and lists a session.
        created = await client.post(
            f"{prefix}/sessions",
            json={"session_id": str(session_id), "title": "Scoped session"},
        )
        renamed = await client.patch(
            f"{prefix}/sessions/{session_id}", json={"title": "Renamed"}
        )
        feedback = await client.post(
            f"{prefix}/sessions/{session_id}/feedback",
            json={"message_id": str(uuid4()), "feedback": "positive"},
        )
        listed = await client.get(f"{prefix}/sessions")
        tampered = await client.get(
            f"/api/saas/workspaces/{uuid4()}/chatbots/{chatbot_id}/sessions"
        )
        deleted = await client.delete(f"{prefix}/sessions/{session_id}")
        after_delete = await client.get(f"{prefix}/sessions")

        # Then: scoped lifecycle succeeds and workspace path tampering fails closed.
        assert created.status_code == 201
        assert renamed.json()["title"] == "Renamed"
        assert feedback.status_code == 201
        assert listed.json() == [
            {
                "session_id": str(session_id),
                "title": "Renamed",
                "created_at": created.json()["created_at"],
                "updated_at": renamed.json()["updated_at"],
            }
        ]
        assert tampered.status_code == 403
        assert str(workspace_id) not in tampered.text
        assert deleted.status_code == 200
        assert after_delete.json() == []


@pytest.mark.anyio
async def test_revoked_context_and_storage_failure_are_sanitized(
    tmp_path: Path,
) -> None:
    # Given: one revoked resolver and one real storage boundary that cannot open.
    workspace_id, chatbot_id = uuid4(), uuid4()
    revoked_app = FastAPI()
    chatbots = _enabled_chatbots()
    revoked_runtime = TenantChatRuntime(
        TenantChatStore(tmp_path / "revoked.sqlite3"), b"server-key", 1
    )
    await revoked_runtime.initialize()
    revoked_app.include_router(
        create_saas_chat_router(_FakeAuthResolver(None), revoked_runtime, chatbots)
    )
    failed_app = FastAPI()
    failed_runtime = TenantChatRuntime(TenantChatStore(tmp_path), b"server-key", 1)
    failed_app.include_router(
        create_saas_chat_router(
            _FakeAuthResolver(_auth_context(workspace_id, uuid4())),
            failed_runtime,
            chatbots,
        )
    )
    path = f"/api/saas/workspaces/{workspace_id}/chatbots/{chatbot_id}/sessions"

    # When: each app receives a session list request.
    async with AsyncClient(
        transport=ASGITransport(app=revoked_app), base_url="http://test"
    ) as client:
        revoked = await client.get(path)
    async with AsyncClient(
        transport=ASGITransport(app=failed_app), base_url="http://test"
    ) as client:
        failed = await client.get(path)

    # Then: both boundaries fail closed without filesystem or provider detail.
    assert revoked.status_code == 403
    assert failed.status_code == 503
    assert str(tmp_path) not in failed.text


@pytest.mark.anyio
async def test_message_capacity_rejection_includes_retry_after(tmp_path: Path) -> None:
    workspace_id, user_id, chatbot_id = uuid4(), uuid4(), uuid4()
    first_session_id, second_session_id = uuid4(), uuid4()
    runtime = TenantChatRuntime(
        TenantChatStore(tmp_path / "tenant-chat.sqlite3"), b"server-key", 1
    )
    await runtime.initialize()
    context = _auth_context(workspace_id, user_id)
    first_scope = SaasChatScope(workspace_id, user_id, chatbot_id, first_session_id)
    second_scope = SaasChatScope(workspace_id, user_id, chatbot_id, second_session_id)
    await runtime.store.create_session(first_scope, "first")
    await runtime.store.create_session(second_scope, "second")
    started = anyio.Event()

    async def hold_slot(_publish: Callable[[str], Awaitable[None]]) -> None:
        started.set()
        await anyio.sleep_forever()

    await runtime.start(
        first_scope,
        hold_slot,
        availability=ChatbotAvailability.ENABLED,
        buffer_max_bytes=4096,
    )
    await started.wait()
    qdrant = AsyncQdrantClient(location=":memory:")
    tenant_store = await _store(qdrant, workspace_id)
    app = FastAPI()
    app.include_router(
        create_saas_chat_router(
            _FakeAuthResolver(context),
            runtime,
            _enabled_chatbots(),
            store_resolver=_StoreResolver(tenant_store),
            graph_runner=_UnusedGraphRunner(),
        )
    )
    path = (
        f"/api/saas/workspaces/{workspace_id}/chatbots/{chatbot_id}"
        f"/sessions/{second_session_id}/messages"
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(path, json={"content": "capacity", "locale": "en"})

    assert response.status_code == 429
    assert response.headers["retry-after"] == "1"
    await runtime.cancel(first_scope)
    await qdrant.close()
