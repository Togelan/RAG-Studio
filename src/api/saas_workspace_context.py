"""User-scoped Postgres membership resolution for the SaaS BFF."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

import asyncpg

from src.api.saas_sessions import Membership, WorkspaceRole


class MembershipResolutionUnavailableError(RuntimeError):
    """The membership authority could not complete a bounded lookup."""


@dataclass(frozen=True, slots=True)
class PostgresMembershipResolver:
    """Resolve active membership with the caller's RLS identity."""

    database_url: str

    async def resolve(self, user_id: UUID, workspace_id: UUID) -> Membership | None:
        """Return one active membership after independent RLS enforcement."""
        try:
            connection = await asyncpg.connect(self.database_url, timeout=5.0)
            try:
                async with connection.transaction():
                    await connection.execute("SET LOCAL ROLE authenticated")
                    await connection.execute(
                        "SELECT set_config('request.jwt.claim.sub', $1, true)",
                        str(user_id),
                    )
                    row = await connection.fetchrow(
                        """
                        SELECT membership.workspace_id, membership.role::text AS role
                          FROM public.workspace_memberships AS membership
                          JOIN public.workspaces AS workspace
                            ON workspace.id = membership.workspace_id
                         WHERE membership.workspace_id = $1
                           AND membership.user_id = $2
                           AND membership.status = 'active'
                           AND workspace.status = 'active'
                        """,
                        workspace_id,
                        user_id,
                    )
            finally:
                await connection.close(timeout=5.0)
        except asyncpg.PostgresError, OSError, TimeoutError:
            raise MembershipResolutionUnavailableError from None
        if row is None:
            return None
        return Membership(
            workspace_id=row["workspace_id"],
            role=WorkspaceRole(row["role"]),
        )
