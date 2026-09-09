from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import Response
from stripe import StripeClient

from src.api.mvp_stripe_gateway import CheckoutCommand, StripeBillingGateway
from src.api.personal_lab_composition import mount_personal_lab_routes
from src.api.saas_runtime import RuntimeConfiguration, RuntimeMode
from tests.api.mvp_billing_route_fakes import (
    LAB,
    canonical,
    csrf,
    event,
    fixture,
    signed,
)


def test_authenticated_checkout_and_portal_use_server_authority(
    tmp_path: Path,
) -> None:
    # Given: one authenticated Personal Lab with a verified billing customer.
    client, gateway, store = fixture(tmp_path)
    store.customers[LAB] = "cus_routefixture01"
    with client:
        client.cookies.set("identity", "authenticated")
        headers = csrf(client)

        # When: Checkout is replayed and Portal is launched.
        checkout = client.post("/api/personal/billing/checkout", headers=headers)
        replay = client.post("/api/personal/billing/checkout", headers=headers)
        portal = client.post("/api/personal/billing/portal", headers=headers)

    # Then: only server configuration and fresh UUID idempotency keys are used.
    assert (
        checkout.json()
        == replay.json()
        == {"url": "https://checkout.stripe.test/session"}
    )
    assert portal.json() == {"url": "https://billing.stripe.test/portal"}
    assert {command.price_id for command in gateway.checkouts} == {
        "price_routefixture0001"
    }
    assert all(command.idempotency_key.version == 4 for command in gateway.checkouts)
    assert gateway.checkouts[0].idempotency_key != gateway.checkouts[1].idempotency_key
    assert (
        gateway.portals[0].customer_id,
        gateway.portals[0].configuration_id,
    ) == ("cus_routefixture01", "bpc_routefixture0001")
    assert store.events == {}


@pytest.mark.anyio
async def test_stripe_adapter_omits_payment_method_override() -> None:
    # Given: the isolated instance client and one server-owned Checkout command.
    client = StripeClient("rk_test_" + "x" * 24)
    gateway = StripeBillingGateway(client)
    command = CheckoutCommand(
        LAB,
        "price_routefixture0001",
        "https://testserver/success",
        "https://testserver/cancel",
        uuid4(),
    )
    with patch.object(
        client.v1.checkout.sessions,
        "create",
        return_value={"url": "https://checkout.stripe.test/session"},
    ) as create:
        # When: the adapter creates the hosted session without external I/O.
        result = await gateway.create_checkout(command)

    # Then: Stripe receives the allowlisted Price and UUID key, with defaults intact.
    params, options = create.call_args.args
    assert result == "https://checkout.stripe.test/session"
    assert params["line_items"] == [{"price": command.price_id, "quantity": 1}]
    assert "payment_method_types" not in params
    assert options == {"idempotency_key": str(command.idempotency_key)}


def test_disabled_configuration_mounts_no_billing_routes(tmp_path: Path) -> None:
    # Given: SaaS composition with the explicit billing rollback state.
    app = FastAPI()
    app.state.runtime_configuration = RuntimeConfiguration(
        mode=RuntimeMode.SAAS, billing=None
    )
    authority = SimpleNamespace(
        auth_context=fixture(tmp_path)[1], database_url="unused"
    )
    mount_personal_lab_routes(app, authority.auth_context, authority.database_url)

    # When: billing paths are requested after composition.
    with TestClient(app) as client:
        checkout = client.post("/api/personal/billing/checkout")
        webhook = client.post("/api/billing/stripe/webhook")

    # Then: no user or webhook billing authority exists.
    assert checkout.status_code == webhook.status_code == 404


def test_auth_csrf_wrong_owner_and_timeout_fail_sanitized(tmp_path: Path) -> None:
    # Given: billing routes with no browser authority and a bounded provider failure.
    client, gateway, store = fixture(tmp_path)
    with client:
        missing_csrf = client.post("/api/personal/billing/checkout")
        headers = csrf(client)
        missing_auth = client.post("/api/personal/billing/checkout", headers=headers)
        client.cookies.set("identity", "authenticated")
        wrong_owner = client.post("/api/personal/billing/portal", headers=headers)
        gateway.fail_checkout = True
        timeout = client.post("/api/personal/billing/checkout", headers=headers)

    # Then: requests are bounded before state mutation and private errors are absent.
    assert missing_csrf.status_code == 403 and missing_auth.status_code == 401
    assert wrong_owner.status_code == 409 and timeout.status_code == 502
    assert timeout.json() == {"detail": "Billing provider is unavailable."}
    assert not gateway.checkouts and not gateway.portals and not store.events


