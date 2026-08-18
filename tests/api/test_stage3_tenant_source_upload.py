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


class _Embedder:
    def embed_dense(self, texts: tuple[str, ...]) -> tuple[DenseVector, ...]:
        return tuple(DenseVector((1.0,) * 384) for _ in texts)

    def embed_sparse(self, texts: tuple[str, ...]) -> tuple[SparseVector, ...]:
        return tuple(SparseVector((1,), (1.0,)) for _ in texts)


@dataclass(slots=True)
class _AuthResolver:
    user_id: UUID
    workspace_id: UUID
    role: WorkspaceRole = WorkspaceRole.OWNER

    async def resolve(
        self, request: Request, *, require_workspace: bool
    ) -> AuthContext:
        del request, require_workspace
        session = BffSession(
            BffSessionHandle("source-upload-session"),
            self.user_id,
            "source-upload@example.test",
            "provider-access",
            "provider-refresh",
            2_000_000_000,
            self.workspace_id,
        )
        return AuthContext(
            session,
            JwtClaims(self.user_id, session.email),
            Membership(self.workspace_id, self.role),
        )


@dataclass(frozen=True, slots=True)
class _StoreResolver:
    stores: dict[UUID, TenantRagStore]

    async def resolve(self, context: TrustedWorkspaceContext) -> TenantRagStore:
        return self.stores[context.workspace_id]


@pytest.mark.anyio
async def test_authorized_source_upload_replaces_only_its_workspace_document() -> None:
    # Given: two isolated workspace stores with identical source filenames.
    qdrant = AsyncQdrantClient(location=":memory:")
    user_id, first_workspace, second_workspace = uuid4(), uuid4(), uuid4()
    first_store = await _store(qdrant, first_workspace)
    second_store = await _store(qdrant, second_workspace)
    auth = _AuthResolver(user_id, first_workspace)
    app = FastAPI()
    app.include_router(
        create_saas_rag_router(
            auth,
            _StoreResolver(
                {first_workspace: first_store, second_workspace: second_store}
            ),
            _Embedder(),
            EnabledChatbots(
                ChatbotConfiguration(
                    provider="deepseek", model_name="stage3-deterministic"
                )
            ),
        )
    )
    transport = httpx.ASGITransport(app=app)

    try:
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            # When: each owner uploads, then the first owner replaces its source.
            first_upload = await client.post(
                f"/api/saas/workspaces/{first_workspace}/documents/upload",
                files={"file": ("handbook.md", b"first source", "text/markdown")},
            )
            auth.workspace_id = second_workspace
            second_upload = await client.post(
                f"/api/saas/workspaces/{second_workspace}/documents/upload",
                files={"file": ("handbook.md", b"second source", "text/markdown")},
            )
            auth.workspace_id = first_workspace
            replacement_upload = await client.post(
                f"/api/saas/workspaces/{first_workspace}/documents/upload",
                files={"file": ("handbook.md", b"first replacement", "text/markdown")},
            )
            auth.role = WorkspaceRole.MEMBER
            member_upload = await client.post(
                f"/api/saas/workspaces/{first_workspace}/documents/upload",
                files={"file": ("blocked.md", b"member upload", "text/markdown")},
            )

        # Then: upload and replacement remain bounded to the authorized store.
        assert first_upload.status_code == 201
        assert second_upload.status_code == 201
        assert replacement_upload.status_code == 201
        assert member_upload.status_code == 403
        first_document = await first_store.find_document("handbook.md")
        second_document = await second_store.find_document("handbook.md")
        assert first_document is not None
        assert second_document is not None
        assert first_document.file_hash != second_document.file_hash
        assert first_document.chunk_count == 1
        assert second_document.chunk_count == 1
    finally:
        await qdrant.close()
