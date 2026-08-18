"""Typed FR-013 workspace lifecycle contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from src.api.saas_sessions import WorkspaceRole


class InvitationRole(StrEnum):
    """Roles an invitation is allowed to grant."""

    ADMIN = "admin"
    MEMBER = "member"


class InvitationStatus(StrEnum):
    """Persisted invitation lifecycle states."""

    PENDING = "pending"
    ACCEPTED = "accepted"
    REVOKED = "revoked"
    EXPIRED = "expired"


class WorkspaceErrorCode(StrEnum):
    """Sanitized failure classes consumed by the HTTP boundary."""

    DENIED = "denied"
    CONFLICT = "conflict"
    UNAVAILABLE = "unavailable"


@dataclass(slots=True)
class WorkspaceOperationError(Exception):
    """Workspace failure without tenant, provider, or database detail."""

    code: WorkspaceErrorCode

    def __str__(self) -> str:
        return f"workspace operation {self.code.value}"


@dataclass(frozen=True, slots=True)
class WorkspaceActor:
    """Trusted actor identity paired with the selected workspace."""

    workspace_id: UUID
    user_id: UUID


@dataclass(frozen=True, slots=True)
class WorkspaceCreation:
    """Idempotent workspace creation command."""

    user_id: UUID
    name: str
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class MembershipChange:
    """Owner-authorized membership role change command."""

    actor: WorkspaceActor
    target_user_id: UUID
    role: InvitationRole


@dataclass(frozen=True, slots=True)
class InvitationCreation:
    """Manager-authorized idempotent invitation command."""

    actor: WorkspaceActor
    email: str
    role: InvitationRole
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class InvitationAcceptance:
    """Invitation acceptance bound to verified provider identity."""

    user_id: UUID
    email: str
    token: str


@dataclass(frozen=True, slots=True)
class OwnershipTransfer:
    """Owner-authorized transfer command."""

    actor: WorkspaceActor
    target_user_id: UUID


@dataclass(frozen=True, slots=True)
class Workspace:
    """One active workspace visible to the current user."""

    id: UUID
    name: str
    role: WorkspaceRole


@dataclass(frozen=True, slots=True)
class MembershipRecord:
    """One active member in an authorized workspace."""

    user_id: UUID
    role: WorkspaceRole


@dataclass(frozen=True, slots=True)
class Invitation:
    """Invitation metadata that never includes the bearer token hash."""

    id: UUID
    email: str
    role: InvitationRole
    status: InvitationStatus = InvitationStatus.PENDING
    expires_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class WorkspaceAuditEvent:
    """Redacted workspace audit event metadata."""

    event_type: str
    subject_id: UUID | None
    created_at: datetime


class WorkspaceService(Protocol):
    """Server-authorized workspace lifecycle boundary."""

    async def list_workspaces(self, user_id: UUID) -> tuple[Workspace, ...]: ...

    async def create_workspace(self, command: WorkspaceCreation) -> Workspace: ...

    async def list_memberships(
        self, actor: WorkspaceActor
    ) -> tuple[MembershipRecord, ...]: ...

    async def change_membership(
        self, command: MembershipChange
    ) -> MembershipRecord: ...

    async def revoke_membership(
        self, actor: WorkspaceActor, target_user_id: UUID
    ) -> None: ...

    async def list_invitations(
        self, actor: WorkspaceActor
    ) -> tuple[Invitation, ...]: ...

    async def create_invitation(self, command: InvitationCreation) -> Invitation: ...

    async def revoke_invitation(
        self, actor: WorkspaceActor, invitation_id: UUID
    ) -> None: ...

    async def accept_invitation(self, command: InvitationAcceptance) -> Workspace: ...

    async def transfer_ownership(self, command: OwnershipTransfer) -> None: ...

    async def archive_workspace(self, actor: WorkspaceActor) -> None: ...

    async def list_audit_events(
        self, actor: WorkspaceActor
    ) -> tuple[WorkspaceAuditEvent, ...]: ...