def test_signed_raw_webhook_applies_once_and_rejects_modified_bytes(
    tmp_path: Path,
) -> None:
    # Given: a signed Checkout event tied to an existing server-owned lab.
    client, gateway, store = fixture(tmp_path)
    gateway.subscriptions["sub_routefixture01"] = canonical()
    payload = event(
        "evt_routefixture01",
        "checkout.session.completed",
        {
            "subscription": "sub_routefixture01",
            "metadata": {"personal_lab_id": str(LAB)},
        },
    )
    signature = signed(payload)
    with client:
        applied = client.post(
            "/api/billing/stripe/webhook",
            content=payload,
            headers={"Stripe-Signature": signature},
        )
        duplicate = client.post(
            "/api/billing/stripe/webhook",
            content=payload,
            headers={"Stripe-Signature": signature},
        )
        modified = client.post(
            "/api/billing/stripe/webhook",
            content=payload + b" ",
            headers={"Stripe-Signature": signature},
        )
        missing = client.post("/api/billing/stripe/webhook", content=payload)
        expired = client.post(
            "/api/billing/stripe/webhook",
            content=payload,
            headers={"Stripe-Signature": signed(payload, timestamp=1)},
        )
        future_timestamp = int(time.time()) + 86_400
        future = client.post(
            "/api/billing/stripe/webhook",
            content=payload,
            headers={"Stripe-Signature": signed(payload, timestamp=future_timestamp)},
        )
        malformed = event("evt_malformed00001", "customer.subscription.updated", {})
        malformed_response = client.post(
            "/api/billing/stripe/webhook",
            content=malformed,
            headers={"Stripe-Signature": signed(malformed)},
        )
        invalid_created = event(
            "evt_badcreated0001",
            "customer.created",
            {},
            created=999_999_999_999_999,
        )
        invalid_created_response = client.post(
            "/api/billing/stripe/webhook",
            content=invalid_created,
            headers={"Stripe-Signature": signed(invalid_created)},
        )

    # Then: signature precedes parsing and the transaction is idempotent.
    assert applied.json() == {"outcome": "applied"}
    assert duplicate.json() == {"outcome": "duplicate"}
    assert modified.status_code == missing.status_code == expired.status_code == 400
    assert (
        future.status_code
        == malformed_response.status_code
        == invalid_created_response.status_code
        == 400
    )
    assert modified.json() == {"detail": "Invalid webhook."}
    assert len(store.events) == 1


def test_unknown_customer_event_type_stale_and_partial_error_are_bounded(
    tmp_path: Path,
) -> None:
    # Given: verified unsupported, unknown-customer, reordered, and failing events.
    client, gateway, store = fixture(tmp_path)
    subscription = canonical()
    gateway.subscriptions[subscription.subscription_id] = subscription
    store.labs[subscription.customer_id] = LAB
    now = int(time.time())

    def post(payload: bytes) -> Response:
        return client.post(
            "/api/billing/stripe/webhook",
            content=payload,
            headers={"Stripe-Signature": signed(payload)},
        )

    with client:
        unknown_type = post(event("evt_unknown00001", "customer.created", {}))
        gateway.subscriptions[subscription.subscription_id] = canonical(
            "cus_unknown000001"
        )
        unknown_customer = post(
            event(
                "evt_unknown00002",
                "customer.subscription.updated",
                {"id": subscription.subscription_id},
            )
        )
        gateway.subscriptions[subscription.subscription_id] = subscription
        newer = post(
            event(
                "evt_newer00000001",
                "customer.subscription.updated",
                {"id": subscription.subscription_id},
                created=now,
            )
        )
        stale = post(
            event(
                "evt_older00000001",
                "invoice.paid",
                {
                    "parent": {
                        "subscription_details": {
                            "subscription": subscription.subscription_id
                        }
                    }
                },
                created=now - 1,
            )
        )
        store.fail_apply = True
        partial = post(
            event(
                "evt_failure000001",
                "customer.subscription.updated",
                {"id": subscription.subscription_id},
                created=now + 1,
            )
        )

    # Then: unsupported ownership never mutates and persistence failure is sanitized.
    assert unknown_type.json() == unknown_customer.json() == {"outcome": "ignore"}
    assert newer.json() == {"outcome": "applied"}
    assert stale.json() == {"outcome": "stale"}
    assert partial.status_code == 503
    assert partial.json() == {"detail": "Billing state is unavailable."}
    assert "evt_failure000001" not in store.events
    assert len(store.events) == 2
