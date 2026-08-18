"""Authorized SaaS document ingestion and tenant retrieval routes."""

from __future__ import annotations

from typing import Annotated, Protocol
from uuid import UUID

from fastapi import APIRouter, File, HTTPException, Request, UploadFile, status
from pydantic import BaseModel, ConfigDict, Field

from src.api.saas_auth_context import AuthContext
from src.api.saas_chat_models import (
    ChatbotCatalogUnavailableError,
    ChatbotExecutionConfiguration,
    ChatbotUnavailableError,
    ExecutionChannel,
    SupportedLocale,
)
from src.api.saas_sessions import WorkspaceRole
from src.api.saas_tenant_context import (
    TrustedWorkspaceContext,
    WorkspaceContextUnavailableError,
    trusted_workspace_context,
)
from src.graph.nodes import tenant_context_node
from src.ingestion.embedding import Embedder
from src.ingestion.tenant_service import (
    TenantDocumentRejectedError,
    TenantIngestionResult,
    TenantTextIngestor,
)
from src.ingestion.tenant_uploads import (
    TenantSourceUpload,
    TenantSourceUploadRejectedError,
)
from src.vector_store.pagination import CursorError
from src.vector_store.tenant_store import TenantCacheScope, TenantRagStore


class TenantRagAuthResolver(Protocol):
    """Resolve revalidated BFF identity and selected workspace authority."""

    async def resolve(
        self, request: Request, *, require_workspace: bool
    ) -> AuthContext: ...


class TenantRagStoreResolver(Protocol):
    """Resolve storage from trusted context without browser collection input."""

    async def resolve(self, context: TrustedWorkspaceContext) -> TenantRagStore: ...


class ChatbotExecutionResolver(Protocol):
    """Resolve tenant chatbot settings after the route path is authorized."""

    async def resolve_execution(
        self,
        workspace_id: UUID,
        chatbot_id: UUID,
        channel: ExecutionChannel,
        locale: SupportedLocale,
    ) -> ChatbotExecutionConfiguration: ...


class TenantDocumentRequest(BaseModel):
    """Bounded plain-text document accepted by the SaaS BFF."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    filename: str = Field(min_length=1, max_length=255)
    text: str = Field(min_length=1, max_length=5_000_000)


class TenantRetrievalRequest(BaseModel):
    """Validated retrieval input that cannot select a model or cache namespace."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    query: str = Field(min_length=1, max_length=10_000)
    locale: SupportedLocale = SupportedLocale.EN


class TenantRetrievalResponse(BaseModel):
    """Tenant-bound cache hit and citation-ready search documents."""

    model_config = ConfigDict(frozen=True)
    cached_answer: str | None
    documents: list[dict[str, object]]


