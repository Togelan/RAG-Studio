from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import UUID

import anyio
import asyncpg
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from src.api.billing_runtime import BillingConfiguration
from src.api.mvp_billing_store import PostgresMvpBillingStore
from src.api.mvp_stripe_gateway import StripeWebhookSignatureVerifier
from src.api.personal_lab_registry import PersonalLabRouteDependencies
from src.api.personal_lab_scope import PersonalLabScopeResolver
from src.api.routes.mvp_billing import create_mvp_billing_router
from tests.api.mvp_billing_route_fakes import (
    LAB,
    SECRET,
    CookieAuth,
    Gateway,
    Scopes,
    canonical,
    event,
    signed,
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
USER = UUID("10000000-0000-4000-8000-000000000001")


@pytest.mark.integration
def test_production_route_store_deduplicates_ten_webhooks(tmp_path: Path) -> None:
    # Given: a migrated disposable PostgreSQL database and production route/store.
    database_url = os.environ.get("RAG_STUDIO_MVP_DISPOSABLE_DATABASE_URL")
    if database_url is None:
        pytest.skip("set RAG_STUDIO_MVP_DISPOSABLE_DATABASE_URL for live proof")
    anyio.run(_prepare_database, database_url)
    gateway = Gateway()
    gateway.subscriptions["sub_routefixture01"] = canonical()
    client = _client(tmp_path, database_url, gateway)
    payload = event(
        "evt_liveconcurrent01",
        "checkout.session.completed",
        {
            "subscription": "sub_routefixture01",
            "metadata": {"personal_lab_id": str(LAB)},
        },
    )
    headers = {"Stripe-Signature": signed(payload)}

    # When: ten concurrent HTTP deliveries traverse verification and reduction.
    with client, ThreadPoolExecutor(max_workers=10) as workers:
        responses = tuple(
            workers.map(
                lambda _: client.post(
                    "/api/billing/stripe/webhook", content=payload, headers=headers
                ),
                range(10),
            )
        )
    state = anyio.run(_read_state, database_url)

    # Then: one event and one projection commit with no partial or extra state.
    outcomes = tuple(response.json()["outcome"] for response in responses)
    assert outcomes.count("applied") == 1
    assert outcomes.count("duplicate") == 9
    assert state == (1, 1, "active", True, "evt_liveconcurrent01", "applied")


def _client(tmp_path: Path, database_url: str, gateway: Gateway) -> TestClient:
    configuration = BillingConfiguration(
        api_key=SecretStr("rk_test_" + "x" * 24),
        webhook_secret=SecretStr(SECRET),
        price_id="price_routefixture0001",
        public_app_url="https://testserver/app",
        portal_configuration_id="bpc_routefixture0001",
        test_object_pairs="price_routefixture0001|bpc_routefixture0001",
    )
    dependencies = PersonalLabRouteDependencies(
        CookieAuth(), PersonalLabScopeResolver(Scopes(), tmp_path)
    )
    app = FastAPI()
    app.include_router(
        create_mvp_billing_router(
            dependencies,
            configuration,
            gateway,
            StripeWebhookSignatureVerifier(SECRET),
            PostgresMvpBillingStore(database_url),
        )
    )
    return TestClient(app, base_url="https://testserver")


async def _prepare_database(database_url: str) -> None:
    connection = await asyncpg.connect(database_url, timeout=10)
    try:
        for migration in MIGRATIONS:
            await connection.execute(migration.read_text(encoding="utf-8"))
        await connection.execute(
            "INSERT INTO public.personal_labs (id,user_id) VALUES ($1,$2)", LAB, USER
        )
    finally:
        await connection.close(timeout=10)


async def _read_state(database_url: str) -> tuple[int, int, str, bool, str, str]:
    connection = await asyncpg.connect(database_url, timeout=10)
    try:
        ledger_count = int(
            await connection.fetchval("SELECT count(*) FROM public.stripe_event_ledger")
        )
        projection = await connection.fetchrow(
            "SELECT subscription_status,entitled,last_stripe_event_id "
            "FROM public.personal_lab_billing_projections"
        )
        projection_count = int(
            await connection.fetchval(
                "SELECT count(*) FROM public.personal_lab_billing_projections"
            )
        )
        ledger_outcome = str(
            await connection.fetchval("SELECT outcome FROM public.stripe_event_ledger")
        )
        assert projection is not None
        return (
            ledger_count,
            projection_count,
            str(projection["subscription_status"]),
            bool(projection["entitled"]),
            str(projection["last_stripe_event_id"]),
            ledger_outcome,
        )
    finally:
        await connection.close(timeout=10)
