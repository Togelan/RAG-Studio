"""Pydantic boundary schemas for FR-013 workspace routes."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from src.api.saas_sessions import WorkspaceRole
from src.api.saas_workspace_models import (
    Invitation,
    InvitationRole,
    MembershipRecord,
    Workspace,
    WorkspaceAuditEvent,
)


class WorkspaceCreateRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str = Field(min_length=1, max_length=120)


class MembershipChangeRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    role: InvitationRole


class InvitationCreateRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    email: str = Field(min_length=3, max_length=320, pattern=r"^[^@\s]+@[^@\s]+$")
    role: InvitationRole


class InvitationAcceptRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    token: str = Field(min_length=43, max_length=256, pattern=r"^[A-Za-z0-9_-]+$")


class OwnershipTransferRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    target_user_id: UUID


class WorkspaceResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    name: str
    role: WorkspaceRole


class MembershipResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    user_id: UUID
    role: WorkspaceRole


class InvitationResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    email: str
    role: InvitationRole
    status: str
    expires_at: datetime | None


class AuditEventResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    event_type: str
    subject_id: UUID | None
    created_at: datetime


def workspace_response(workspace: Workspace) -> WorkspaceResponse:
    return WorkspaceResponse(id=workspace.id, name=workspace.name, role=workspace.role)


def membership_response(membership: MembershipRecord) -> MembershipResponse:
    return MembershipResponse(user_id=membership.user_id, role=membership.role)


def invitation_response(invitation: Invitation) -> InvitationResponse:
    """Serialize invitation metadata without its bearer token or hash."""
    return InvitationResponse(
        id=invitation.id,
        email=invitation.email,
        role=invitation.role,
        status=invitation.status.value,
        expires_at=invitation.expires_at,
    )


def audit_response(event: WorkspaceAuditEvent) -> AuditEventResponse:
    """Serialize only the redacted audit projection."""
    return AuditEventResponse(
        event_type=event.event_type,
        subject_id=event.subject_id,
        created_at=event.created_at,
    )
