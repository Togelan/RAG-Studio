from __future__ import annotations

from pathlib import Path

from src.api.mvp_entitlements import BillingProjection, SubscriptionStatus
from tests.api.mvp_billing_route_fakes import LAB, canonical, event, fixture, signed


def test_billing_projection_requires_authentication_and_uses_safe_defaults(
    tmp_path: Path,
) -> None:
    # Given: a billing router with no verified entitlement projection.
    client, _, _ = fixture(tmp_path)

    # When: a browser reads billing before and after establishing its session.
    with client:
        anonymous = client.get("/api/personal/billing")
        client.cookies.set("identity", "authenticated")
        projection = client.get("/api/personal/billing")

    # Then: authentication is enforced and the initial response is display-safe.
    assert anonymous.status_code == 401
    assert projection.status_code == 200
    assert projection.json() == {
        "plan": {
            "amount_usd_cents": 1_000,
            "currency": "USD",
            "interval": "month",
        },
        "status": "none",
        "pending": False,
        "entitled": False,
        "can_manage": False,
    }


def test_billing_projection_tracks_verified_entitlement_without_provider_ids(
    tmp_path: Path,
) -> None:
    # Given: one authenticated owner and a verified active subscription event.
    client, gateway, _ = fixture(tmp_path)
    subscription = canonical()
    gateway.subscriptions[subscription.subscription_id] = subscription
    payload = event(
        "evt_projection0001",
        "checkout.session.completed",
        {
            "subscription": subscription.subscription_id,
            "metadata": {"personal_lab_id": str(LAB)},
        },
    )

    # When: the webhook projection is persisted before the owner reads billing.
    with client:
        applied = client.post(
            "/api/billing/stripe/webhook",
            content=payload,
            headers={"Stripe-Signature": signed(payload)},
        )
        client.cookies.set("identity", "authenticated")
        projection = client.get("/api/personal/billing")

    # Then: browser state reflects the verified projection and no provider ID leaks.
    assert applied.status_code == 200
    assert projection.status_code == 200
    assert projection.json()["status"] == SubscriptionStatus.ACTIVE.value
    assert projection.json()["entitled"] is True
    assert projection.json()["pending"] is False
    assert projection.json()["can_manage"] is True
    assert set(projection.json()) == {
        "plan",
        "status",
        "pending",
        "entitled",
        "can_manage",
    }


def test_billing_projection_marks_only_incomplete_entitlement_as_pending(
    tmp_path: Path,
) -> None:
    # Given: a durable incomplete entitlement projection for the authenticated lab.
    client, _, store = fixture(tmp_path)
    store.projection_override = BillingProjection(
        status=SubscriptionStatus.INCOMPLETE,
        entitled=False,
        can_manage=True,
    )

    # When: the owner reads the billing projection.
    with client:
        client.cookies.set("identity", "authenticated")
        projection = client.get("/api/personal/billing")

    # Then: the UI can distinguish pending payment completion from entitlement.
    assert projection.status_code == 200
    assert projection.json() | {"plan": None} == {
        "plan": None,
        "status": "incomplete",
        "pending": True,
        "entitled": False,
        "can_manage": True,
    }


def test_billing_projection_sanitizes_unavailable_and_malformed_store_data(
    tmp_path: Path,
) -> None:
    # Given: an authenticated browser and a durable billing read failure.
    client, _, store = fixture(tmp_path)

    # When: the projection is unavailable or violates its typed storage contract.
    with client:
        client.cookies.set("identity", "authenticated")
        store.projection_failure = True
        unavailable = client.get("/api/personal/billing")
        store.projection_failure = False
        store.malformed_projection = True
        malformed = client.get("/api/personal/billing")

    # Then: both failures disclose only the stable billing-unavailable response.
    assert unavailable.status_code == malformed.status_code == 503
    assert (
        unavailable.json()
        == malformed.json()
        == {"detail": "Billing state is unavailable."}
    )
