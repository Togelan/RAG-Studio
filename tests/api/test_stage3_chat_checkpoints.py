from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI, Request
from langchain_core.messages import AIMessage
from langgraph.graph import StateGraph
from qdrant_client import AsyncQdrantClient

from src.api.routes.saas_chat import create_saas_chat_router
from src.api.saas_auth_context import AuthContext
from src.api.saas_chat_models import ChatbotConfiguration
from src.api.saas_chat_persistence import TenantChatStore
from src.api.saas_chat_runtime import TenantChatRuntime
from src.api.saas_chat_scope import SaasChatScope
from src.api.saas_identity import JwtClaims
from src.api.saas_security import BffSessionHandle
from src.api.saas_sessions import BffSession, Membership, WorkspaceRole
from src.api.saas_tenant_context import TrustedWorkspaceContext
from src.graph.builder import create_graph, stream_rag_graph
from src.graph.state import RAGState
from src.vector_store.tenant_store import TenantRagStore
from tests.api.stage3_chatbot_test_support import EnabledChatbots
from tests.vector_store.test_tenant_rag_store import _store


class _SwitchingAuthResolver:
    def __init__(self, context: AuthContext) -> None:
        self.context = context

    async def resolve(
        self, request: Request, *, require_workspace: bool
    ) -> AuthContext:
        del request, require_workspace
        return self.context


@dataclass(frozen=True, slots=True)
class _StoreResolver:
    store: TenantRagStore

    async def resolve(self, context: TrustedWorkspaceContext) -> TenantRagStore:
        del context
        return self.store


@dataclass(slots=True)
class _CheckpointGraphRunner:
    graph: Any

    async def stream(
        self,
        *,
        query: str,
        thread_id: object,
        configuration: ChatbotConfiguration,
        api_key: str | None,
        tenant_store: TenantRagStore,
    ) -> AsyncIterator[Mapping[str, object]]:
        del tenant_store
        async for event in stream_rag_graph(
            query=query,
            session_id=str(thread_id),
            user_api_key=api_key,
            persist_user_api_key=False,
            compiled_graph=self.graph,
            provider=configuration.provider,
            model=configuration.model_name,
            system_prompt=configuration.instructions,
        ):
            yield event


def _auth_context(workspace_id: UUID, user_id: UUID) -> AuthContext:
    session = BffSession(
        BffSessionHandle("opaque-checkpoint-test"),
        user_id,
        "member@example.test",
        "server-only-access",
        "server-only-refresh",
        99_999_999_999.0,
        workspace_id,
    )
    return AuthContext(
        session,
        JwtClaims(user_id, session.email),
        Membership(workspace_id, WorkspaceRole.MEMBER),
    )


async def _checkpoint_node(state: RAGState) -> dict[str, Any]:
    return {
        "messages": [AIMessage(content="checkpointed")],
        "final_answer": "checkpointed",
        "generated_from": "cache",
        "faithfulness_score": 1.0,
        "retrieved_docs": [],
    }


@asynccontextmanager
async def _real_checkpoint_graph(database_path: Path) -> AsyncIterator[Any]:
    async with create_graph(db_path=str(database_path)) as saver_owner:
        builder = StateGraph(RAGState)
        builder.add_node("checkpoint", _checkpoint_node)
        builder.set_entry_point("checkpoint")
        builder.set_finish_point("checkpoint")
        yield builder.compile(checkpointer=saver_owner.checkpointer)


def _messages(checkpoint: Any) -> list[Any]:
    return list(checkpoint.checkpoint["channel_values"]["messages"])


