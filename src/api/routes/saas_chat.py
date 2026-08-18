"""Authenticated SaaS session, feedback, cancellation, and replay routes."""

from __future__ import annotations

from collections.abc import Awaitable
from typing import Protocol
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from src.api.chat_jobs import ChatJobNotFoundError
from src.api.chat_stream import (
    STREAM_RETRY_AFTER_SECONDS,
    StreamCapacityError,
    StreamSessionConflictError,
)
from src.api.routes.saas_chat_schemas import (
    SessionCreateRequest,
    SessionMessageRequest,
    SessionOperationResponse,
    SessionRenameRequest,
    SessionResponse,
)
from src.api.saas_auth_context import AuthContext
from src.api.saas_chat_execution import (
    ProviderCredentialUnavailableError,
    graph_job_producer,
    server_provider_key,
)
from src.api.saas_chat_models import (
    ChatbotAvailability,
    ChatbotCatalogUnavailableError,
    ChatbotExecutionConfiguration,
    ChatbotUnavailableError,
    ChatFeedback,
    ChatPersistenceUnavailableError,
    ChatSessionNotFoundError,
    ChatSessionRecord,
    ExecutionChannel,
    SupportedLocale,
)
from src.api.saas_chat_runtime import TenantChatRuntime
from src.api.saas_chat_scope import SaasChatContext, SaasChatScope
from src.api.saas_tenant_context import (
    TrustedWorkspaceContext,
    WorkspaceContextUnavailableError,
    trusted_workspace_context,
)
from src.api.saas_tenant_graph import TenantGraphRunner
from src.vector_store.tenant_store import TenantRagStore


class AuthContextResolver(Protocol):
    """Resolve current identity and selected active workspace authority."""

    async def resolve(
        self, request: Request, *, require_workspace: bool
    ) -> AuthContext: ...


class ChatbotExecutionResolver(Protocol):
    """Resolve authoritative lifecycle state and localized execution settings."""

    async def resolve_execution(
        self,
        workspace_id: UUID,
        chatbot_id: UUID,
        channel: ExecutionChannel,
        locale: SupportedLocale,
    ) -> ChatbotExecutionConfiguration: ...


class TenantRagStoreResolver(Protocol):
    """Resolve a collection only after BFF membership authorization."""

    async def resolve(self, context: TrustedWorkspaceContext) -> TenantRagStore: ...


