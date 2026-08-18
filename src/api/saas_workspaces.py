"""FR-013 workspace service facade."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from pydantic import SecretStr

from src.api.saas_invitation_delivery import (
    InvitationMailer,
    InvitationTokenIssuer,
    SmtpInvitationMailer,
    UnavailableInvitationMailer,
    load_invitation_delivery_configuration,
)
from src.api.saas_invitation_store import PostgresInvitationStore
from src.api.saas_workspace_models import (
    Invitation,
    InvitationAcceptance,
    InvitationCreation,
    MembershipChange,
    MembershipRecord,
    OwnershipTransfer,
    Workspace,
    WorkspaceActor,
    WorkspaceAuditEvent,
    WorkspaceCreation,
)
from src.api.saas_workspace_store import PostgresWorkspaceStore


@dataclass(frozen=True, slots=True)
class PostgresWorkspaceService:
    """Compose workspace and invitation stores behind one route contract."""

    workspaces: PostgresWorkspaceStore
    invitations: PostgresInvitationStore

    async def list_workspaces(self, user_id: UUID) -> tuple[Workspace, ...]:
        return await self.workspaces.list_workspaces(user_id)

    async def create_workspace(self, command: WorkspaceCreation) -> Workspace:
        return await self.workspaces.create_workspace(command)

    async def list_memberships(
        self, actor: WorkspaceActor
    ) -> tuple[MembershipRecord, ...]:
        return await self.workspaces.list_memberships(actor)

    async def change_membership(self, command: MembershipChange) -> MembershipRecord:
        return await self.workspaces.change_membership(command)

    async def revoke_membership(
        self, actor: WorkspaceActor, target_user_id: UUID
    ) -> None:
        await self.workspaces.revoke_membership(actor, target_user_id)

    async def list_invitations(self, actor: WorkspaceActor) -> tuple[Invitation, ...]:
        return await self.invitations.list_invitations(actor)

    async def create_invitation(self, command: InvitationCreation) -> Invitation:
        return await self.invitations.create_invitation(command)

    async def revoke_invitation(
        self, actor: WorkspaceActor, invitation_id: UUID
    ) -> None:
        await self.invitations.revoke_invitation(actor, invitation_id)

    async def accept_invitation(self, command: InvitationAcceptance) -> Workspace:
        return await self.invitations.accept_invitation(command)

    async def transfer_ownership(self, command: OwnershipTransfer) -> None:
        await self.workspaces.transfer_ownership(command)

    async def archive_workspace(self, actor: WorkspaceActor) -> None:
        await self.workspaces.archive_workspace(actor)

    async def list_audit_events(
        self, actor: WorkspaceActor
    ) -> tuple[WorkspaceAuditEvent, ...]:
        return await self.workspaces.list_audit_events(actor)


def create_postgres_workspace_service(
    database_url: str, invitation_secret: SecretStr
) -> PostgresWorkspaceService:
    """Build Task 5 persistence with configured SMTP or fail-closed delivery."""
    configuration = load_invitation_delivery_configuration()
    mailer: InvitationMailer
    if configuration is None:
        mailer = UnavailableInvitationMailer()
    else:
        mailer = SmtpInvitationMailer(configuration)
    return PostgresWorkspaceService(
        workspaces=PostgresWorkspaceStore(database_url),
        invitations=PostgresInvitationStore(
            database_url,
            InvitationTokenIssuer(invitation_secret),
            mailer,
        ),
    )
