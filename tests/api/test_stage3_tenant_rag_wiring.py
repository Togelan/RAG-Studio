from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI, Request
from qdrant_client import AsyncQdrantClient

from src.api.routes.saas_rag import create_saas_rag_router
from src.api.saas_auth_context import AuthContext
from src.api.saas_chat_models import ChatbotConfiguration
from src.api.saas_identity import JwtClaims
from src.api.saas_security import BffSessionHandle
from src.api.saas_sessions import BffSession, Membership, WorkspaceRole
from src.api.saas_tenant_context import TrustedWorkspaceContext
from src.vector_store.models import DenseVector, SparseVector
from src.vector_store.tenant_store import TenantRagStore
from tests.api.stage3_chatbot_test_support import EnabledChatbots
from tests.vector_store.test_tenant_rag_store import _store


class FakeEmbedder:
    def embed_dense(self, texts: tuple[str, ...]) -> tuple[DenseVector, ...]:
        return tuple(DenseVector((1.0,) * 384) for _ in texts)

    def embed_sparse(self, texts: tuple[str, ...]) -> tuple[SparseVector, ...]:
        return tuple(SparseVector((1,), (1.0,)) for _ in texts)


@dataclass(slots=True)
class SwitchingAuth:
    user_id: UUID
    workspace_id: UUID

    async def resolve(
        self, request: Request, *, require_workspace: bool
    ) -> AuthContext:
        del request, require_workspace
        email = "tenant@example.test"
        session = BffSession(
            BffSessionHandle("opaque"),
            self.user_id,
            email,
            "provider-token",
            "refresh-token",
            2_000_000_000,
            active_workspace_id=self.workspace_id,
        )
        return AuthContext(
            session,
            JwtClaims(self.user_id, email),
            Membership(self.workspace_id, WorkspaceRole.OWNER),
        )


@dataclass(frozen=True, slots=True)
class StoreResolver:
    stores: dict[UUID, TenantRagStore]

    async def resolve(self, context: TrustedWorkspaceContext) -> TenantRagStore:
        return self.stores[context.workspace_id]


@pytest.mark.anyio
async def test_saas_document_and_retrieval_routes_bind_authorized_workspace() -> None:
    # Given: two workspace stores, one authenticated context, and one SaaS router.
    qdrant = AsyncQdrantClient(location=":memory:")
    user_id, first_id, second_id = uuid4(), uuid4(), uuid4()
    first = await _store(qdrant, first_id)
    second = await _store(qdrant, second_id)
    auth = SwitchingAuth(user_id, first_id)
    app = FastAPI()
    app.include_router(
        create_saas_rag_router(
            auth,
            StoreResolver({first_id: first, second_id: second}),
            FakeEmbedder(),
            EnabledChatbots(
                ChatbotConfiguration(
                    provider="deepseek",
                    model_name="deepseek-chat",
                )
            ),
        )
    )
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            # When: identical filenames are ingested and retrieved under each context.
            first_upload = await client.post(
                f"/api/saas/workspaces/{first_id}/documents",
                json={"filename": "same.txt", "text": "first private"},
            )
            auth.workspace_id = second_id
            second_upload = await client.post(
                f"/api/saas/workspaces/{second_id}/documents",
                json={"filename": "same.txt", "text": "second private"},
            )
            second_search = await client.post(
                f"/api/saas/workspaces/{second_id}/chatbots/{uuid4()}/retrieve",
                json={"query": "private"},
            )
            browser_selected_configuration = await client.post(
                f"/api/saas/workspaces/{second_id}/chatbots/{uuid4()}/retrieve",
                json={
                    "query": "private",
                    "provider": "untrusted-provider",
                    "model_name": "untrusted-model",
                },
            )
            second_cache_hit = await client.post(
                f"/api/saas/workspaces/{second_id}/chatbots/{uuid4()}/retrieve",
                json={"query": "private"},
            )
            replaced = await client.post(
                f"/api/saas/workspaces/{second_id}/documents",
                json={"filename": "same.txt", "text": "second replaced"},
            )
            after_replacement = await client.post(
                f"/api/saas/workspaces/{second_id}/chatbots/{uuid4()}/retrieve",
                json={"query": "private"},
            )
            replacement_cache_hit = await client.post(
                f"/api/saas/workspaces/{second_id}/chatbots/{uuid4()}/retrieve",
                json={"query": "private"},
            )
            tampered = await client.get(f"/api/saas/workspaces/{first_id}/documents")
            cleared = await client.delete(f"/api/saas/workspaces/{second_id}/documents")
            empty_after_clear = await client.post(
                f"/api/saas/workspaces/{second_id}/chatbots/{uuid4()}/retrieve",
                json={"query": "private"},
            )
            auth.workspace_id = first_id
            first_after_second_clear = await client.post(
                f"/api/saas/workspaces/{first_id}/chatbots/{uuid4()}/retrieve",
                json={"query": "private"},
            )

        # Then: real tenant ingestion/retrieval stays bound and path tampering is denied.
        assert first_upload.status_code == 201
        assert second_upload.status_code == 201
        assert second_search.status_code == 200
        assert browser_selected_configuration.status_code == 422
        assert [item["text"] for item in second_search.json()["documents"]] == [
            "second private"
        ]
        assert second_search.json()["cached_answer"] is None
        assert second_cache_hit.json()["cached_answer"] == "second private"
        assert replaced.status_code == 201
        assert after_replacement.json()["cached_answer"] is None
        assert [item["text"] for item in after_replacement.json()["documents"]] == [
            "second replaced"
        ]
        assert replacement_cache_hit.json()["cached_answer"] == "second replaced"
        assert tampered.status_code == 403
        assert cleared.status_code == 200
        assert empty_after_clear.json()["documents"] == []
        assert empty_after_clear.json()["cached_answer"] is None
        assert [
            item["text"] for item in first_after_second_clear.json()["documents"]
        ] == ["first private"]
        assert "collection" not in second_search.text.lower()
    finally:
        await qdrant.close()
