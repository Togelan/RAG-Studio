"""Bounded server-side Stripe transport for MVP billing routes."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import partial
from typing import Final, Protocol
from uuid import UUID

import anyio
import stripe
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, ValidationError
from stripe import StripeClient

from src.api.mvp_entitlements import (
    CanonicalSubscription,
    SubscriptionStatus,
    parse_subscription_status,
)

_STRIPE_TIMEOUT_SECONDS = 5.0
_WEBHOOK_TOLERANCE_SECONDS = 300
_VERIFY_STRIPE_HEADER: Final[Callable[[str, str, str, int], bool]] = (
    stripe.WebhookSignature.verify_header
)


class StripeGatewayUnavailableError(Exception):
    """Sanitized provider failure safe to translate at the HTTP boundary."""


class StripeSignatureError(Exception):
    """Raised when raw webhook bytes do not match the configured signature."""


@dataclass(frozen=True, slots=True)
class CheckoutCommand:
    """Server-owned values for one hosted subscription Checkout session."""

    personal_lab_id: UUID
    price_id: str
    success_url: str
    cancel_url: str
    idempotency_key: UUID


@dataclass(frozen=True, slots=True)
class PortalCommand:
    """Server-owned values for one hosted Customer Portal session."""

    customer_id: str
    configuration_id: str
    return_url: str
    idempotency_key: UUID


class BillingGateway(Protocol):
    """Capabilities used by the authenticated and webhook route boundary."""

    async def create_checkout(self, command: CheckoutCommand) -> str: ...

    async def create_portal(self, command: PortalCommand) -> str: ...

    async def retrieve_subscription(
        self, subscription_id: str
    ) -> CanonicalSubscription | None: ...


class WebhookSignatureVerifier(Protocol):
    """Verify exact raw webhook bytes before application JSON parsing."""

    def verify(self, payload: bytes, signature: str) -> None: ...


@dataclass(frozen=True, slots=True)
class StripeWebhookSignatureVerifier:
    """Apply Stripe's timestamped HMAC verification to exact request bytes."""

    secret: str

    def verify(self, payload: bytes, signature: str) -> None:
        try:
            decoded = payload.decode("utf-8")
            _VERIFY_STRIPE_HEADER(
                decoded,
                signature,
                self.secret,
                _WEBHOOK_TOLERANCE_SECONDS,
            )
            timestamp = int(
                next(
                    item.removeprefix("t=")
                    for item in signature.split(",")
                    if item.startswith("t=")
                )
            )
        except (
            UnicodeDecodeError,
            ValueError,
            StopIteration,
            stripe.SignatureVerificationError,
        ):
            raise StripeSignatureError from None
        if timestamp > time.time() + _WEBHOOK_TOLERANCE_SECONDS:
            raise StripeSignatureError


class _HostedSession(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    url: HttpUrl


class _SubscriptionItem(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    current_period_end: int = Field(gt=0)


class _SubscriptionItems(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    data: tuple[_SubscriptionItem, ...] = Field(min_length=1)


class _SubscriptionSnapshot(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    id: str = Field(pattern=r"^sub_[A-Za-z0-9]{8,}$")
    customer: str = Field(pattern=r"^cus_[A-Za-z0-9]{8,}$")
    status: str
    items: _SubscriptionItems


@dataclass(frozen=True, slots=True)
class StripeBillingGateway:
    """Adapt one isolated Stripe client without module-global credentials."""

    client: StripeClient

    async def create_checkout(self, command: CheckoutCommand) -> str:
        metadata = {
            "personal_lab_id": str(command.personal_lab_id),
            "plan_version": "mvp-v1",
        }
        create = partial(
            self.client.v1.checkout.sessions.create,
            {
                "mode": "subscription",
                "line_items": [{"price": command.price_id, "quantity": 1}],
                "success_url": command.success_url,
                "cancel_url": command.cancel_url,
                "client_reference_id": str(command.personal_lab_id),
                "metadata": metadata,
                "subscription_data": {"metadata": metadata},
            },
            {"idempotency_key": str(command.idempotency_key)},
        )
        session = await self._call(create)
        try:
            return str(_HostedSession.model_validate(session).url)
        except ValidationError:
            raise StripeGatewayUnavailableError from None

    async def create_portal(self, command: PortalCommand) -> str:
        create = partial(
            self.client.v1.billing_portal.sessions.create,
            {
                "customer": command.customer_id,
                "configuration": command.configuration_id,
                "return_url": command.return_url,
            },
            {"idempotency_key": str(command.idempotency_key)},
        )
        session = await self._call(create)
        try:
            return str(_HostedSession.model_validate(session).url)
        except ValidationError:
            raise StripeGatewayUnavailableError from None

    async def retrieve_subscription(
        self, subscription_id: str
    ) -> CanonicalSubscription | None:
        retrieve = partial(self.client.v1.subscriptions.retrieve, subscription_id)
        raw = await self._call(retrieve)
        try:
            snapshot = _SubscriptionSnapshot.model_validate(raw)
        except ValidationError:
            return None
        status = parse_subscription_status(snapshot.status)
        if status is None or status is SubscriptionStatus.NONE:
            return None
        period_end = max(item.current_period_end for item in snapshot.items.data)
        return CanonicalSubscription(
            customer_id=snapshot.customer,
            subscription_id=snapshot.id,
            status=status,
            current_period_end=datetime.fromtimestamp(period_end, tz=UTC),
        )

    @staticmethod
    async def _call[Result](operation: partial[Result]) -> Result:
        try:
            with anyio.fail_after(_STRIPE_TIMEOUT_SECONDS):
                return await anyio.to_thread.run_sync(operation, abandon_on_cancel=True)
        except stripe.StripeError, TimeoutError, OSError:
            raise StripeGatewayUnavailableError from None
