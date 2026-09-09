from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID

import anyio
import asyncpg
import pytest

from src.api.mvp_public_admission import ReservationOutcome
from src.api.mvp_public_admission_store import PostgresMvpPublicAdmissionStore

ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS = (
    ROOT / "docker/stage3/001-auth-schema.sql",
    ROOT / "supabase/migrations/20260816165319_stage3_tenant_schema.sql",
    ROOT / "supabase/migrations/20260816170226_stage3_tenant_routines_rls.sql",
    ROOT / "supabase/migrations/20260816170824_stage3_tenant_rls_grants.sql",
    ROOT / "supabase/migrations/20260817090000_stage3_chatbot_lifecycle.sql",
    ROOT / "supabase/migrations/20260820090000_group1_accounts_sessions.sql",
    ROOT / "supabase/migrations/20260821090000_group2_personal_labs.sql",
    ROOT / "supabase/migrations/20260825120000_mvp_personal_lab_billing_widget.sql",
)
LAB = UUID("71000000-0000-4000-8000-000000000001")
USER = UUID("71000000-0000-4000-8000-000000000002")
PUBLICATION = UUID("71000000-0000-4000-8000-000000000003")
PUBLIC_KEY = UUID("71000000-0000-4000-8000-000000000004")


@pytest.mark.integration
def test_public_store_enforces_concurrent_quota_replay_and_stale_authority() -> None:
    database_url = os.environ.get("RAG_STUDIO_MVP_DISPOSABLE_DATABASE_URL")
    if database_url is None:
        pytest.skip("set RAG_STUDIO_MVP_DISPOSABLE_DATABASE_URL for live proof")
    anyio.run(_exercise_store, database_url)


async def _exercise_store(database_url: str) -> None:
    control = await asyncpg.connect(database_url, timeout=10, command_timeout=30)
    try:
        await control.execute("DROP DATABASE IF EXISTS task7_admission WITH (FORCE)")
        await control.execute("CREATE DATABASE task7_admission")
        parts = urlsplit(database_url)
        isolated_url = urlunsplit(parts._replace(path="/task7_admission"))
        await _exercise_isolated_store(isolated_url)
    finally:
        await control.execute("DROP DATABASE IF EXISTS task7_admission WITH (FORCE)")
        assert not await control.fetchval(
            "SELECT EXISTS(SELECT 1 FROM pg_database WHERE datname='task7_admission')"
        )
        await control.close(timeout=10)


async def _exercise_isolated_store(database_url: str) -> None:
    admin = await asyncpg.connect(database_url, timeout=10, command_timeout=30)
    try:
        for migration in MIGRATIONS:
            await admin.execute(migration.read_text(encoding="utf-8"))
        await _seed(admin)
        store = PostgresMvpPublicAdmissionStore(database_url)
        snapshot = await store.resolve(PUBLIC_KEY)
        assert snapshot is not None
        assert snapshot.publication_id == PUBLICATION and snapshot.entitled

        reservations = tuple(UUID(int=10_000 + index) for index in range(501))
        outcomes = await _reserve_concurrently(store, reservations)
        accepted = [
            reservation
            for reservation, outcome in zip(reservations, outcomes, strict=True)
            if outcome is ReservationOutcome.ACCEPTED
        ]
        assert outcomes.count(ReservationOutcome.ACCEPTED) == 500
        assert outcomes.count(ReservationOutcome.SATURATED) == 1

        released = accepted.pop()
        assert await store.release(released)
        replacement = UUID(int=20_000)
        replay_race = await _reserve_concurrently(store, (replacement, replacement))
        assert sorted(item.value for item in replay_race) == ["accepted", "replayed"]

        await _commit_concurrently(store, (*accepted, replacement))
        counters = await admin.fetchrow(
            "SELECT reserved_count,committed_count "
            "FROM public.personal_lab_widget_monthly_quotas "
            "WHERE publication_id=$1",
            PUBLICATION,
        )
        assert counters is not None and tuple(counters) == (0, 500)

        restarted = PostgresMvpPublicAdmissionStore(database_url)
        assert (
            await restarted.reserve_once(PUBLICATION, replacement)
            is ReservationOutcome.REPLAYED
        )
        await admin.execute(
            "UPDATE public.personal_lab_billing_projections "
            "SET entitled=false,subscription_status='canceled' "
            "WHERE personal_lab_id=$1",
            LAB,
        )
        stale = UUID(int=30_000)
        assert (
            await restarted.reserve_once(PUBLICATION, stale)
            is ReservationOutcome.STALE_AUTHORITY
        )
        assert not await admin.fetchval(
            "SELECT EXISTS(SELECT 1 "
            "FROM public.personal_lab_widget_quota_reservations "
            "WHERE reservation_id=$1)",
            stale,
        )
    finally:
        await admin.close(timeout=10)


async def _seed(connection: asyncpg.Connection) -> None:
    await connection.execute(
        "INSERT INTO public.personal_labs (id,user_id) VALUES ($1,$2)", LAB, USER
    )
    await connection.execute(
        "INSERT INTO public.personal_lab_widget_publications "
        "(id,personal_lab_id,public_key,allowed_origin,state) "
        "VALUES ($1,$2,$3,'https://widget.example.test','enabled')",
        PUBLICATION,
        LAB,
        PUBLIC_KEY,
    )
    await connection.execute(
        "INSERT INTO public.personal_lab_billing_projections "
        "(personal_lab_id,stripe_customer_id,stripe_subscription_id,"
        "subscription_status,entitled) "
        "VALUES ($1,'cus_task7fixture','sub_task7fixture','active',true)",
        LAB,
    )


async def _reserve_concurrently(
    store: PostgresMvpPublicAdmissionStore, reservations: tuple[UUID, ...]
) -> list[ReservationOutcome]:
    outcomes: list[ReservationOutcome] = []

    async def reserve(reservation_id: UUID) -> None:
        outcomes.append(await store.reserve_once(PUBLICATION, reservation_id))

    with anyio.fail_after(30):
        async with anyio.create_task_group() as tasks:
            for reservation_id in reservations:
                tasks.start_soon(reserve, reservation_id)
    return outcomes


async def _commit_concurrently(
    store: PostgresMvpPublicAdmissionStore, reservations: tuple[UUID, ...]
) -> None:
    results: list[bool] = []

    async def commit(reservation_id: UUID) -> None:
        results.append(await store.commit(reservation_id))

    with anyio.fail_after(30):
        async with anyio.create_task_group() as tasks:
            for reservation_id in reservations:
                tasks.start_soon(commit, reservation_id)
    assert len(results) == 500 and all(results)
