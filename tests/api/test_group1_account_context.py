from __future__ import annotations

import os
from uuid import UUID, uuid4

import anyio
import asyncpg
import pytest

from src.api.saas_account_context import PostgresAccountContextResolver
from src.api.saas_account_models import (
    AccountContextError,
    AccountContextErrorCode,
    AccountStatus,
    WorkspaceContextStatus,
)
from src.api.saas_account_store import PostgresAccountStore
from src.api.saas_sessions import WorkspaceRole


def _database_url() -> str:
    value = os.environ.get("GROUP1_TEST_DATABASE_URL")
    if value is None:
        pytest.skip("GROUP1_TEST_DATABASE_URL is required for the Postgres contract")
    return value


async def _insert_owned_account(
    database_url: str, account_id: UUID, user_id: UUID, label: str
) -> None:
    connection = await asyncpg.connect(database_url)
    try:
        async with connection.transaction():
            await connection.execute(
                "INSERT INTO public.accounts (id, label) VALUES ($1, $2)",
                account_id,
                label,
            )
            await connection.execute(
                """
                INSERT INTO public.account_memberships (account_id, user_id)
                VALUES ($1, $2)
                """,
                account_id,
                user_id,
            )
    finally:
        await connection.close()


async def _insert_workspace(
    database_url: str,
    *,
    account_id: UUID,
    owner_id: UUID,
    member_id: UUID | None = None,
) -> UUID:
    workspace_id = uuid4()
    connection = await asyncpg.connect(database_url)
    try:
        async with connection.transaction():
            await connection.execute(
                """
                INSERT INTO public.workspaces (id, account_id, name, created_by)
                VALUES ($1, $2, 'Context workspace', $3)
                """,
                workspace_id,
                account_id,
                owner_id,
            )
            await connection.execute(
                """
                INSERT INTO public.workspace_memberships
                    (workspace_id, user_id, role)
                VALUES ($1, $2, 'owner')
                """,
                workspace_id,
                owner_id,
            )
            if member_id is not None:
                await connection.execute(
                    """
                    INSERT INTO public.workspace_memberships
                        (workspace_id, user_id, role)
                    VALUES ($1, $2, 'member')
                    """,
                    workspace_id,
                    member_id,
                )
    finally:
        await connection.close()
    return workspace_id


@pytest.mark.anyio
async def test_concurrent_new_user_bootstrap_is_idempotent() -> None:
    database_url = _database_url()
    user_id = uuid4()
    store = PostgresAccountStore(database_url)
    results: list[UUID] = []

    async def bootstrap() -> None:
        account = await store.bootstrap_default_account(user_id)
        results.append(account.id)

    async with anyio.create_task_group() as tasks:
        for _ in range(10):
            tasks.start_soon(bootstrap)

    connection = await asyncpg.connect(database_url)
    try:
        counts = await connection.fetchrow(
            """
            SELECT
                (SELECT count(*) FROM public.accounts WHERE id = $1) AS accounts,
                (SELECT count(*) FROM public.account_memberships
                  WHERE account_id = $1 AND user_id = $2) AS memberships
            """,
            results[0],
            user_id,
        )
    finally:
        await connection.close()

    assert len(set(results)) == 1
    assert counts is not None
    assert counts["accounts"] == 1
    assert counts["memberships"] == 1


