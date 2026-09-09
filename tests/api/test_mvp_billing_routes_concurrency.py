from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from tests.api.mvp_billing_route_fakes import LAB, canonical, event, fixture, signed


def test_ten_concurrent_duplicate_deliveries_apply_once(tmp_path: Path) -> None:
    # Given: the stated ten-request load threshold delivers one signed event.
    client, gateway, store = fixture(tmp_path)
    gateway.subscriptions["sub_routefixture01"] = canonical()
    payload = event(
        "evt_concurrent0001",
        "checkout.session.completed",
        {
            "subscription": "sub_routefixture01",
            "metadata": {"personal_lab_id": str(LAB)},
        },
    )
    headers = {"Stripe-Signature": signed(payload)}

    # When: ten workers submit the same verified delivery concurrently.
    with client, ThreadPoolExecutor(max_workers=10) as workers:
        responses = tuple(
            workers.map(
                lambda _: client.post(
                    "/api/billing/stripe/webhook", content=payload, headers=headers
                ),
                range(10),
            )
        )

    # Then: one transaction applies and nine replays observe duplicate state.
    outcomes = tuple(response.json()["outcome"] for response in responses)
    assert outcomes.count("applied") == 1 and outcomes.count("duplicate") == 9
    assert len(store.events) == 1
