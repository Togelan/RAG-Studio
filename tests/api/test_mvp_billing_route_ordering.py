from __future__ import annotations

import time
from datetime import UTC, datetime
from pathlib import Path

from httpx import Response

from src.api.mvp_entitlements import SubscriptionStatus
from tests.api.mvp_billing_route_fakes import (
    LAB,
    canonical,
    event,
    fixture,
    signed,
)


def test_duplicate_invoice_then_older_deletion_keeps_canonical_entitlement(
    tmp_path: Path,
) -> None:
    # Given: Stripe's canonical subscription is active for the Personal Lab.
    client, gateway, store = fixture(tmp_path)
    subscription = canonical()
    gateway.subscriptions[subscription.subscription_id] = subscription
    store.labs[subscription.customer_id] = LAB
    paid_at = int(time.time())
    invoice = event(
        "evt_paidordering01",
        "invoice.paid",
        {
            "parent": {
                "subscription_details": {"subscription": subscription.subscription_id}
            }
        },
        created=paid_at,
    )
    older_deletion = event(
        "evt_deletedold001",
        "customer.subscription.deleted",
        {"id": subscription.subscription_id},
        created=paid_at - 1,
    )

    def post(payload: bytes) -> Response:
        return client.post(
            "/api/billing/stripe/webhook",
            content=payload,
            headers={"Stripe-Signature": signed(payload)},
        )

    # When: invoice delivery is repeated before an older deletion arrives.
    with client:
        applied = post(invoice)
        duplicate = post(invoice)
        stale = post(older_deletion)
        client.cookies.set("identity", "authenticated")
        projection = client.get("/api/personal/billing")

    # Then: the ledger is idempotent/ordered and the canonical state stays active.
    assert applied.json() == {"outcome": "applied"}
    assert duplicate.json() == {"outcome": "duplicate"}
    assert stale.json() == {"outcome": "stale"}
    assert set(store.events) == {"evt_paidordering01", "evt_deletedold001"}
    assert store.latest[LAB] == (
        datetime.fromtimestamp(paid_at, tz=UTC),
        "evt_paidordering01",
    )
    assert projection.status_code == 200
    assert projection.json()["status"] == SubscriptionStatus.ACTIVE.value
    assert projection.json()["entitled"] is True
    assert projection.json()["can_manage"] is True
