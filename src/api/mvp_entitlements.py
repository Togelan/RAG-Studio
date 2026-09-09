"""Deterministic MVP billing catalogue and entitlement reduction."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Final


class StripeEventType(StrEnum):
    """Stripe lifecycle events accepted after signature verification."""

    CHECKOUT_COMPLETED = "checkout.session.completed"
    SUBSCRIPTION_CREATED = "customer.subscription.created"
    SUBSCRIPTION_UPDATED = "customer.subscription.updated"
    SUBSCRIPTION_DELETED = "customer.subscription.deleted"
    INVOICE_PAID = "invoice.paid"
    INVOICE_PAYMENT_FAILED = "invoice.payment_failed"


class SubscriptionStatus(StrEnum):
    """Persisted MVP subscription states."""

    NONE = "none"
    INCOMPLETE = "incomplete"
    ACTIVE = "active"
    PAST_DUE = "past_due"
    CANCELED = "canceled"
    UNPAID = "unpaid"


class ReductionOutcome(StrEnum):
    """Bounded reducer outcomes consumed by the webhook boundary."""

    APPLY = "apply"
    IGNORE = "ignore"
    RETRY = "retry"


@dataclass(frozen=True, slots=True)
class MvpPlan:
    """One immutable commercial plan in the versioned MVP catalogue."""

    version: str
    stripe_price_id: str
    unit_amount_usd_cents: int = 1_000
    interval: str = "month"
    monthly_widget_messages: int = 500


@dataclass(frozen=True, slots=True)
class CanonicalSubscription:
    """Latest Stripe subscription snapshot fetched by the transport."""

    customer_id: str
    subscription_id: str
    status: SubscriptionStatus
    current_period_end: datetime | None


@dataclass(frozen=True, slots=True)
class VerifiedBillingEvent:
    """Redacted verified event metadata safe for deterministic reduction."""

    event_id: str
    event_type: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class EntitlementMutation:
    """Canonical projection values written with the immutable ledger row."""

    customer_id: str
    subscription_id: str
    status: SubscriptionStatus
    entitled: bool
    current_period_end: datetime | None


@dataclass(frozen=True, slots=True)
class BillingProjection:
    """Display-safe persisted entitlement values for the Personal Lab owner."""

    status: SubscriptionStatus
    entitled: bool
    can_manage: bool


@dataclass(frozen=True, slots=True)
class Reduction:
    """Exhaustive reducer result with an optional projection mutation."""

    outcome: ReductionOutcome
    mutation: EntitlementMutation | None = None


_SUPPORTED_EVENTS: Final = frozenset(event.value for event in StripeEventType)


def resolve_mvp_plan(price_id: str) -> MvpPlan:
    """Bind the configured opaque Price identifier to the sole MVP plan."""
    return MvpPlan(version="mvp-v1", stripe_price_id=price_id)


def parse_subscription_status(raw_status: str) -> SubscriptionStatus | None:
    """Parse a Stripe status into the closed MVP projection state set."""
    try:
        return SubscriptionStatus(raw_status)
    except ValueError:
        return None


def reduce_verified_event(
    event: VerifiedBillingEvent,
    canonical_subscription: CanonicalSubscription | None,
) -> Reduction:
    """Reduce supported events only from a canonical Stripe refresh snapshot."""
    if event.event_type not in _SUPPORTED_EVENTS:
        return Reduction(ReductionOutcome.IGNORE)
    if canonical_subscription is None:
        return Reduction(ReductionOutcome.RETRY)
    status = canonical_subscription.status
    return Reduction(
        ReductionOutcome.APPLY,
        EntitlementMutation(
            customer_id=canonical_subscription.customer_id,
            subscription_id=canonical_subscription.subscription_id,
            status=status,
            entitled=status is SubscriptionStatus.ACTIVE,
            current_period_end=canonical_subscription.current_period_end,
        ),
    )


def canonical_order(event: VerifiedBillingEvent) -> tuple[datetime, str]:
    """Return a total UTC order so equal-second deliveries converge."""
    created_at = event.created_at
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)
    return created_at.astimezone(UTC), event.event_id
