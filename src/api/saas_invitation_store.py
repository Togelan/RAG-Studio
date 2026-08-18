"""Postgres invitation lifecycle with one-use hashed bearer tokens."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final
from uuid import UUID

from src.api.saas_invitation_delivery import (
    InvitationMailer,
    InvitationMessage,
    InvitationTokenIssuer,
)
from src.api.saas_sessions import WorkspaceRole
from src.api.saas_workspace_database import actor_has_role, workspace_transaction
from src.api.saas_workspace_models import (
    Invitation,
    InvitationAcceptance,
    InvitationCreation,
    InvitationRole,
    InvitationStatus,
    Workspace,
    WorkspaceActor,
    WorkspaceErrorCode,
    WorkspaceOperationError,
)

_INVITATION_LIFETIME: Final = timedelta(days=7)
_MANAGERS: Final = (WorkspaceRole.OWNER, WorkspaceRole.ADMIN)


@dataclass(frozen=True, slots=True)
class PostgresInvitationStore:
    """Persist invitations and deliver only their raw bearer token."""

    database_url: str
    token_issuer: InvitationTokenIssuer
    mailer: InvitationMailer

    async def list_invitations(self, actor: WorkspaceActor) -> tuple[Invitation, ...]:
        """List redacted invitation metadata for owners and admins."""
        async with workspace_transaction(self.database_url) as connection:
            if not await actor_has_role(connection, actor, _MANAGERS):
                raise WorkspaceOperationError(WorkspaceErrorCode.DENIED)
            rows = await connection.fetch(
                """
                SELECT id, email, role::text AS role, status::text AS status,
                       expires_at
                  FROM public.workspace_invitations
                 WHERE workspace_id = $1
                 ORDER BY created_at DESC, id DESC
                """,
                actor.workspace_id,
            )
        return tuple(
            Invitation(
                id=row["id"],
                email=row["email"],
                role=InvitationRole(row["role"]),
                status=InvitationStatus(row["status"]),
                expires_at=row["expires_at"],
            )
            for row in rows
        )

    async def create_invitation(self, command: InvitationCreation) -> Invitation:
        """Create or retry one manager-authorized invitation and send its link."""
        normalized_email = command.email.strip().lower()
        raw_token = self.token_issuer.issue(command)
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        async with workspace_transaction(self.database_url) as connection:
            if not await actor_has_role(connection, command.actor, _MANAGERS):
                raise WorkspaceOperationError(WorkspaceErrorCode.DENIED)
            await connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended($1, 0))", token_hash
            )
            row = await connection.fetchrow(
                """
                SELECT id, workspace_id, email, role::text AS role,
                       status::text AS status, expires_at, created_by
                  FROM public.workspace_invitations WHERE token_hash = $1
                """,
                token_hash,
            )
            if row is None:
                expires_at = datetime.now(UTC) + _INVITATION_LIFETIME
                invitation_id = await connection.fetchval(
                    "SELECT private.create_workspace_invitation($1, $2, $3, $4, $5, $6)",
                    command.actor.workspace_id,
                    normalized_email,
                    command.role.value,
                    token_hash,
                    expires_at,
                    command.actor.user_id,
                )
                invitation = Invitation(
                    invitation_id,
                    normalized_email,
                    command.role,
                    InvitationStatus.PENDING,
                    expires_at,
                )
            else:
                if (
                    row["workspace_id"] != command.actor.workspace_id
                    or row["email"] != normalized_email
                    or row["role"] != command.role.value
                    or row["created_by"] != command.actor.user_id
                    or row["status"] not in {"pending", "accepted"}
                ):
                    raise WorkspaceOperationError(WorkspaceErrorCode.CONFLICT)
                invitation = Invitation(
                    row["id"],
                    row["email"],
                    command.role,
                    InvitationStatus(row["status"]),
                    row["expires_at"],
                )
        if invitation.status is InvitationStatus.PENDING:
            await self.mailer.send(
                InvitationMessage(
                    email=normalized_email,
                    token=raw_token,
                    workspace_id=command.actor.workspace_id,
                )
            )
        return invitation

    async def revoke_invitation(
        self, actor: WorkspaceActor, invitation_id: UUID
    ) -> None:
        """Revoke a pending invitation idempotently for owners and admins."""
        async with workspace_transaction(self.database_url) as connection:
            if not await actor_has_role(connection, actor, _MANAGERS):
                raise WorkspaceOperationError(WorkspaceErrorCode.DENIED)
            await connection.execute(
                "SELECT private.revoke_workspace_invitation($1, $2, $3)",
                invitation_id,
                actor.workspace_id,
                actor.user_id,
            )

    async def accept_invitation(self, command: InvitationAcceptance) -> Workspace:
        """Accept once, or replay for the same verified user, under a row lock."""
        token_hash = hashlib.sha256(command.token.encode()).hexdigest()
        denied = False
        workspace: Workspace | None = None
        async with workspace_transaction(self.database_url) as connection:
            await connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended($1, 0))", token_hash
            )
            invitation = await connection.fetchrow(
                """
                SELECT id, workspace_id, email, status::text AS status, expires_at
                  FROM public.workspace_invitations
                 WHERE token_hash = $1 FOR UPDATE
                """,
                token_hash,
            )
            if (
                invitation is None
                or invitation["email"] != command.email.strip().lower()
            ):
                raise WorkspaceOperationError(WorkspaceErrorCode.DENIED)
            if invitation["status"] == InvitationStatus.PENDING.value and invitation[
                "expires_at"
            ] <= datetime.now(UTC):
                await connection.execute(
                    """
                    UPDATE public.workspace_invitations SET status = 'expired'
                     WHERE id = $1
                    """,
                    invitation["id"],
                )
                await connection.execute(
                    """
                    INSERT INTO public.workspace_audit_events
                        (workspace_id, event_type, subject_id)
                    VALUES ($1, 'invitation.expired', $2)
                    """,
                    invitation["workspace_id"],
                    invitation["id"],
                )
                denied = True
            else:
                await connection.execute(
                    "SELECT private.accept_workspace_invitation($1, $2, $3)",
                    token_hash,
                    command.user_id,
                    command.email,
                )
                row = await connection.fetchrow(
                    """
                    SELECT workspace.id, workspace.name, membership.role::text AS role
                      FROM public.workspace_memberships AS membership
                      JOIN public.workspaces AS workspace
                        ON workspace.id = membership.workspace_id
                     WHERE membership.user_id = $1
                       AND membership.workspace_id = $2
                       AND membership.status = 'active'
                       AND workspace.status = 'active'
                    """,
                    command.user_id,
                    invitation["workspace_id"],
                )
                if row is not None:
                    workspace = Workspace(
                        row["id"], row["name"], WorkspaceRole(row["role"])
                    )
        if denied or workspace is None:
            raise WorkspaceOperationError(WorkspaceErrorCode.DENIED)
        return workspace
