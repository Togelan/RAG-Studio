from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import anyio
import asyncpg
import pytest

from src.api.mvp_billing_store import (
    BillingStoreUnavailableError,
    LedgerOutcome,
    PostgresMvpBillingStore,
)
from src.api.mvp_entitlements import (
    EntitlementMutation,
    SubscriptionStatus,
    VerifiedBillingEvent,
)

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
RACE_LAB_ID = UUID("a1000000-0000-4000-8000-000000000001")
RACE_USER_ID = UUID("a1000000-0000-4000-8000-000000000002")
FAULT_LAB_ID = UUID("a2000000-0000-4000-8000-000000000001")
FAULT_USER_ID = UUID("a2000000-0000-4000-8000-000000000002")


@dataclass(frozen=True, slots=True)
class _RaceCase:
    event: VerifiedBillingEvent
    mutation: EntitlementMutation


@pytest.mark.integration
def test_postgres_store_serializes_event_race_and_rolls_back_fault() -> None:
    # Given: a fresh disposable PostgreSQL authority for the production store.
    database_url = os.environ.get("RAG_STUDIO_MVP_DISPOSABLE_DATABASE_URL")
    if database_url is None:
        pytest.skip("set RAG_STUDIO_MVP_DISPOSABLE_DATABASE_URL for live proof")

    # When/Then: real concurrent transactions converge and a fault leaves no partial row.
    anyio.run(_exercise_concurrent_store, database_url)


async def _exercise_concurrent_store(database_url: str) -> None:
    admin = await asyncpg.connect(database_url, timeout=10)
    try:
        for migration in MIGRATIONS:
            await admin.execute(migration.read_text(encoding="utf-8"))
        await admin.execute(
            "INSERT INTO public.personal_labs (id,user_id) VALUES ($1,$2),($3,$4)",
            RACE_LAB_ID,
            RACE_USER_ID,
            FAULT_LAB_ID,
            FAULT_USER_ID,
        )
        active = _case(
            "evt_racenewer0001", "racefixture001", 2, SubscriptionStatus.ACTIVE, True
        )
        stale = _case(
            "evt_raceolder0001",
            "racefixture001",
            1,
            SubscriptionStatus.PAST_DUE,
            False,
        )
        race_results = await _run_ordered_race(
            database_url, admin, RACE_LAB_ID, active, stale
        )
        assert race_results == {
            active.event.event_id: LedgerOutcome.APPLIED,
            stale.event.event_id: LedgerOutcome.STALE,
        }
        projection = await admin.fetchrow(
            "SELECT subscription_status,entitled,last_stripe_event_id "
            "FROM public.personal_lab_billing_projections WHERE personal_lab_id=$1",
            RACE_LAB_ID,
        )
        assert projection is not None
        assert tuple(projection) == ("active", True, active.event.event_id)

        fault = _case(
            "evt_racefault0001",
            "faultfixture01",
            4,
            SubscriptionStatus.PAST_DUE,
            True,
        )
        valid = _case(
            "evt_racevalid0001",
            "faultfixture01",
            3,
            SubscriptionStatus.ACTIVE,
            True,
        )
        fault_results = await _run_ordered_race(
            database_url, admin, FAULT_LAB_ID, fault, valid
        )
        assert fault_results == {
            fault.event.event_id: "unavailable",
            valid.event.event_id: LedgerOutcome.APPLIED,
        }
        fault_projection = await admin.fetchrow(
            "SELECT subscription_status,entitled,last_stripe_event_id "
            "FROM public.personal_lab_billing_projections WHERE personal_lab_id=$1",
            FAULT_LAB_ID,
        )
        fault_rows = await admin.fetchval(
            "SELECT count(*) FROM public.stripe_event_ledger WHERE stripe_event_id=$1",
            fault.event.event_id,
        )
        assert fault_projection is not None
        assert tuple(fault_projection) == ("active", True, valid.event.event_id)
        assert fault_rows == 0
    finally:
        await admin.close(timeout=10)


def _case(
    event_id: str,
    stripe_suffix: str,
    second: int,
    status: SubscriptionStatus,
    entitled: bool,
) -> _RaceCase:
    return _RaceCase(
        VerifiedBillingEvent(
            event_id,
            "customer.subscription.updated",
            datetime(2026, 8, 25, 12, 0, second, tzinfo=UTC),
        ),
        EntitlementMutation(
            f"cus_{stripe_suffix}",
            f"sub_{stripe_suffix}",
            status,
            entitled,
            None,
        ),
    )


async def _run_ordered_race(
    database_url: str,
    admin: asyncpg.Connection,
    lab_id: UUID,
    first: _RaceCase,
    second: _RaceCase,
) -> dict[str, LedgerOutcome | str]:
    blocker = await asyncpg.connect(database_url, timeout=10)
    transaction = blocker.transaction()
    await transaction.start()
    committed = False
    await blocker.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended($1,0))", str(lab_id)
    )
    results: dict[str, LedgerOutcome | str] = {}

    async def apply(case: _RaceCase) -> None:
        try:
            results[case.event.event_id] = await PostgresMvpBillingStore(
                database_url
            ).apply_event(lab_id, case.event, case.mutation)
        except BillingStoreUnavailableError:
            results[case.event.event_id] = "unavailable"

    try:
        with anyio.fail_after(10):
            async with anyio.create_task_group() as tasks:
                tasks.start_soon(apply, first)
                await _wait_for_advisory_waiters(admin, 1)
                tasks.start_soon(apply, second)
                await _wait_for_advisory_waiters(admin, 2)
                await transaction.commit()
                committed = True
    finally:
        if not committed:
            await transaction.rollback()
        await blocker.close(timeout=10)
    return results


async def _wait_for_advisory_waiters(
    connection: asyncpg.Connection, expected: int
) -> None:
    with anyio.fail_after(3):
        while True:
            waiting = await connection.fetchval(
                "SELECT count(*) FROM pg_locks "
                "WHERE locktype='advisory' AND granted=false"
            )
            if int(waiting) >= expected:
                return
            await anyio.sleep(0.01)