@pytest.mark.anyio
async def test_owned_and_foreign_contexts_are_grouped_without_billing_leak() -> None:
    database_url = _database_url()
    user_id = uuid4()
    foreign_owner_id = uuid4()
    owned_account_id = uuid4()
    foreign_account_id = uuid4()
    await _insert_owned_account(database_url, owned_account_id, user_id, "Owned")
    await _insert_owned_account(
        database_url, foreign_account_id, foreign_owner_id, "Foreign"
    )
    owned_workspace_id = await _insert_workspace(
        database_url, account_id=owned_account_id, owner_id=user_id
    )
    foreign_workspace_id = await _insert_workspace(
        database_url,
        account_id=foreign_account_id,
        owner_id=foreign_owner_id,
        member_id=user_id,
    )
    resolver = PostgresAccountContextResolver(PostgresAccountStore(database_url))

    contexts = await resolver.available(user_id)
    owned = next(context for context in contexts if context.id == owned_account_id)
    foreign = next(context for context in contexts if context.id == foreign_account_id)
    selected = await resolver.resolve(
        user_id,
        account_id=foreign_account_id,
        workspace_id=foreign_workspace_id,
    )

    assert owned.status is AccountStatus.ACTIVE
    assert owned.owner_projection is not None
    assert owned.owner_projection.can_manage_billing
    assert owned.owner_projection.can_view_plan
    assert owned.owner_projection.can_view_limits
    assert owned.workspaces[0].id == owned_workspace_id
    assert foreign.owner_projection is None
    assert foreign.workspaces[0].role is WorkspaceRole.MEMBER
    assert selected.workspace is not None
    assert selected.workspace.status is WorkspaceContextStatus.ACTIVE
    assert selected.workspace.role is WorkspaceRole.MEMBER


@pytest.mark.anyio
async def test_forged_stale_and_ambiguous_selections_fail_closed() -> None:
    database_url = _database_url()
    user_id = uuid4()
    foreign_owner_id = uuid4()
    first_account_id = uuid4()
    second_account_id = uuid4()
    foreign_account_id = uuid4()
    await _insert_owned_account(database_url, first_account_id, user_id, "First")
    await _insert_owned_account(database_url, second_account_id, user_id, "Second")
    await _insert_owned_account(
        database_url, foreign_account_id, foreign_owner_id, "Foreign"
    )
    foreign_workspace_id = await _insert_workspace(
        database_url,
        account_id=foreign_account_id,
        owner_id=foreign_owner_id,
        member_id=user_id,
    )
    resolver = PostgresAccountContextResolver(PostgresAccountStore(database_url))
    connection = await asyncpg.connect(database_url)
    try:
        before = await connection.fetchval(
            "SELECT count(*) FROM public.account_memberships"
        )
        with pytest.raises(AccountContextError) as forged:
            await resolver.resolve(
                user_id,
                account_id=uuid4(),
                workspace_id=foreign_workspace_id,
            )
        after = await connection.fetchval(
            "SELECT count(*) FROM public.account_memberships"
        )
        await connection.execute(
            """
            UPDATE public.workspaces
               SET status = 'archived', archived_at = now(), archived_by = $2
             WHERE id = $1
            """,
            foreign_workspace_id,
            foreign_owner_id,
        )
    finally:
        await connection.close()

    with pytest.raises(AccountContextError) as archived:
        await resolver.resolve(
            user_id,
            account_id=foreign_account_id,
            workspace_id=foreign_workspace_id,
        )
    with pytest.raises(AccountContextError) as ambiguous:
        await resolver.owned_account_for_new_workspace(
            user_id, selected_account_id=None
        )
    selected_account = await resolver.owned_account_for_new_workspace(
        user_id, selected_account_id=second_account_id
    )

    assert before == after
    assert forged.value.code is AccountContextErrorCode.DENIED
    assert archived.value.code is AccountContextErrorCode.DENIED
    assert ambiguous.value.code is AccountContextErrorCode.CONFLICT
    assert selected_account == second_account_id


@pytest.mark.anyio
async def test_revoked_foreign_membership_disappears_from_available_contexts() -> None:
    database_url = _database_url()
    user_id = uuid4()
    owner_id = uuid4()
    account_id = uuid4()
    await _insert_owned_account(database_url, account_id, owner_id, "Foreign")
    workspace_id = await _insert_workspace(
        database_url, account_id=account_id, owner_id=owner_id, member_id=user_id
    )
    store = PostgresAccountStore(database_url)
    connection = await asyncpg.connect(database_url)
    try:
        await connection.execute(
            """
            UPDATE public.workspace_memberships
               SET status = 'revoked', revoked_at = now()
             WHERE workspace_id = $1 AND user_id = $2
            """,
            workspace_id,
            user_id,
        )
    finally:
        await connection.close()

    assert await store.list_available_contexts(user_id) == ()
