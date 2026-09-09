"""Authenticated hosted billing and signed Stripe webhook routes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Protocol, assert_never
from uuid import UUID, uuid4

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, JsonValue, ValidationError

from src.api.billing_runtime import BillingConfiguration
from src.api.mvp_billing_store import (
    BillingStoreUnavailableError,
    LedgerOutcome,
)
from src.api.mvp_entitlements import (
    EntitlementMutation,
    ReductionOutcome,
    StripeEventType,
    VerifiedBillingEvent,
    reduce_verified_event,
)
from src.api.mvp_stripe_gateway import (
    BillingGateway,
    CheckoutCommand,
    PortalCommand,
    StripeGatewayUnavailableError,
    StripeSignatureError,
    WebhookSignatureVerifier,
)
from src.api.personal_lab_registry import PersonalLabRouteDependencies
from src.api.personal_lab_scope import PersonalLabScope


class BillingEventStore(Protocol):
    """Durable billing lookups and atomic event projection capability."""

    async def customer_for_lab(self, personal_lab_id: UUID) -> str | None: ...

    async def personal_lab_for_customer(
        self, customer_id: str, claimed_lab_id: UUID | None = None
    ) -> UUID | None: ...

    async def apply_event(
        self,
        personal_lab_id: UUID,
        event: VerifiedBillingEvent,
        mutation: EntitlementMutation,
    ) -> LedgerOutcome: ...


class InvalidBillingEventError(Exception):
    """Raised when a supported event has a malformed provider object."""


class HostedBillingResponse(BaseModel):
    """Browser-safe hosted billing destination."""

    model_config = ConfigDict(frozen=True)

    url: str = Field(pattern=r"^https://")


class WebhookResponse(BaseModel):
    """Stable acknowledgement without provider or customer details."""

    model_config = ConfigDict(frozen=True)

    outcome: str


class _EventData(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    object: dict[str, JsonValue]


class _StripeEvent(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    id: str = Field(pattern=r"^evt_[A-Za-z0-9]{8,}$")
    type: str = Field(min_length=3, max_length=120)
    created: int = Field(gt=0)
    data: _EventData


class _Metadata(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    personal_lab_id: UUID


class _CheckoutObject(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    subscription: str = Field(pattern=r"^sub_[A-Za-z0-9]{8,}$")
    metadata: _Metadata


class _SubscriptionObject(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    id: str = Field(pattern=r"^sub_[A-Za-z0-9]{8,}$")


class _SubscriptionDetails(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    subscription: str = Field(pattern=r"^sub_[A-Za-z0-9]{8,}$")


class _InvoiceParent(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    subscription_details: _SubscriptionDetails


class _InvoiceObject(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    parent: _InvoiceParent


@dataclass(frozen=True, slots=True)
class _SubscriptionReference:
    subscription_id: str
    claimed_lab_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class _BillingHandlers:
    dependencies: PersonalLabRouteDependencies
    configuration: BillingConfiguration
    gateway: BillingGateway
    verifier: WebhookSignatureVerifier
    store: BillingEventStore

    async def checkout(self, request: Request) -> HostedBillingResponse:
        scope = await _scope(request, self.dependencies)
        base_url = str(self.configuration.public_app_url).rstrip("/")
        command = CheckoutCommand(
            personal_lab_id=scope.id,
            price_id=self.configuration.price_id,
            success_url=f"{base_url}/billing?checkout=success",
            cancel_url=f"{base_url}/billing?checkout=canceled",
            idempotency_key=uuid4(),
        )
        try:
            return HostedBillingResponse(
                url=await self.gateway.create_checkout(command)
            )
        except StripeGatewayUnavailableError:
            raise _provider_unavailable() from None

    async def portal(self, request: Request) -> HostedBillingResponse:
        scope = await _scope(request, self.dependencies)
        try:
            customer_id = await self.store.customer_for_lab(scope.id)
        except BillingStoreUnavailableError:
            raise _billing_unavailable() from None
        if customer_id is None:
            raise HTTPException(409, detail="Billing account is not available.")
        command = PortalCommand(
            customer_id=customer_id,
            configuration_id=self.configuration.portal_configuration_id,
            return_url=f"{str(self.configuration.public_app_url).rstrip('/')}/billing",
            idempotency_key=uuid4(),
        )
        try:
            return HostedBillingResponse(url=await self.gateway.create_portal(command))
        except StripeGatewayUnavailableError:
            raise _provider_unavailable() from None

    async def webhook(
        self,
        request: Request,
        stripe_signature: Annotated[
            str | None, Header(alias="Stripe-Signature")
        ] = None,
    ) -> WebhookResponse:
        payload = await request.body()
        if stripe_signature is None:
            raise _invalid_webhook()
        try:
            self.verifier.verify(payload, stripe_signature)
            incoming = _StripeEvent.model_validate_json(payload)
        except StripeSignatureError, ValidationError:
            raise _invalid_webhook() from None
        try:
            created_at = datetime.fromtimestamp(incoming.created, tz=UTC)
        except OSError, OverflowError, ValueError:
            raise _invalid_webhook() from None
        verified = VerifiedBillingEvent(incoming.id, incoming.type, created_at)
        try:
            reference = _reference(incoming)
        except InvalidBillingEventError:
            raise _invalid_webhook() from None
        if reference is None:
            return WebhookResponse(outcome=ReductionOutcome.IGNORE.value)
        try:
            canonical = await self.gateway.retrieve_subscription(
                reference.subscription_id
            )
        except StripeGatewayUnavailableError:
            raise _provider_unavailable() from None
        reduction = reduce_verified_event(verified, canonical)
        if reduction.outcome is ReductionOutcome.RETRY or reduction.mutation is None:
            raise _provider_unavailable()
        try:
            personal_lab_id = await self.store.personal_lab_for_customer(
                reduction.mutation.customer_id, reference.claimed_lab_id
            )
            if personal_lab_id is None:
                return WebhookResponse(outcome=ReductionOutcome.IGNORE.value)
            outcome = await self.store.apply_event(
                personal_lab_id, verified, reduction.mutation
            )
        except BillingStoreUnavailableError:
            raise _billing_unavailable() from None
        return WebhookResponse(outcome=outcome.value)


def create_mvp_billing_router(
    dependencies: PersonalLabRouteDependencies,
    configuration: BillingConfiguration,
    gateway: BillingGateway,
    verifier: WebhookSignatureVerifier,
    store: BillingEventStore,
) -> APIRouter:
    """Create hosted user actions and the CSRF-exempt signed webhook endpoint."""
    handlers = _BillingHandlers(dependencies, configuration, gateway, verifier, store)
    router = APIRouter(tags=["personal-billing"])
    router.add_api_route(
        "/api/personal/billing/checkout",
        handlers.checkout,
        methods=["POST"],
        response_model=HostedBillingResponse,
    )
    router.add_api_route(
        "/api/personal/billing/portal",
        handlers.portal,
        methods=["POST"],
        response_model=HostedBillingResponse,
    )
    router.add_api_route(
        "/api/billing/stripe/webhook",
        handlers.webhook,
        methods=["POST"],
        response_model=WebhookResponse,
    )
    return router


async def _scope(
    request: Request, dependencies: PersonalLabRouteDependencies
) -> PersonalLabScope:
    trusted = await dependencies.auth_context.resolve(request, require_workspace=False)
    return await dependencies.scopes.resolve(trusted.claims.user_id)


def _reference(event: _StripeEvent) -> _SubscriptionReference | None:
    try:
        event_type = StripeEventType(event.type)
    except ValueError:
        return None
    try:
        match event_type:
            case StripeEventType.CHECKOUT_COMPLETED:
                checkout = _CheckoutObject.model_validate(event.data.object)
                return _SubscriptionReference(
                    checkout.subscription, checkout.metadata.personal_lab_id
                )
            case (
                StripeEventType.SUBSCRIPTION_CREATED
                | StripeEventType.SUBSCRIPTION_UPDATED
                | StripeEventType.SUBSCRIPTION_DELETED
            ):
                subscription = _SubscriptionObject.model_validate(event.data.object)
                return _SubscriptionReference(subscription.id)
            case StripeEventType.INVOICE_PAID | StripeEventType.INVOICE_PAYMENT_FAILED:
                invoice = _InvoiceObject.model_validate(event.data.object)
                return _SubscriptionReference(
                    invoice.parent.subscription_details.subscription
                )
            case unreachable:
                assert_never(unreachable)
    except ValidationError:
        raise InvalidBillingEventError from None


def _provider_unavailable() -> HTTPException:
    return HTTPException(502, detail="Billing provider is unavailable.")


def _billing_unavailable() -> HTTPException:
    return HTTPException(503, detail="Billing state is unavailable.")


def _invalid_webhook() -> HTTPException:
    return HTTPException(400, detail="Invalid webhook.")
