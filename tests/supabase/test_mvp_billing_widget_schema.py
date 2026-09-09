from __future__ import annotations

import os
import re
from pathlib import Path
from uuid import UUID

import anyio
import asyncpg
import pytest

ROOT = Path(__file__).resolve().parents[2]
PERSONAL_LABS_MIGRATION = (
    ROOT / "supabase/migrations/20260821090000_group2_personal_labs.sql"
)
MIGRATION = (
    ROOT / "supabase/migrations/20260825120000_mvp_personal_lab_billing_widget.sql"
)
FOUNDATION_MIGRATIONS = (
    ROOT / "docker/stage3/001-auth-schema.sql",
    ROOT / "supabase/migrations/20260816165319_stage3_tenant_schema.sql",
    ROOT / "supabase/migrations/20260816170226_stage3_tenant_routines_rls.sql",
    ROOT / "supabase/migrations/20260816170824_stage3_tenant_rls_grants.sql",
    ROOT / "supabase/migrations/20260817090000_stage3_chatbot_lifecycle.sql",
    ROOT / "supabase/migrations/20260820090000_group1_accounts_sessions.sql",
    PERSONAL_LABS_MIGRATION,
)
LAB_ID = UUID("30000000-0000-4000-8000-000000000003")
USER_ID = UUID("40000000-0000-4000-8000-000000000004")
PUBLICATION_KEY = UUID("50000000-0000-4000-8000-000000000005")
SECOND_LAB_ID = UUID("60000000-0000-4000-8000-000000000006")
SECOND_USER_ID = UUID("70000000-0000-4000-8000-000000000007")
NEW_TABLES = (
    "personal_lab_billing_projections",
    "stripe_event_ledger",
    "personal_lab_widget_publications",
    "personal_lab_widget_publication_audit",
    "personal_lab_widget_monthly_quotas",
    "personal_lab_widget_quota_reservations",
)


def test_existing_personal_lab_registry_remains_service_owned_and_stable() -> None:
    # Given: the migration that owns the existing Personal Lab identity boundary.
    sql = PERSONAL_LABS_MIGRATION.read_text(encoding="utf-8")

    # When/Then: it remains one row per user and inaccessible to browser roles.
    assert "user_id uuid NOT NULL UNIQUE" in sql
    assert "ON TABLE public.personal_labs TO service_role" in sql
    assert "FORCE ROW LEVEL SECURITY" in sql
    assert "TO authenticated" not in sql


def test_migration_static_retention_security_and_quota_contract() -> None:
    # Given: the ordered persistence migration.
    sql = _normalized_migration()

    # When/Then: retained rows, forced RLS, and atomic quota semantics are explicit.
    assert MIGRATION.name > PERSONAL_LABS_MIGRATION.name
    assert sql.startswith("begin;") and sql.endswith("commit;")
    assert "create table public." not in sql
    for table in NEW_TABLES:
        assert re.search(rf"create table if not exists public\.{table}\s*\(", sql)
        assert f"alter table public.{table} enable row level security;" in sql
        assert re.search(rf"alter table public\.{table} force row level security;", sql)
    for fragment in (
        "personal_lab_id uuid primary key references public.personal_labs(id) on delete restrict",
        "personal_lab_id uuid not null unique references public.personal_labs(id) on delete restrict",
        "stripe_event_id text primary key",
        "allowed_origin !~ '[*?#[:space:]]'",
        "revoke all on function private.",
        "grant execute on function private.reserve_personal_lab_widget_message",
        "date_trunc('month', current_timestamp at time zone 'utc')::date",
        "security definer",
        "set search_path = pg_catalog, private",
        "prevent_mvp_audit_mutation",
        "pg_advisory_xact_lock",
        "and state = 'reserved'",
        ">= (p_stripe_created_at, p_stripe_event_id)",
        "exclu ded.last_stripe_event_id",
    ):
        assert fragment.replace(" ", "") in sql.replace(" ", "")
    assert "on delete cascade" not in sql
    assert "raw_payload" not in sql and "json" not in sql
    assert re.search(
        r"reserved_count = reserved_count \+ 1.*reserved_count \+ committed_count < 500",
        sql,
    )


