"""Sanitized FR-015 chatbot lifecycle routes."""

from __future__ import annotations

from collections.abc import Awaitable
from typing import Annotated, Final, Protocol, assert_never
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Request, status

from src.api.routes.saas_chatbot_schemas import (
    ChatbotDefinitionRequest,
    ChatbotResponse,
    ChatbotUpdateRequest,
    ChatbotVersionRequest,
    chatbot_response,
)
from src.api.routes.saas_workspace_route_support import (
    WorkspaceRouteAccess,
    selected_workspace_actor,
)
from src.api.saas_auth_context import AuthContext
from src.api.saas_chatbot_models import (
    ChatbotActor,
    ChatbotCreation,
    ChatbotErrorCode,
    ChatbotOperationError,
    ChatbotService,
    ChatbotUpdate,
    ChatbotVersionMutation,
)
from src.api.saas_sessions import WorkspaceRole

_ALL_ROLES: Final = (
    WorkspaceRole.OWNER,
    WorkspaceRole.ADMIN,
    WorkspaceRole.MEMBER,
)
_MANAGERS: Final = (WorkspaceRole.OWNER, WorkspaceRole.ADMIN)
IdempotencyKey = Annotated[
    str,
    Header(
        alias="Idempotency-Key",
        min_length=8,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    ),
]


class AuthContextResolver(Protocol):
    """Resolve current BFF identity and selected workspace authority."""

    async def resolve(
        self, request: Request, *, require_workspace: bool
    ) -> AuthContext: ...


def create_saas_chatbots_router(
    auth_resolver: AuthContextResolver,
    service: ChatbotService,
) -> APIRouter:
    """Build tenant chatbot lifecycle routes around trusted authority."""
    router = APIRouter(
        prefix="/api/saas/workspaces/{workspace_id}/chatbots",
        tags=["saas-chatbots"],
    )

    @router.get("", response_model=list[ChatbotResponse])
    async def list_chatbots(
        workspace_id: UUID, request: Request
    ) -> list[ChatbotResponse]:
        actor = await _actor(auth_resolver, request, workspace_id, _ALL_ROLES)
        records = await _execute(service.list_chatbots(actor))
        return [chatbot_response(record) for record in records]

    @router.get("/{chatbot_id}", response_model=ChatbotResponse)
    async def get_chatbot(
        workspace_id: UUID, chatbot_id: UUID, request: Request
    ) -> ChatbotResponse:
        actor = await _actor(auth_resolver, request, workspace_id, _ALL_ROLES)
        record = await _execute(service.get_chatbot(actor, chatbot_id))
        return chatbot_response(record)

    @router.post(
        "",
        response_model=ChatbotResponse,
        status_code=status.HTTP_201_CREATED,
    )
    async def create_chatbot(
        workspace_id: UUID,
        payload: ChatbotDefinitionRequest,
        request: Request,
        idempotency_key: IdempotencyKey,
    ) -> ChatbotResponse:
        actor = await _actor(auth_resolver, request, workspace_id, _MANAGERS)
        record = await _execute(
            service.create_chatbot(
                ChatbotCreation(actor, payload.to_definition(), idempotency_key)
            )
        )
        return chatbot_response(record)

    @router.patch("/{chatbot_id}", response_model=ChatbotResponse)
    async def update_chatbot(
        workspace_id: UUID,
        chatbot_id: UUID,
        payload: ChatbotUpdateRequest,
        request: Request,
    ) -> ChatbotResponse:
        actor = await _actor(auth_resolver, request, workspace_id, _MANAGERS)
        record = await _execute(
            service.update_chatbot(
                ChatbotUpdate(
                    actor,
                    chatbot_id,
                    payload.version,
                    payload.to_definition(),
                )
            )
        )
        return chatbot_response(record)

    @router.post("/{chatbot_id}/disable", response_model=ChatbotResponse)
    async def disable_chatbot(
        workspace_id: UUID,
        chatbot_id: UUID,
        payload: ChatbotVersionRequest,
        request: Request,
    ) -> ChatbotResponse:
        actor = await _actor(auth_resolver, request, workspace_id, _MANAGERS)
        record = await _execute(
            service.disable_chatbot(
                ChatbotVersionMutation(actor, chatbot_id, payload.version)
            )
        )
        return chatbot_response(record)

    @router.delete("/{chatbot_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def archive_chatbot(
        workspace_id: UUID,
        chatbot_id: UUID,
        payload: ChatbotVersionRequest,
        request: Request,
    ) -> None:
        actor = await _actor(auth_resolver, request, workspace_id, _MANAGERS)
        await _execute(
            service.archive_chatbot(
                ChatbotVersionMutation(actor, chatbot_id, payload.version)
            )
        )

    return router


async def _actor(
    resolver: AuthContextResolver,
    request: Request,
    workspace_id: UUID,
    roles: tuple[WorkspaceRole, ...],
) -> ChatbotActor:
    context = await resolver.resolve(request, require_workspace=True)
    return selected_workspace_actor(context, WorkspaceRouteAccess(workspace_id, roles))


async def _execute[T](operation: Awaitable[T]) -> T:
    try:
        return await operation
    except ChatbotOperationError as error:
        raise _http_error(error.code) from None


def _http_error(code: ChatbotErrorCode) -> HTTPException:
    match code:
        case ChatbotErrorCode.DENIED:
            return HTTPException(status_code=403, detail="Operation is not permitted.")
        case ChatbotErrorCode.NOT_FOUND:
            return HTTPException(status_code=404, detail="Chatbot not found.")
        case ChatbotErrorCode.CONFLICT:
            return HTTPException(
                status_code=409, detail="Chatbot version conflicts with current state."
            )
        case ChatbotErrorCode.UNAVAILABLE:
            return HTTPException(
                status_code=503, detail="Chatbot service is unavailable."
            )
        case unreachable:
            assert_never(unreachable)
