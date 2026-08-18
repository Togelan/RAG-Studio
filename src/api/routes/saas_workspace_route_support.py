"""Shared authorization and error translation for workspace routes."""

from __future__ import annotations

from collections.abc import Awaitable
from dataclasses import dataclass
from typing import assert_never
from uuid import UUID

from fastapi import HTTPException, Request

from src.api.saas_auth_context import AuthContext, BffAuthContextResolver
from src.api.saas_sessions import WorkspaceRole
from src.api.saas_workspace_models import (
    WorkspaceActor,
    WorkspaceErrorCode,
    WorkspaceOperationError,
)


@dataclass(frozen=True, slots=True)
class WorkspaceRouteAccess:
    """Selected workspace and roles admitted by one route."""

    workspace_id: UUID
    roles: tuple[WorkspaceRole, ...]


async def resolve_workspace_actor(
    resolver: BffAuthContextResolver,
    request: Request,
    access: WorkspaceRouteAccess,
) -> WorkspaceActor:
    """Resolve and authorize an active selected-workspace actor."""
    context = await resolver.resolve(request, require_workspace=True)
    return selected_workspace_actor(context, access)


def selected_workspace_actor(
    context: AuthContext, access: WorkspaceRouteAccess
) -> WorkspaceActor:
    """Reject route UUID tampering and role escalation before persistence."""
    membership = context.membership
    if (
        membership is None
        or membership.workspace_id != access.workspace_id
        or membership.role not in access.roles
    ):
        raise HTTPException(status_code=403, detail="Workspace is unavailable.")
    return WorkspaceActor(access.workspace_id, context.claims.user_id)


async def execute_workspace_operation[T](operation: Awaitable[T]) -> T:
    """Translate typed service failures into sanitized HTTP responses."""
    try:
        return await operation
    except WorkspaceOperationError as error:
        raise _http_error(error.code) from None


def _http_error(code: WorkspaceErrorCode) -> HTTPException:
    match code:
        case WorkspaceErrorCode.DENIED:
            return HTTPException(status_code=403, detail="Operation is not permitted.")
        case WorkspaceErrorCode.CONFLICT:
            return HTTPException(
                status_code=409, detail="Operation conflicts with current state."
            )
        case WorkspaceErrorCode.UNAVAILABLE:
            return HTTPException(
                status_code=503, detail="Workspace service is unavailable."
            )
        case unreachable:
            assert_never(unreachable)