@pytest.mark.integration
def test_disposable_postgres_enforces_501_simultaneous_reservation_cap() -> None:
    # Given: an explicitly supplied disposable Postgres database.
    database_url = os.environ.get("RAG_STUDIO_MVP_DISPOSABLE_DATABASE_URL")
    if database_url is None:
        pytest.skip(
            "live proof unavailable: set RAG_STUDIO_MVP_DISPOSABLE_DATABASE_URL"
        )
    anyio.run(_exercise_live_contract, database_url)


def _normalized_migration() -> str:
    assert MIGRATION.is_file(), "MVP persistence migration must exist"
    return re.sub(r"\s+", " ", MIGRATION.read_text(encoding="utf-8").lower()).strip()


async def _exercise_live_contract(database_url: str) -> None:
    connection = await asyncpg.connect(database_url, timeout=10)
    try:
        for path in (*FOUNDATION_MIGRATIONS, MIGRATION, MIGRATION):
            await connection.execute(path.read_text(encoding="utf-8"))
        await connection.execute(
            "INSERT INTO public.personal_labs (id, user_id) VALUES ($1, $2), ($3, $4)",
            LAB_ID,
            USER_ID,
            SECOND_LAB_ID,
            SECOND_USER_ID,
        )
        async with connection.transaction():
            await connection.execute("SET LOCAL ROLE service_role")
            publication = await connection.fetchval(
                "SELECT private.publish_personal_lab_widget($1, $2, $3)",
                LAB_ID,
                "https://widget.example.test",
                PUBLICATION_KEY,
            )
        assert publication is not None
        publication_id = UUID(str(publication))
        await _assert_browser_roles_denied(connection)
        await _assert_invalid_publications_are_atomic(connection)
        await _assert_event_replay_and_immutability(connection)
        await _assert_simultaneous_quota_cap(database_url, connection, publication_id)
        assert (
            await connection.fetchval("SELECT count(*) FROM public.personal_labs") == 2
        )
    finally:
        await connection.close(timeout=10)


async def _assert_browser_roles_denied(connection: asyncpg.Connection) -> None:
    for role_sql in ("SET LOCAL ROLE anon", "SET LOCAL ROLE authenticated"):
        for table in NEW_TABLES:
            with pytest.raises(asyncpg.InsufficientPrivilegeError):
                async with connection.transaction():
                    await connection.execute(role_sql)
                    await connection.fetch(f"SELECT * FROM public.{table}")
        for statement in (
            (
                "INSERT INTO public.stripe_event_ledger "
                "(stripe_event_id, personal_lab_id, event_type, stripe_created_at, outcome) "
                "VALUES ('evt_denied00000001', '30000000-0000-4000-8000-000000000003', "
                "'invoice.paid', now(), 'applied')"
            ),
            (
                "SELECT private.reserve_personal_lab_widget_message("
                "'50000000-0000-4000-8000-000000000005', "
                "'80000000-0000-4000-8000-000000000008')"
            ),
        ):
            with pytest.raises(asyncpg.InsufficientPrivilegeError):
                async with connection.transaction():
                    await connection.execute(role_sql)
                    await connection.execute(statement)


async def _assert_invalid_publications_are_atomic(
    connection: asyncpg.Connection,
) -> None:
    with pytest.raises(asyncpg.UniqueViolationError):
        async with connection.transaction():
            await connection.execute("SET LOCAL ROLE service_role")
            await connection.fetchval(
                "SELECT private.publish_personal_lab_widget($1, $2, $3)",
                LAB_ID,
                "https://widget.example.test",
                UUID("80000000-0000-4000-8000-000000000008"),
            )
    with pytest.raises(asyncpg.CheckViolationError):
        async with connection.transaction():
            await connection.execute("SET LOCAL ROLE service_role")
            await connection.fetchval(
                "SELECT private.publish_personal_lab_widget($1, $2, $3)",
                SECOND_LAB_ID,
                "https://widget.example.test/path",
                UUID("90000000-0000-4000-8000-000000000009"),
            )
    counts = await connection.fetchrow(
        "SELECT (SELECT count(*) FROM public.personal_lab_widget_publications), "
        "(SELECT count(*) FROM public.personal_lab_widget_publication_audit)"
    )
    assert counts is not None and tuple(counts) == (1, 1)