def create_saas_chat_router(
    auth_resolver: AuthContextResolver,
    runtime: TenantChatRuntime,
    chatbots: ChatbotExecutionResolver,
    *,
    store_resolver: TenantRagStoreResolver | None = None,
    graph_runner: TenantGraphRunner | None = None,
) -> APIRouter:
    """Compose tenant-scoped session lifecycle routes."""
    router = APIRouter(
        prefix="/api/saas/workspaces/{workspace_id}/chatbots/{chatbot_id}",
        tags=["saas-chat"],
    )

    @router.get("/sessions", response_model=list[SessionResponse])
    async def list_sessions(
        workspace_id: UUID, chatbot_id: UUID, request: Request
    ) -> list[ChatSessionRecord]:
        context = await _authorized_context(
            auth_resolver, request, workspace_id, chatbot_id
        )
        return list(await _store_result(runtime.store.list_sessions(context)))

    @router.post(
        "/sessions",
        response_model=SessionResponse,
        status_code=status.HTTP_201_CREATED,
    )
    async def create_session(
        workspace_id: UUID,
        chatbot_id: UUID,
        body: SessionCreateRequest,
        request: Request,
    ) -> ChatSessionRecord:
        scope = await _authorized_scope(
            auth_resolver, request, workspace_id, chatbot_id, body.session_id
        )
        await _execution_configuration(
            chatbots,
            workspace_id,
            chatbot_id,
            SupportedLocale.EN,
        )
        return await _store_result(runtime.store.create_session(scope, body.title))

    @router.patch("/sessions/{session_id}", response_model=SessionResponse)
    async def rename_session(
        workspace_id: UUID,
        chatbot_id: UUID,
        session_id: UUID,
        body: SessionRenameRequest,
        request: Request,
    ) -> ChatSessionRecord:
        scope = await _authorized_scope(
            auth_resolver, request, workspace_id, chatbot_id, session_id
        )
        return await _store_result(runtime.store.rename_session(scope, body.title))

    @router.delete("/sessions/{session_id}", response_model=SessionOperationResponse)
    async def delete_session(
        workspace_id: UUID,
        chatbot_id: UUID,
        session_id: UUID,
        request: Request,
    ) -> SessionOperationResponse:
        scope = await _authorized_scope(
            auth_resolver, request, workspace_id, chatbot_id, session_id
        )
        await runtime.cancel(scope)
        await _store_result(runtime.store.delete_session(scope))
        return SessionOperationResponse(status="deleted", session_id=session_id)

    @router.post(
        "/sessions/{session_id}/feedback",
        response_model=SessionOperationResponse,
        status_code=status.HTTP_201_CREATED,
    )
    async def submit_feedback(
        workspace_id: UUID,
        chatbot_id: UUID,
        session_id: UUID,
        body: ChatFeedback,
        request: Request,
    ) -> SessionOperationResponse:
        scope = await _authorized_scope(
            auth_resolver, request, workspace_id, chatbot_id, session_id
        )
        await _store_result(runtime.store.save_feedback(scope, body))
        return SessionOperationResponse(status="stored", session_id=session_id)

    @router.post(
        "/sessions/{session_id}/cancel",
        response_model=SessionOperationResponse,
    )
    async def cancel_session(
        workspace_id: UUID,
        chatbot_id: UUID,
        session_id: UUID,
        request: Request,
    ) -> SessionOperationResponse:
        scope = await _authorized_scope(
            auth_resolver, request, workspace_id, chatbot_id, session_id
        )
        await _store_result(runtime.store.get_session(scope))
        cancelled = await runtime.cancel(scope)
        return SessionOperationResponse(
            status="cancelled" if cancelled else "idle", session_id=session_id
        )

    @router.get("/sessions/{session_id}/stream")
    async def reattach_session(
        workspace_id: UUID,
        chatbot_id: UUID,
        session_id: UUID,
        request: Request,
    ) -> StreamingResponse:
        scope = await _authorized_scope(
            auth_resolver, request, workspace_id, chatbot_id, session_id
        )
        await _store_result(runtime.store.get_session(scope))
        try:
            events = await runtime.reattach(scope)
        except ChatJobNotFoundError:
            raise HTTPException(
                status_code=404, detail="Active response not found."
            ) from None
        return StreamingResponse(
            events,
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @router.post("/sessions/{session_id}/messages")
    async def execute_message(
        workspace_id: UUID,
        chatbot_id: UUID,
        session_id: UUID,
        body: SessionMessageRequest,
        request: Request,
    ) -> StreamingResponse:
        scope, workspace_context = await _authorized_execution_scope(
            auth_resolver, request, workspace_id, chatbot_id, session_id
        )
        await _store_result(runtime.store.get_session(scope))
        execution = await _execution_configuration(
            chatbots,
            workspace_id,
            chatbot_id,
            body.locale,
        )
        configuration = execution.configuration
        if store_resolver is None or graph_runner is None:
            raise HTTPException(
                status_code=503, detail="Chat execution is unavailable."
            )
        try:
            api_key = server_provider_key(configuration)
            thread_id = runtime.checkpoint_config(scope)["configurable"]["thread_id"]
            tenant_store = await store_resolver.resolve(workspace_context)
            events = await runtime.start(
                scope,
                graph_job_producer(
                    graph_events=graph_runner.stream(
                        query=body.content,
                        thread_id=thread_id,
                        configuration=configuration,
                        api_key=api_key,
                        tenant_store=tenant_store,
                    )
                ),
                availability=ChatbotAvailability.ENABLED,
                buffer_max_bytes=65_536,
            )
        except ProviderCredentialUnavailableError:
            raise HTTPException(
                status_code=503, detail="Provider is unavailable."
            ) from None
        except ChatbotUnavailableError:
            raise HTTPException(
                status_code=409, detail="Chatbot is unavailable."
            ) from None
        except StreamSessionConflictError:
            raise HTTPException(
                status_code=409, detail="A response is already active."
            ) from None
        except StreamCapacityError:
            raise HTTPException(
                status_code=429,
                detail="Chat execution is at capacity.",
                headers={"Retry-After": str(STREAM_RETRY_AFTER_SECONDS)},
            ) from None
        return StreamingResponse(
            events,
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return router


async def _authorized_context(
    resolver: AuthContextResolver,
    request: Request,
    workspace_id: UUID,
    chatbot_id: UUID,
) -> SaasChatContext:
    auth_context = await resolver.resolve(request, require_workspace=True)
    try:
        workspace_context = trusted_workspace_context(auth_context)
    except WorkspaceContextUnavailableError:
        raise HTTPException(
            status_code=403, detail="Workspace is unavailable."
        ) from None
    if workspace_context.workspace_id != workspace_id:
        raise HTTPException(status_code=403, detail="Workspace is unavailable.")
    return SaasChatContext(workspace_id, workspace_context.user_id, chatbot_id)


async def _authorized_scope(
    resolver: AuthContextResolver,
    request: Request,
    workspace_id: UUID,
    chatbot_id: UUID,
    session_id: UUID,
) -> SaasChatScope:
    context = await _authorized_context(resolver, request, workspace_id, chatbot_id)
    return SaasChatScope(
        context.workspace_id, context.user_id, context.chatbot_id, session_id
    )


async def _authorized_execution_scope(
    resolver: AuthContextResolver,
    request: Request,
    workspace_id: UUID,
    chatbot_id: UUID,
    session_id: UUID,
) -> tuple[SaasChatScope, TrustedWorkspaceContext]:
    """Return exact chat scope together with its revalidated storage authority."""
    auth_context = await resolver.resolve(request, require_workspace=True)
    try:
        workspace_context = trusted_workspace_context(auth_context)
    except WorkspaceContextUnavailableError:
        raise HTTPException(
            status_code=403, detail="Workspace is unavailable."
        ) from None
    if workspace_context.workspace_id != workspace_id:
        raise HTTPException(status_code=403, detail="Workspace is unavailable.")
    return (
        SaasChatScope(workspace_id, workspace_context.user_id, chatbot_id, session_id),
        workspace_context,
    )


async def _store_result[T](operation: Awaitable[T]) -> T:
    try:
        return await operation
    except ChatSessionNotFoundError:
        raise HTTPException(status_code=404, detail="Session not found.") from None
    except ChatPersistenceUnavailableError:
        raise HTTPException(
            status_code=503, detail="Chat persistence is unavailable."
        ) from None


async def _execution_configuration(
    resolver: ChatbotExecutionResolver,
    workspace_id: UUID,
    chatbot_id: UUID,
    locale: SupportedLocale,
) -> ChatbotExecutionConfiguration:
    try:
        return await resolver.resolve_execution(
            workspace_id,
            chatbot_id,
            ExecutionChannel.TEST,
            locale,
        )
    except ChatbotUnavailableError:
        raise HTTPException(status_code=409, detail="Chatbot is unavailable.") from None
    except ChatbotCatalogUnavailableError:
        raise HTTPException(
            status_code=503, detail="Chatbot authority is unavailable."
        ) from None