def create_saas_rag_router(
    auth_resolver: TenantRagAuthResolver,
    store_resolver: TenantRagStoreResolver,
    embedder: Embedder,
    chatbots: ChatbotExecutionResolver,
) -> APIRouter:
    """Compose SaaS RAG routes around trusted workspace-bound capabilities."""
    router = APIRouter(prefix="/api/saas/workspaces/{workspace_id}", tags=["saas-rag"])
    ingestor = TenantTextIngestor(embedder)

    @router.post(
        "/documents",
        response_model=TenantIngestionResult,
        status_code=status.HTTP_201_CREATED,
    )
    async def ingest_document(
        workspace_id: UUID, body: TenantDocumentRequest, request: Request
    ) -> TenantIngestionResult:
        context, store = await _authorized_store(
            auth_resolver, store_resolver, request, workspace_id
        )
        if context.role is WorkspaceRole.MEMBER:
            raise HTTPException(status_code=403, detail="Insufficient workspace role.")
        try:
            return await ingestor.ingest(store, body.filename, body.text)
        except TenantDocumentRejectedError:
            raise HTTPException(
                status_code=422, detail="Document is invalid."
            ) from None

    @router.post(
        "/documents/upload",
        response_model=TenantIngestionResult,
        status_code=status.HTTP_201_CREATED,
    )
    async def upload_document(
        workspace_id: UUID,
        request: Request,
        file: Annotated[UploadFile, File()],
    ) -> TenantIngestionResult:
        """Parse and atomically replace one authorized workspace source."""
        context, store = await _authorized_store(
            auth_resolver, store_resolver, request, workspace_id
        )
        if context.role is WorkspaceRole.MEMBER:
            raise HTTPException(status_code=403, detail="Insufficient workspace role.")
        try:
            return await ingestor.ingest_source(
                store,
                TenantSourceUpload(
                    filename=file.filename or "",
                    content_type=file.content_type,
                    content=await file.read(),
                ),
            )
        except TenantSourceUploadRejectedError:
            raise HTTPException(
                status_code=422, detail="Document is invalid."
            ) from None

    @router.get("/documents")
    async def list_documents(
        workspace_id: UUID, request: Request, cursor: str | None = None
    ) -> dict[str, object]:
        _, store = await _authorized_store(
            auth_resolver, store_resolver, request, workspace_id
        )
        try:
            page = await store.list_documents(cursor)
        except CursorError:
            raise HTTPException(status_code=422, detail="Invalid cursor.") from None
        return {
            "documents": [
                {
                    "doc_id": item.payload.get("doc_id", ""),
                    "filename": item.payload.get("source", ""),
                    "chunk_count": item.payload.get("total_chunks", 0),
                    "created_at": item.payload.get("created_at", ""),
                }
                for item in page.items
            ],
            "next_cursor": page.next_cursor,
            "truncated": page.truncated,
        }

    @router.delete("/documents/{doc_id}")
    async def delete_document(
        workspace_id: UUID, doc_id: str, request: Request
    ) -> dict[str, int]:
        context, store = await _authorized_store(
            auth_resolver, store_resolver, request, workspace_id
        )
        if context.role is WorkspaceRole.MEMBER:
            raise HTTPException(status_code=403, detail="Insufficient workspace role.")
        return {"deleted_count": await store.delete_document(doc_id)}

    @router.delete("/documents")
    async def clear_documents(workspace_id: UUID, request: Request) -> dict[str, int]:
        context, store = await _authorized_store(
            auth_resolver, store_resolver, request, workspace_id
        )
        if context.role is WorkspaceRole.MEMBER:
            raise HTTPException(status_code=403, detail="Insufficient workspace role.")
        return {"deleted_count": await store.clear_documents()}

    @router.post(
        "/chatbots/{chatbot_id}/retrieve", response_model=TenantRetrievalResponse
    )
    async def retrieve(
        workspace_id: UUID,
        chatbot_id: UUID,
        body: TenantRetrievalRequest,
        request: Request,
    ) -> TenantRetrievalResponse:
        _, store = await _authorized_store(
            auth_resolver, store_resolver, request, workspace_id
        )
        execution = await _execution_configuration(
            chatbots, workspace_id, chatbot_id, body.locale
        )
        scope = TenantCacheScope(str(execution.configuration.fingerprint))
        graph_result = await tenant_context_node(
            body.query,
            tenant_store=store,
            cache_scope=scope,
            embedder=embedder,
        )
        return TenantRetrievalResponse(
            cached_answer=graph_result["cached_answer"],
            documents=graph_result["retrieved_docs"],
        )

    return router


async def _execution_configuration(
    resolver: ChatbotExecutionResolver,
    workspace_id: UUID,
    chatbot_id: UUID,
    locale: SupportedLocale,
) -> ChatbotExecutionConfiguration:
    try:
        return await resolver.resolve_execution(
            workspace_id, chatbot_id, ExecutionChannel.TEST, locale
        )
    except ChatbotUnavailableError:
        raise HTTPException(status_code=409, detail="Chatbot is unavailable.") from None
    except ChatbotCatalogUnavailableError:
        raise HTTPException(
            status_code=503, detail="Chatbot authority is unavailable."
        ) from None


async def _authorized_store(
    auth_resolver: TenantRagAuthResolver,
    store_resolver: TenantRagStoreResolver,
    request: Request,
    workspace_id: UUID,
) -> tuple[TrustedWorkspaceContext, TenantRagStore]:
    auth_context = await auth_resolver.resolve(request, require_workspace=True)
    try:
        context = trusted_workspace_context(auth_context)
    except WorkspaceContextUnavailableError:
        raise HTTPException(
            status_code=403, detail="Workspace is unavailable."
        ) from None
    if context.workspace_id != workspace_id:
        raise HTTPException(status_code=403, detail="Workspace is unavailable.")
    return context, await store_resolver.resolve(context)
