"""Postgres workspace and membership lifecycle implementation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final
from uuid import UUID, uuid5

from src.api.saas_sessions import WorkspaceRole
from src.api.saas_workspace_database import (
    actor_has_role,
    set_authenticated_identity,
    workspace_transaction,
)
from src.api.saas_workspace_models import (
    MembershipChange,
    MembershipRecord,
    OwnershipTransfer,
    Workspace,
    WorkspaceActor,
    WorkspaceAuditEvent,
    WorkspaceCreation,
    WorkspaceErrorCode,
    WorkspaceOperationError,
)

_WORKSPACE_ID_NAMESPACE: Final = UUID("564bf556-0fc6-4be5-85e8-2be5791b614e")
_OWNERS: Final = (WorkspaceRole.OWNER,)
_MANAGERS: Final = (WorkspaceRole.OWNER, WorkspaceRole.ADMIN)


@dataclass(frozen=True, slots=True)
class PostgresWorkspaceStore:
    """Persist workspaces and owner-only membership mutations."""

    database_url: str

    async def list_workspaces(self, user_id: UUID) -> tuple[Workspace, ...]:
        """List only active workspaces admitted by user-scoped RLS."""
        async with workspace_transaction(self.database_url) as connection:
            await set_authenticated_identity(connection, user_id)
            rows = await connection.fetch(
                """
                SELECT workspace.id, workspace.name, membership.role::text AS role
                  FROM public.workspace_memberships AS membership
                  JOIN public.workspaces AS workspace
                    ON workspace.id = membership.workspace_id
                 WHERE membership.user_id = $1
                   AND membership.status = 'active'
                   AND workspace.status = 'active'
                 ORDER BY workspace.created_at, workspace.id
                """,
                user_id,
            )
        return tuple(
            Workspace(row["id"], row["name"], WorkspaceRole(row["role"]))
            for row in rows
        )

    async def create_workspace(self, command: WorkspaceCreation) -> Workspace:
        """Create one owner workspace idempotently for a request key."""
        normalized_name = command.name.strip()
        workspace_id = uuid5(
            _WORKSPACE_ID_NAMESPACE,
            f"{command.user_id}:{command.idempotency_key}",
        )
        async with workspace_transaction(self.database_url) as connection:
            await connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended($1, 0))",
                str(workspace_id),
            )
            existing = await connection.fetchrow(
                """
                SELECT id, name, created_by, status::text AS status
                  FROM public.workspaces WHERE id = $1
                """,
                workspace_id,
            )
            if existing is not None:
                if (
                    existing["created_by"] != command.user_id
                    or existing["name"] != normalized_name
                    or existing["status"] != "active"
                ):
                    raise WorkspaceOperationError(WorkspaceErrorCode.CONFLICT)
                return Workspace(workspace_id, normalized_name, WorkspaceRole.OWNER)
            await connection.execute(
                "INSERT INTO public.workspaces (id, name, created_by, account_id) VALUES ($1, $2, $3, $4)",
                workspace_id,
                normalized_name,
                command.user_id,
                command.account_id,
            )
            await connection.execute(
                """
                INSERT INTO public.workspace_memberships (workspace_id, user_id, role)
                VALUES ($1, $2, 'owner')
                """,
                workspace_id,
                command.user_id,
            )
            await connection.execute(
                """
                INSERT INTO public.workspace_audit_events
                    (workspace_id, actor_user_id, event_type, subject_id)
                VALUES ($1, $2, 'workspace.created', $1)
                """,
                workspace_id,
                command.user_id,
            )
        return Workspace(workspace_id, normalized_name, WorkspaceRole.OWNER)

    async def list_memberships(
        self, actor: WorkspaceActor
    ) -> tuple[MembershipRecord, ...]:
        """List active memberships for an owner."""
        async with workspace_transaction(self.database_url) as connection:
            if not await actor_has_role(connection, actor, _OWNERS):
                raise WorkspaceOperationError(WorkspaceErrorCode.DENIED)
            rows = await connection.fetch(
                """
                SELECT user_id, role::text AS role
                  FROM public.workspace_memberships
                 WHERE workspace_id = $1 AND status = 'active'
                 ORDER BY created_at, user_id
                """,
                actor.workspace_id,
            )
        return tuple(
            MembershipRecord(row["user_id"], WorkspaceRole(row["role"])) for row in rows
        )

    async def change_membership(self, command: MembershipChange) -> MembershipRecord:
        """Change an active non-owner membership with owner authority."""
        async with workspace_transaction(self.database_url) as connection:
            if not await actor_has_role(connection, command.actor, _OWNERS):
                raise WorkspaceOperationError(WorkspaceErrorCode.DENIED)
            target = await connection.fetchrow(
                """
                SELECT role::text AS role, status::text AS status
                  FROM public.workspace_memberships
                 WHERE workspace_id = $1 AND user_id = $2 FOR UPDATE
                """,
                command.actor.workspace_id,
                command.target_user_id,
            )
            if (
                target is None
                or target["role"] == WorkspaceRole.OWNER.value
                or target["status"] != "active"
            ):
                raise WorkspaceOperationError(WorkspaceErrorCode.DENIED)
            if target["role"] != command.role.value:
                await connection.execute(
                    """
                    UPDATE public.workspace_memberships SET role = $3
                     WHERE workspace_id = $1 AND user_id = $2
                    """,
                    command.actor.workspace_id,
                    command.target_user_id,
                    command.role.value,
                )
                await connection.execute(
                    """
                    INSERT INTO public.workspace_audit_events
                        (workspace_id, actor_user_id, event_type, subject_id)
                    VALUES ($1, $2, 'membership.role_changed', $3)
                    """,
                    command.actor.workspace_id,
                    command.actor.user_id,
                    command.target_user_id,
                )
        return MembershipRecord(
            command.target_user_id, WorkspaceRole(command.role.value)
        )

    async def revoke_membership(
        self, actor: WorkspaceActor, target_user_id: UUID
    ) -> None:
        """Revoke an active non-owner membership idempotently."""
        async with workspace_transaction(self.database_url) as connection:
            if not await actor_has_role(connection, actor, _OWNERS):
                raise WorkspaceOperationError(WorkspaceErrorCode.DENIED)
            target = await connection.fetchrow(
                """
                SELECT role::text AS role, status::text AS status
                  FROM public.workspace_memberships
                 WHERE workspace_id = $1 AND user_id = $2 FOR UPDATE
                """,
                actor.workspace_id,
                target_user_id,
            )
            if target is None or target["role"] == WorkspaceRole.OWNER.value:
                raise WorkspaceOperationError(WorkspaceErrorCode.DENIED)
            if target["status"] == "revoked":
                return
            await connection.execute(
                """
                UPDATE public.workspace_memberships
                   SET status = 'revoked', revoked_at = now()
                 WHERE workspace_id = $1 AND user_id = $2
                """,
                actor.workspace_id,
                target_user_id,
            )
            await connection.execute(
                """
                INSERT INTO public.workspace_audit_events
                    (workspace_id, actor_user_id, event_type, subject_id)
                VALUES ($1, $2, 'membership.revoked', $3)
                """,
                actor.workspace_id,
                actor.user_id,
                target_user_id,
            )

    async def transfer_ownership(self, command: OwnershipTransfer) -> None:
        """Transfer ownership only to an active admin."""
        async with workspace_transaction(self.database_url) as connection:
            if not await actor_has_role(connection, command.actor, _OWNERS):
                raise WorkspaceOperationError(WorkspaceErrorCode.DENIED)
            target_is_admin = await actor_has_role(
                connection,
                WorkspaceActor(command.actor.workspace_id, command.target_user_id),
                (WorkspaceRole.ADMIN,),
            )
            if not target_is_admin:
                raise WorkspaceOperationError(WorkspaceErrorCode.DENIED)
            await connection.execute(
                "SELECT private.transfer_workspace_ownership($1, $2, $3)",
                command.actor.workspace_id,
                command.actor.user_id,
                command.target_user_id,
            )

    async def archive_workspace(self, actor: WorkspaceActor) -> None:
        """Archive an active workspace with owner authority."""
        async with workspace_transaction(self.database_url) as connection:
            if not await actor_has_role(connection, actor, _OWNERS):
                raise WorkspaceOperationError(WorkspaceErrorCode.DENIED)
            await connection.execute(
                "SELECT private.archive_workspace($1, $2)",
                actor.workspace_id,
                actor.user_id,
            )

    async def list_audit_events(
        self, actor: WorkspaceActor
    ) -> tuple[WorkspaceAuditEvent, ...]:
        """Return redacted audit metadata to owners and admins."""
        async with workspace_transaction(self.database_url) as connection:
            if not await actor_has_role(connection, actor, _MANAGERS):
                raise WorkspaceOperationError(WorkspaceErrorCode.DENIED)
            rows = await connection.fetch(
                """
                SELECT event_type, subject_id, created_at
                  FROM public.workspace_audit_events
                 WHERE workspace_id = $1 ORDER BY created_at DESC, id DESC LIMIT 200
                """,
                actor.workspace_id,
            )
        return tuple(
            WorkspaceAuditEvent(row["event_type"], row["subject_id"], row["created_at"])
            for row in rows
        )
