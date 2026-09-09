from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from pydantic import JsonValue, SecretStr

from src.api.billing_runtime import BillingConfiguration
from src.api.mvp_billing_store import BillingStoreUnavailableError, LedgerOutcome
from src.api.mvp_entitlements import (
    BillingProjection,
    CanonicalSubscription,
    EntitlementMutation,
    SubscriptionStatus,
    VerifiedBillingEvent,
)
from src.api.mvp_stripe_gateway import (
    CheckoutCommand,
    PortalCommand,
    StripeGatewayUnavailableError,
    StripeWebhookSignatureVerifier,
)
from src.api.personal_lab_registry import PersonalLabRouteDependencies
from src.api.personal_lab_scope import PersonalLabScopeResolver
from src.api.routes.mvp_billing import create_mvp_billing_router
from src.api.routes.mvp_billing_projection import create_mvp_billing_projection_router
from src.api.saas_security import SaasCsrfMiddleware

USER = UUID("10000000-0000-4000-8000-000000000001")
LAB = UUID("20000000-0000-4000-8000-000000000002")
SECRET = "whsec_" + "routefixturevalue000001"


@dataclass(frozen=True, slots=True)
class Claims:
    user_id: UUID


@dataclass(frozen=True, slots=True)
class AuthResult:
    claims: Claims


class CookieAuth:
    async def resolve(self, request: Request, *, require_workspace: bool) -> AuthResult:
        del require_workspace
        if request.cookies.get("identity") != "authenticated":
            raise HTTPException(401, detail="Authentication required.")
        return AuthResult(Claims(USER))


class Scopes:
    async def resolve(self, user_id: UUID) -> UUID:
        assert user_id == USER
        return LAB


class Gateway:
    def __init__(self) -> None:
        self.checkouts: list[CheckoutCommand] = []
        self.portals: list[PortalCommand] = []
        self.subscriptions: dict[str, CanonicalSubscription] = {}
        self.fail_checkout = False

    async def create_checkout(self, command: CheckoutCommand) -> str:
        if self.fail_checkout:
            raise StripeGatewayUnavailableError
        self.checkouts.append(command)
        return "https://checkout.stripe.test/session"

    async def create_portal(self, command: PortalCommand) -> str:
        self.portals.append(command)
        return "https://billing.stripe.test/portal"

    async def retrieve_subscription(
        self, subscription_id: str
    ) -> CanonicalSubscription | None:
        return self.subscriptions.get(subscription_id)


class Store:
    def __init__(self) -> None:
        self.customers: dict[UUID, str] = {}
        self.labs: dict[str, UUID] = {}
        self.events: dict[str, tuple[datetime, EntitlementMutation]] = {}
        self.latest: dict[UUID, tuple[datetime, str]] = {}
        self.fail_apply = False
        self.projection_failure = False
        self.malformed_projection = False
        self.projection_override: BillingProjection | None = None

    async def projection_for_lab(
        self, personal_lab_id: UUID
    ) -> BillingProjection | None:
        if self.projection_failure:
            raise BillingStoreUnavailableError
        if self.malformed_projection:
            return BillingProjection("malformed", False, False)
        if self.projection_override is not None:
            return self.projection_override
        latest = self.latest.get(personal_lab_id)
        if latest is None:
            return None
        mutation = self.events[latest[1]][1]
        return BillingProjection(
            status=mutation.status,
            entitled=mutation.entitled,
            can_manage=mutation.customer_id == self.customers.get(personal_lab_id),
        )

    async def customer_for_lab(self, personal_lab_id: UUID) -> str | None:
        return self.customers.get(personal_lab_id)

    async def personal_lab_for_customer(
        self, customer_id: str, claimed_lab_id: UUID | None = None
    ) -> UUID | None:
        if claimed_lab_id is not None:
            existing = self.labs.get(customer_id)
            return claimed_lab_id if existing in {None, claimed_lab_id} else None
        return self.labs.get(customer_id)

    async def apply_event(
        self,
        personal_lab_id: UUID,
        event: VerifiedBillingEvent,
        mutation: EntitlementMutation,
    ) -> LedgerOutcome:
        if self.fail_apply:
            raise BillingStoreUnavailableError
        if event.event_id in self.events:
            return LedgerOutcome.DUPLICATE
        self.events[event.event_id] = (event.created_at, mutation)
        current = self.latest.get(personal_lab_id)
        order = (event.created_at, event.event_id)
        if current is not None and order <= current:
            return LedgerOutcome.STALE
        self.latest[personal_lab_id] = order
        self.customers[personal_lab_id] = mutation.customer_id
        self.labs[mutation.customer_id] = personal_lab_id
        return LedgerOutcome.APPLIED


def fixture(tmp_path: Path) -> tuple[TestClient, Gateway, Store]:
    gateway, store = Gateway(), Store()
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
    app.add_middleware(
        SaasCsrfMiddleware,
        trusted_origins=("https://testserver",),
        protected_roots=("/api/personal",),
    )
    app.include_router(
        create_mvp_billing_router(
            dependencies,
            configuration,
            gateway,
            StripeWebhookSignatureVerifier(SECRET),
            store,
        )
    )
    app.include_router(
        create_mvp_billing_projection_router(
            dependencies,
            configuration,
            store,
        )
    )
    return TestClient(app, base_url="https://testserver"), gateway, store


def csrf(client: TestClient) -> dict[str, str]:
    client.cookies.set("__Host-ragstudio-csrf", "proof")
    return {"X-CSRF-Token": "proof", "Origin": "https://testserver"}


def signed(payload: bytes, *, timestamp: int | None = None) -> str:
    created = timestamp or int(time.time())
    message = f"{created}.{payload.decode()}".encode()
    digest = hmac.new(SECRET.encode(), message, hashlib.sha256).hexdigest()
    return f"t={created},v1={digest}"


def event(
    event_id: str,
    event_type: str,
    event_object: dict[str, JsonValue],
    *,
    created: int | None = None,
) -> bytes:
    return json.dumps(
        {
            "id": event_id,
            "type": event_type,
            "created": created or int(time.time()),
            "data": {"object": event_object},
        },
        separators=(",", ":"),
    ).encode()


def canonical(customer_id: str = "cus_routefixture01") -> CanonicalSubscription:
    return CanonicalSubscription(
        customer_id,
        "sub_routefixture01",
        SubscriptionStatus.ACTIVE,
        datetime(2026, 9, 25, tzinfo=UTC),
    )
