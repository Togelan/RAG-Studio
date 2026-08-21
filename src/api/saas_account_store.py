"""Postgres authority for Account and Workspace context selection."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from hashlib import md5
from uuid import UUID

import asyncpg

from src.api.saas_account_models import (
    AccountContext,
    AccountContextError,
    AccountContextErrorCode,
    AccountOwnerProjection,
    AccountStatus,
    SelectedAccountContext,
    WorkspaceContext,
)
from src.api.saas_sessions import WorkspaceRole
from src.api.saas_workspace_database import set_authenticated_identity


@asynccontextmanager
async def _account_transaction(
    database_url: str,
) -> AsyncIterator[asyncpg.Connection]:
    try:
        connection = await asyncpg.connect(database_url, timeout=5.0)
        try:
            async with connection.transaction():
                yield connection
        finally:
            await connection.close(timeout=5.0)
    except AccountContextError:
        raise
    except asyncpg.PostgresError as error:
        raise _mapped_error(error.sqlstate) from None
    except OSError, TimeoutError:
        raise AccountContextError(AccountContextErrorCode.UNAVAILABLE) from None


def _mapped_error(sqlstate: str | None) -> AccountContextError:
    if sqlstate == "28000":
        return AccountContextError(AccountContextErrorCode.DENIED)
    if sqlstate in {"23505", "23514", "55000"}:
        return AccountContextError(AccountContextErrorCode.CONFLICT)
    return AccountContextError(AccountContextErrorCode.UNAVAILABLE)


def _default_account_id(user_id: UUID) -> UUID:
    digest = md5(
        f"rag-studio:account:v1:{user_id}".encode(), usedforsecurity=False
    ).hexdigest()
    return UUID(
        f"{digest[:8]}-{digest[8:12]}-4{digest[13:16]}-8{digest[17:20]}-{digest[20:32]}"
    )


@dataclass(frozen=True, slots=True)
class PostgresAccountStore:
    """Resolve Account authority from current Postgres rows."""

    database_url: str

    async def bootstrap_default_account(self, user_id: UUID) -> AccountContext:
        """Create one deterministic default Account for a new user."""
        account_id = _default_account_id(user_id)
        label = f"Account {str(user_id).replace('-', '')[:8].upper()}"
        async with _account_transaction(self.database_url) as connection:
            await connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended($1, 0))",
                str(account_id),
            )
            await connection.execute(
                """
                INSERT INTO public.accounts (id, label)
                VALUES ($1, $2)
                ON CONFLICT (id) DO NOTHING
                """,
                account_id,
                label,
            )
            await connection.execute(
                """
                INSERT INTO public.account_memberships (account_id, user_id)
                VALUES ($1, $2)
                ON CONFLICT (account_id, user_id) DO NOTHING
                """,
                account_id,
                user_id,
            )
            row = await connection.fetchrow(
                """
                SELECT account.id, account.label
                  FROM public.accounts AS account
                  JOIN public.account_memberships AS membership
                    ON membership.account_id = account.id
                 WHERE account.id = $1 AND membership.user_id = $2
                   AND membership.role = 'owner'
                   AND membership.status = 'active'
                """,
                account_id,
                user_id,
            )
        if row is None:
            raise AccountContextError(AccountContextErrorCode.CONFLICT)
        return AccountContext(
            id=row["id"],
            label=row["label"],
            status=AccountStatus.ACTIVE,
            owner_projection=AccountOwnerProjection(),
            workspaces=(),
        )

    async def list_available_contexts(
        self, user_id: UUID
    ) -> tuple[AccountContext, ...]:
        """Group owned Accounts and active foreign memberships by Account."""
        async with _account_transaction(self.database_url) as connection:
            await set_authenticated_identity(connection, user_id)
            owned_rows = await connection.fetch(
                """
                SELECT account.id, account.label
                  FROM public.accounts AS account
                  JOIN public.account_memberships AS membership
                    ON membership.account_id = account.id
                 WHERE membership.user_id = $1
                   AND membership.role = 'owner'
                   AND membership.status = 'active'
                 ORDER BY account.created_at, account.id
                """,
                user_id,
            )
            workspace_rows = await connection.fetch(
                """
                SELECT label.account_id, label.account_label,
                       workspace.id, workspace.name,
                       membership.role::text AS role
                  FROM public.workspace_memberships AS membership
                  JOIN public.workspaces AS workspace
                    ON workspace.id = membership.workspace_id
                  JOIN public.workspace_account_labels AS label
                    ON label.workspace_id = workspace.id
                 WHERE membership.user_id = $1
                   AND membership.status = 'active'
                   AND workspace.status = 'active'
                 ORDER BY workspace.created_at, workspace.id
                """,
                user_id,
            )
        return _group_contexts(owned_rows, workspace_rows)

    async def resolve_selection(
        self,
        user_id: UUID,
        *,
        account_id: UUID,
        workspace_id: UUID | None,
    ) -> SelectedAccountContext:
        """Resolve an explicit selection only from active trusted rows."""
        async with _account_transaction(self.database_url) as connection:
            await set_authenticated_identity(connection, user_id)
            owned = bool(
                await connection.fetchval(
                    "SELECT private.has_active_account_ownership($1)", account_id
                )
            )
            if workspace_id is None:
                if not owned:
                    raise AccountContextError(AccountContextErrorCode.DENIED)
                account_row = await connection.fetchrow(
                    "SELECT id, label FROM public.accounts WHERE id = $1",
                    account_id,
                )
                if account_row is None:
                    raise AccountContextError(AccountContextErrorCode.DENIED)
                return SelectedAccountContext(
                    account=AccountContext(
                        account_row["id"],
                        account_row["label"],
                        AccountStatus.ACTIVE,
                        AccountOwnerProjection(),
                        (),
                    ),
                    workspace=None,
                )
            row = await connection.fetchrow(
                """
                SELECT label.account_id, label.account_label,
                       workspace.id, workspace.name,
                       membership.role::text AS role
                  FROM public.workspace_memberships AS membership
                  JOIN public.workspaces AS workspace
                    ON workspace.id = membership.workspace_id
                  JOIN public.workspace_account_labels AS label
                    ON label.workspace_id = workspace.id
                 WHERE membership.user_id = $1
                   AND membership.workspace_id = $2
                   AND label.account_id = $3
                   AND membership.status = 'active'
                   AND workspace.status = 'active'
                """,
                user_id,
                workspace_id,
                account_id,
            )
        if row is None:
            raise AccountContextError(AccountContextErrorCode.DENIED)
        workspace = _workspace_from_row(row)
        account = AccountContext(
            id=row["account_id"],
            label=row["account_label"],
            status=AccountStatus.ACTIVE,
            owner_projection=AccountOwnerProjection() if owned else None,
            workspaces=(workspace,),
        )
        return SelectedAccountContext(account=account, workspace=workspace)

    async def owned_account_for_new_workspace(
        self, user_id: UUID, selected_account_id: UUID | None
    ) -> UUID:
        """Return an explicitly owned Account, never an arbitrary first row."""
        contexts = await self.list_available_contexts(user_id)
        owned = tuple(
            context for context in contexts if context.owner_projection is not None
        )
        if selected_account_id is not None:
            if any(context.id == selected_account_id for context in owned):
                return selected_account_id
            raise AccountContextError(AccountContextErrorCode.DENIED)
        if not owned:
            return (await self.bootstrap_default_account(user_id)).id
        if len(owned) == 1:
            return owned[0].id
        raise AccountContextError(AccountContextErrorCode.CONFLICT)


def _workspace_from_row(row: asyncpg.Record) -> WorkspaceContext:
    return WorkspaceContext(
        id=row["id"],
        name=row["name"],
        role=WorkspaceRole(row["role"]),
    )


def _group_contexts(
    owned_rows: list[asyncpg.Record], workspace_rows: list[asyncpg.Record]
) -> tuple[AccountContext, ...]:
    owned = {row["id"]: row["label"] for row in owned_rows}
    labels = dict(owned)
    workspaces: dict[UUID, list[WorkspaceContext]] = {
        account_id: [] for account_id in owned
    }
    for row in workspace_rows:
        account_id = row["account_id"]
        labels[account_id] = row["account_label"]
        workspaces.setdefault(account_id, []).append(_workspace_from_row(row))
    return tuple(
        AccountContext(
            id=account_id,
            label=label,
            status=AccountStatus.ACTIVE,
            owner_projection=AccountOwnerProjection() if account_id in owned else None,
            workspaces=tuple(workspaces.get(account_id, ())),
        )
        for account_id, label in labels.items()
    )
