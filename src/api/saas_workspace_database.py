"""Bounded Postgres transaction helpers for FR-013 workspace services."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

import asyncpg

from src.api.saas_sessions import WorkspaceRole
from src.api.saas_workspace_models import (
    WorkspaceActor,
    WorkspaceErrorCode,
    WorkspaceOperationError,
)


@asynccontextmanager
async def workspace_transaction(database_url: str) -> AsyncIterator[asyncpg.Connection]:
    """Open one bounded transaction and sanitize infrastructure failures."""
    try:
        connection = await asyncpg.connect(database_url, timeout=5.0)
        try:
            async with connection.transaction():
                yield connection
        finally:
            await connection.close(timeout=5.0)
    except WorkspaceOperationError:
        raise
    except asyncpg.PostgresError as error:
        raise _mapped_postgres_error(error.sqlstate) from None
    except OSError, TimeoutError:
        raise WorkspaceOperationError(WorkspaceErrorCode.UNAVAILABLE) from None


async def set_authenticated_identity(
    connection: asyncpg.Connection, user_id: UUID
) -> None:
    """Apply the caller identity before a user-scoped RLS query."""
    await connection.execute("SET LOCAL ROLE authenticated")
    await connection.execute(
        "SELECT set_config('request.jwt.claim.sub', $1, true)", str(user_id)
    )


async def actor_has_role(
    connection: asyncpg.Connection,
    actor: WorkspaceActor,
    allowed_roles: tuple[WorkspaceRole, ...],
) -> bool:
    """Revalidate an active actor role inside the mutation transaction."""
    return bool(
        await connection.fetchval(
            "SELECT private.actor_has_role($1, $2, $3::public.workspace_role[])",
            actor.workspace_id,
            actor.user_id,
            [role.value for role in allowed_roles],
        )
    )


def _mapped_postgres_error(sqlstate: str | None) -> WorkspaceOperationError:
    if sqlstate == "28000":
        return WorkspaceOperationError(WorkspaceErrorCode.DENIED)
    if sqlstate in {"23505", "23514", "55000"}:
        return WorkspaceOperationError(WorkspaceErrorCode.CONFLICT)
    return WorkspaceOperationError(WorkspaceErrorCode.UNAVAILABLE)
