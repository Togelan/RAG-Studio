"""Sanitized FR-013 workspace and invitation BFF routes."""

from __future__ import annotations

from typing import Annotated, Final
from uuid import UUID

from fastapi import APIRouter, Header, Request, status

from src.api.routes.saas_workspace_route_support import (
    WorkspaceRouteAccess,
    execute_workspace_operation,
    resolve_workspace_actor,
    selected_workspace_actor,
)
from src.api.routes.saas_workspace_schemas import (
    AuditEventResponse,
    InvitationAcceptRequest,
    InvitationCreateRequest,
    InvitationResponse,
    MembershipChangeRequest,
    MembershipResponse,
    OwnershipTransferRequest,
    WorkspaceCreateRequest,
    WorkspaceResponse,
    audit_response,
    invitation_response,
    membership_response,
    workspace_response,
)
from src.api.saas_auth_context import BffAuthContextResolver
from src.api.saas_sessions import WorkspaceRole
from src.api.saas_workspace_models import (
    InvitationAcceptance,
    InvitationCreation,
    MembershipChange,
    OwnershipTransfer,
    WorkspaceCreation,
    WorkspaceService,
)

_OWNERS: Final = (WorkspaceRole.OWNER,)
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


def create_saas_workspaces_router(
    auth_context_resolver: BffAuthContextResolver,
    service: WorkspaceService,
) -> APIRouter:
    """Build workspace routes around trusted auth and persistence boundaries."""
    router = APIRouter(tags=["saas-workspaces"])

    @router.get("/api/saas/workspaces", response_model=list[WorkspaceResponse])
    async def list_workspaces(request: Request) -> list[WorkspaceResponse]:
        context = await auth_context_resolver.resolve(request, require_workspace=False)
        workspaces = await execute_workspace_operation(
            service.list_workspaces(context.claims.user_id)
        )
        return [workspace_response(workspace) for workspace in workspaces]

    @router.post(
        "/api/saas/workspaces",
        response_model=WorkspaceResponse,
        status_code=status.HTTP_201_CREATED,
    )
    async def create_workspace(
        payload: WorkspaceCreateRequest,
        request: Request,
        idempotency_key: IdempotencyKey,
    ) -> WorkspaceResponse:
        context = await auth_context_resolver.resolve(request, require_workspace=False)
        workspace = await execute_workspace_operation(
            service.create_workspace(
                WorkspaceCreation(context.claims.user_id, payload.name, idempotency_key)
            )
        )
        return workspace_response(workspace)

    @router.get(
        "/api/saas/workspaces/{workspace_id}/members",
        response_model=list[MembershipResponse],
    )
    async def list_memberships(
        workspace_id: UUID, request: Request
    ) -> list[MembershipResponse]:
        actor = await resolve_workspace_actor(
            auth_context_resolver,
            request,
            WorkspaceRouteAccess(workspace_id, _OWNERS),
        )
        memberships = await execute_workspace_operation(service.list_memberships(actor))
        return [membership_response(membership) for membership in memberships]

    @router.patch(
        "/api/saas/workspaces/{workspace_id}/members/{target_user_id}",
        response_model=MembershipResponse,
    )
    async def change_membership(
        workspace_id: UUID,
        target_user_id: UUID,
        payload: MembershipChangeRequest,
        request: Request,
    ) -> MembershipResponse:
        actor = await resolve_workspace_actor(
            auth_context_resolver,
            request,
            WorkspaceRouteAccess(workspace_id, _OWNERS),
        )
        membership = await execute_workspace_operation(
            service.change_membership(
                MembershipChange(actor, target_user_id, payload.role)
            )
        )
        return membership_response(membership)

    @router.delete(
        "/api/saas/workspaces/{workspace_id}/members/{target_user_id}",
        status_code=status.HTTP_204_NO_CONTENT,
    )
    async def revoke_membership(
        workspace_id: UUID, target_user_id: UUID, request: Request
    ) -> None:
        actor = await resolve_workspace_actor(
            auth_context_resolver,
            request,
            WorkspaceRouteAccess(workspace_id, _OWNERS),
        )
        await execute_workspace_operation(
            service.revoke_membership(actor, target_user_id)
        )

    @router.get(
        "/api/saas/workspaces/{workspace_id}/invitations",
        response_model=list[InvitationResponse],
    )
    async def list_invitations(
        workspace_id: UUID, request: Request
    ) -> list[InvitationResponse]:
        actor = await resolve_workspace_actor(
            auth_context_resolver,
            request,
            WorkspaceRouteAccess(workspace_id, _MANAGERS),
        )
        invitations = await execute_workspace_operation(service.list_invitations(actor))
        return [invitation_response(invitation) for invitation in invitations]

    @router.post(
        "/api/saas/workspaces/{workspace_id}/invitations",
        response_model=InvitationResponse,
        status_code=status.HTTP_201_CREATED,
    )
    async def create_invitation(
        workspace_id: UUID,
        payload: InvitationCreateRequest,
        request: Request,
        idempotency_key: IdempotencyKey,
    ) -> InvitationResponse:
        actor = await resolve_workspace_actor(
            auth_context_resolver,
            request,
            WorkspaceRouteAccess(workspace_id, _MANAGERS),
        )
        invitation = await execute_workspace_operation(
            service.create_invitation(
                InvitationCreation(actor, payload.email, payload.role, idempotency_key)
            )
        )
        return invitation_response(invitation)

    @router.delete(
        "/api/saas/workspaces/{workspace_id}/invitations/{invitation_id}",
        status_code=status.HTTP_204_NO_CONTENT,
    )
    async def revoke_invitation(
        workspace_id: UUID, invitation_id: UUID, request: Request
    ) -> None:
        actor = await resolve_workspace_actor(
            auth_context_resolver,
            request,
            WorkspaceRouteAccess(workspace_id, _MANAGERS),
        )
        await execute_workspace_operation(
            service.revoke_invitation(actor, invitation_id)
        )

    @router.post(
        "/api/saas/workspace-invitations/accept",
        response_model=WorkspaceResponse,
    )
    async def accept_invitation(
        payload: InvitationAcceptRequest, request: Request
    ) -> WorkspaceResponse:
        context = await auth_context_resolver.resolve(request, require_workspace=False)
        workspace = await execute_workspace_operation(
            service.accept_invitation(
                InvitationAcceptance(
                    context.claims.user_id, context.claims.email, payload.token
                )
            )
        )
        return workspace_response(workspace)

    @router.post(
        "/api/saas/workspaces/{workspace_id}/transfer",
        status_code=status.HTTP_204_NO_CONTENT,
    )
    async def transfer_ownership(
        workspace_id: UUID,
        payload: OwnershipTransferRequest,
        request: Request,
    ) -> None:
        actor = await resolve_workspace_actor(
            auth_context_resolver,
            request,
            WorkspaceRouteAccess(workspace_id, _OWNERS),
        )
        await execute_workspace_operation(
            service.transfer_ownership(OwnershipTransfer(actor, payload.target_user_id))
        )

    @router.post(
        "/api/saas/workspaces/{workspace_id}/archive",
        status_code=status.HTTP_204_NO_CONTENT,
    )
    async def archive_workspace(workspace_id: UUID, request: Request) -> None:
        context = await auth_context_resolver.resolve(request, require_workspace=True)
        actor = selected_workspace_actor(
            context, WorkspaceRouteAccess(workspace_id, _OWNERS)
        )
        await execute_workspace_operation(service.archive_workspace(actor))
        await auth_context_resolver.session_store.select_workspace(
            context.session.handle, None
        )

    @router.get(
        "/api/saas/workspaces/{workspace_id}/audit",
        response_model=list[AuditEventResponse],
    )
    async def list_audit_events(
        workspace_id: UUID, request: Request
    ) -> list[AuditEventResponse]:
        actor = await resolve_workspace_actor(
            auth_context_resolver,
            request,
            WorkspaceRouteAccess(workspace_id, _MANAGERS),
        )
        events = await execute_workspace_operation(service.list_audit_events(actor))
        return [audit_response(event) for event in events]

    return router