@pytest.mark.anyio
async def test_authenticated_graph_checkpoint_restores_and_denies_scope_tamper(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given: two authorized tenant scopes reuse one session UUID and real SQLite saver.
    monkeypatch.setenv("DEEPSEEK_API_KEY", "server-only-checkpoint-test")
    database_path = tmp_path / "real-checkpoints.sqlite3"
    store = TenantChatStore(tmp_path / "tenant-chat.sqlite3")
    runtime = TenantChatRuntime(store, b"server-side-checkpoint-key", 2)
    await runtime.initialize()
    shared_session = uuid4()
    first = SaasChatScope(uuid4(), uuid4(), uuid4(), shared_session)
    second = SaasChatScope(uuid4(), uuid4(), uuid4(), shared_session)
    configuration = ChatbotConfiguration(
        provider="deepseek",
        model_name="test-model",
        instructions="",
        workspace_all=True,
    )
    for scope in (first, second):
        await store.save_configuration(scope.context, configuration)
        await store.create_session(scope, "Scoped")
    resolver = _SwitchingAuthResolver(_auth_context(first.workspace_id, first.user_id))
    qdrant = AsyncQdrantClient(location=":memory:")
    tenant_store = await _store(qdrant, first.workspace_id)
    app = FastAPI()
    runner = _CheckpointGraphRunner(graph=None)
    app.include_router(
        create_saas_chat_router(
            resolver,
            runtime,
            EnabledChatbots(configuration),
            store_resolver=_StoreResolver(tenant_store),
            graph_runner=runner,
        )
    )
    transport = httpx.ASGITransport(app=app)
    first_path = (
        f"/api/saas/workspaces/{first.workspace_id}/chatbots/{first.chatbot_id}"
        f"/sessions/{shared_session}/messages"
    )
    second_path = (
        f"/api/saas/workspaces/{second.workspace_id}/chatbots/{second.chatbot_id}"
        f"/sessions/{shared_session}/messages"
    )

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        async with _real_checkpoint_graph(database_path) as graph:
            app.state.graph = graph
            runner.graph = graph

            # When: each tenant executes the real graph through the authenticated route.
            first_response = await client.post(first_path, json={"content": "first"})
            resolver.context = _auth_context(second.workspace_id, second.user_id)
            second_response = await client.post(second_path, json={"content": "second"})

            # Then: both executions complete through separate opaque threads.
            assert first_response.status_code == 200
            assert second_response.status_code == 200
            assert "event: done" in first_response.text
            assert runtime.checkpoint_config(first) != runtime.checkpoint_config(second)

        async with _real_checkpoint_graph(database_path) as restarted_graph:
            app.state.graph = restarted_graph
            runner.graph = restarted_graph
            resolver.context = _auth_context(first.workspace_id, first.user_id)

            # When: the first exact scope executes again after saver reconstruction.
            restored_response = await client.post(
                first_path, json={"content": "after restart"}
            )

            # Then: its prior messages restore while the other scope stays independent.
            first_checkpoint = await restarted_graph.checkpointer.aget_tuple(
                runtime.checkpoint_config(first)
            )
            second_checkpoint = await restarted_graph.checkpointer.aget_tuple(
                runtime.checkpoint_config(second)
            )
            assert restored_response.status_code == 200
            assert len(_messages(first_checkpoint)) == 4
            assert len(_messages(second_checkpoint)) == 2
            assert "user_api_key" not in first_checkpoint.checkpoint["channel_values"]
            assert "server-only-checkpoint-test" not in repr(first_checkpoint)

            # When/Then: independent workspace, user, and chatbot tampering is denied.
            wrong_workspace = await client.post(
                first_path.replace(str(first.workspace_id), str(uuid4())),
                json={"content": "tamper"},
            )
            resolver.context = _auth_context(first.workspace_id, uuid4())
            wrong_user = await client.post(first_path, json={"content": "tamper"})
            resolver.context = _auth_context(first.workspace_id, first.user_id)
            wrong_chatbot = await client.post(
                first_path.replace(str(first.chatbot_id), str(uuid4())),
                json={"content": "tamper"},
            )
            assert wrong_workspace.status_code == 403
            assert wrong_user.status_code == 404
            assert wrong_chatbot.status_code == 404
            unchanged = await restarted_graph.checkpointer.aget_tuple(
                runtime.checkpoint_config(first)
            )
            assert len(_messages(unchanged)) == 4

    await runtime.shutdown()
    await qdrant.close()