async def _assert_event_replay_and_immutability(
    connection: asyncpg.Connection,
) -> None:
    event_sql = (
        "SELECT private.apply_personal_lab_billing_event($1, "
        "'evt_contract00000001', 'customer.subscription.updated', "
        "'cus_contract000001', 'sub_contract000001', 'active', true, "
        "'2026-08-25T00:00:00Z'::timestamptz)"
    )
    async with connection.transaction():
        await connection.execute("SET LOCAL ROLE service_role")
        assert await connection.fetchval(event_sql, LAB_ID) is True
        assert await connection.fetchval(event_sql, LAB_ID) is False
    for statement in (
        "UPDATE public.stripe_event_ledger SET outcome='ignored'",
        "DELETE FROM public.stripe_event_ledger",
        "UPDATE public.personal_lab_widget_publication_audit SET key_version=2",
        "DELETE FROM public.personal_lab_widget_publication_audit",
        "DELETE FROM public.personal_lab_widget_publications",
    ):
        with pytest.raises(asyncpg.ObjectNotInPrerequisiteStateError):
            async with connection.transaction():
                await connection.execute(statement)


async def _assert_simultaneous_quota_cap(
    database_url: str,
    admin: asyncpg.Connection,
    publication_id: UUID,
) -> None:
    go = anyio.Event()
    ready = anyio.Event()
    lock = anyio.Lock()
    ready_count = 0
    outcomes: list[tuple[int, bool, bool]] = []

    async def attempt(index: int) -> None:
        nonlocal ready_count
        connection = await asyncpg.connect(database_url, timeout=20)
        try:
            await connection.execute("SET ROLE service_role")
            backend_pid = await connection.fetchval("SELECT pg_backend_pid()")
            async with lock:
                ready_count += 1
                if ready_count == 501:
                    ready.set()
            await go.wait()
            async with connection.transaction():
                reservation_id = UUID(int=index + 1)
                admitted = bool(
                    await connection.fetchval(
                        "SELECT private.reserve_personal_lab_widget_message($1, $2)",
                        publication_id,
                        reservation_id,
                    )
                )
                committed = admitted and bool(
                    await connection.fetchval(
                        "SELECT private.commit_personal_lab_widget_message($1)",
                        reservation_id,
                    )
                )
            outcomes.append((int(backend_pid), admitted, committed))
        finally:
            await connection.close(timeout=10)

    with anyio.fail_after(180):
        async with anyio.create_task_group() as tasks:
            for index in range(501):
                tasks.start_soon(attempt, index)
            await ready.wait()
            go.set()
    assert len(outcomes) == 501
    assert len({pid for pid, _, _ in outcomes}) == 501
    assert sum(admitted for _, admitted, _ in outcomes) == 500
    assert sum(committed for _, _, committed in outcomes) == 500
    quota = await admin.fetchrow(
        "SELECT reserved_count, committed_count "
        "FROM public.personal_lab_widget_monthly_quotas WHERE publication_id=$1",
        publication_id,
    )
    states = await admin.fetchrow(
        "SELECT count(*) FILTER (WHERE state='committed') AS committed, "
        "count(*) FILTER (WHERE state='released') AS released "
        "FROM public.personal_lab_widget_quota_reservations WHERE publication_id=$1",
        publication_id,
    )
    assert quota is not None and tuple(quota) == (0, 500)
    assert states is not None and tuple(states) == (500, 1)
