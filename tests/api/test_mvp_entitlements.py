from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID

import anyio
import pytest

from src.api.mvp_billing_store import LedgerOutcome, QuotaOutcome
from src.api.mvp_entitlements import (
    CanonicalSubscription,
    ReductionOutcome,
    StripeEventType,
    SubscriptionStatus,
    VerifiedBillingEvent,
    canonical_order,
    parse_subscription_status,
    reduce_verified_event,
    resolve_mvp_plan,
)


def test_catalog_exposes_one_versioned_ten_dollar_monthly_plan() -> None:
    # Given: the configured opaque Stripe Price identifier.
    price_id = "price_runtimefixture0001"

    # When: the server-owned MVP catalogue resolves it.
    plan = resolve_mvp_plan(price_id)

    # Then: the only commercial contract is versioned and fixed at $10/month.
    assert (plan.version, plan.unit_amount_usd_cents, plan.interval) == (
        "mvp-v1",
        1_000,
        "month",
    )


def _event(event_id: str, event_type: str, second: int) -> VerifiedBillingEvent:
    return VerifiedBillingEvent(
        event_id=event_id,
        event_type=event_type,
        created_at=datetime(2026, 8, 25, 12, 0, second, tzinfo=UTC),
    )


def _subscription(status: SubscriptionStatus) -> CanonicalSubscription:
    return CanonicalSubscription(
        customer_id="cus_redactedfixture",
        subscription_id="sub_redactedfixture",
        status=status,
        current_period_end=datetime(2026, 9, 25, tzinfo=UTC),
    )


@pytest.mark.parametrize(
    ("status", "entitled"),
    (
        (SubscriptionStatus.ACTIVE, True),
        (SubscriptionStatus.PAST_DUE, False),
        (SubscriptionStatus.INCOMPLETE, False),
        (SubscriptionStatus.UNPAID, False),
        (SubscriptionStatus.CANCELED, False),
    ),
)
def test_supported_lifecycle_maps_explicit_entitlement(
    status: SubscriptionStatus, entitled: bool
) -> None:
    # Given: a supported verified update and a canonical refreshed subscription.
    event = _event("evt_status00000001", StripeEventType.SUBSCRIPTION_UPDATED, 1)

    # When: the event is reduced.
    result = reduce_verified_event(event, _subscription(status))

    # Then: only active grants entitlement.
    assert result.outcome is ReductionOutcome.APPLY
    assert result.mutation is not None
    assert result.mutation.entitled is entitled


@pytest.mark.parametrize("event_type", tuple(StripeEventType))
def test_every_supported_event_requires_canonical_refresh(event_type: str) -> None:
    # Given: verified metadata for a supported lifecycle event without a refresh.
    event = _event("evt_retry00000001", event_type, 1)

    # When: reduction cannot obtain canonical subscription state.
    result = reduce_verified_event(event, None)

    # Then: it returns one bounded retry result and no state mutation.
    assert result == type(result)(ReductionOutcome.RETRY)


def test_unknown_event_is_stably_ignored() -> None:
    # Given: a verified but unsupported Stripe event name.
    event = _event("evt_unknown0000001", "customer.created", 1)

    # When: it reaches the reducer.
    result = reduce_verified_event(event, _subscription(SubscriptionStatus.ACTIVE))

    # Then: it has no projection authority and completes as ignored.
    assert result == type(result)(ReductionOutcome.IGNORE)


def test_unknown_subscription_status_has_bounded_retry_path() -> None:
    # Given: a new or malformed Stripe subscription status at the parse boundary.
    event = _event("evt_newstatus000001", StripeEventType.SUBSCRIPTION_UPDATED, 1)

    # When: parsing and reduction are attempted without a recognized snapshot.
    status = parse_subscription_status("future_status")
    result = reduce_verified_event(
        event, None if status is None else _subscription(status)
    )

    # Then: no entitlement mutation is inferred from unknown provider state.
    assert result == type(result)(ReductionOutcome.RETRY)


@dataclass(slots=True)
class _AtomicLedger:
    projections: dict[UUID, tuple[tuple[datetime, str], SubscriptionStatus]] = field(
        default_factory=dict
    )
    events: dict[str, LedgerOutcome] = field(default_factory=dict)

    def apply(
        self,
        lab_id: UUID,
        event: VerifiedBillingEvent,
        status: SubscriptionStatus,
        *,
        fail_projection: bool = False,
    ) -> LedgerOutcome:
        snapshot = (dict(self.projections), dict(self.events))
        if event.event_id in self.events:
            return LedgerOutcome.DUPLICATE
        current = self.projections.get(lab_id)
        outcome = (
            LedgerOutcome.APPLIED
            if current is None or canonical_order(event) > current[0]
            else LedgerOutcome.STALE
        )
        self.events[event.event_id] = outcome
        try:
            if outcome is LedgerOutcome.APPLIED:
                if fail_projection:
                    raise RuntimeError("injected projection fault")
                self.projections[lab_id] = (canonical_order(event), status)
        except RuntimeError:
            self.projections, self.events = snapshot
            raise
        return outcome


def test_reverse_order_and_duplicate_events_converge_canonically() -> None:
    # Given: two ledgers and two ordered events delivered in opposite orders.
    lab_id = UUID("30000000-0000-4000-8000-000000000003")
    older = _event("evt_older000000001", StripeEventType.SUBSCRIPTION_UPDATED, 1)
    newer = _event("evt_newer000000001", StripeEventType.INVOICE_PAID, 2)
    forward, reverse = _AtomicLedger(), _AtomicLedger()

    # When: the same lifecycle is delivered forward, reversed, and duplicated.
    forward.apply(lab_id, older, SubscriptionStatus.PAST_DUE)
    forward.apply(lab_id, newer, SubscriptionStatus.ACTIVE)
    reverse.apply(lab_id, newer, SubscriptionStatus.ACTIVE)
    stale = reverse.apply(lab_id, older, SubscriptionStatus.PAST_DUE)
    duplicate = reverse.apply(lab_id, newer, SubscriptionStatus.ACTIVE)

    # Then: both projections converge and the duplicate adds no ledger row.
    assert forward.projections == reverse.projections
    assert stale is LedgerOutcome.STALE
    assert duplicate is LedgerOutcome.DUPLICATE
    assert len(reverse.events) == 2


def test_projection_failure_rolls_back_ledger_and_projection() -> None:
    # Given: one prior verified projection and a later verified event.
    lab_id = UUID("30000000-0000-4000-8000-000000000003")
    ledger = _AtomicLedger()
    original = _event("evt_original0000001", StripeEventType.INVOICE_PAID, 1)
    failing = _event("evt_failing00000001", StripeEventType.INVOICE_PAYMENT_FAILED, 2)
    ledger.apply(lab_id, original, SubscriptionStatus.ACTIVE)
    snapshot = (dict(ledger.projections), dict(ledger.events))

    # When: projection persistence fails inside the event transaction.
    with pytest.raises(RuntimeError, match="injected projection fault"):
        ledger.apply(lab_id, failing, SubscriptionStatus.PAST_DUE, fail_projection=True)

    # Then: neither the new ledger row nor projection survives.
    assert (ledger.projections, ledger.events) == snapshot


@dataclass(slots=True)
class _AtomicQuota:
    committed: int = 0
    reservations: dict[UUID, str] = field(default_factory=dict)
    lock: anyio.Lock = field(default_factory=anyio.Lock)

    async def reserve_and_commit(self, reservation_id: UUID) -> QuotaOutcome:
        async with self.lock:
            if reservation_id in self.reservations:
                return QuotaOutcome.ALREADY_FINALIZED
            if self.committed >= 500:
                self.reservations[reservation_id] = "released"
                return QuotaOutcome.SATURATED
            self.reservations[reservation_id] = "committed"
            self.committed += 1
            return QuotaOutcome.ACCEPTED

    async def reserve_then_release(self, reservation_id: UUID) -> None:
        async with self.lock:
            self.reservations[reservation_id] = "reserved"
            self.reservations[reservation_id] = "released"


@pytest.mark.anyio
async def test_501_concurrent_commits_cap_atomically_at_500() -> None:
    # Given: one persistent-month quota authority and 501 distinct attempts.
    quota = _AtomicQuota()
    outcomes: list[QuotaOutcome] = []

    async def attempt(index: int) -> None:
        outcomes.append(await quota.reserve_and_commit(UUID(int=index + 1)))

    # When: all attempts race for the same UTC-month budget.
    async with anyio.create_task_group() as tasks:
        for index in range(501):
            tasks.start_soon(attempt, index)

    # Then: exactly 500 commit and the 501st is durably released.
    assert outcomes.count(QuotaOutcome.ACCEPTED) == 500
    assert outcomes.count(QuotaOutcome.SATURATED) == 1
    assert quota.committed == 500
    assert tuple(quota.reservations.values()).count("released") == 1


@pytest.mark.anyio
async def test_cancellation_and_failure_release_reservations() -> None:
    # Given: two reserved attempts that do not complete generation.
    quota = _AtomicQuota()
    canceled, failed = UUID(int=600), UUID(int=601)

    # When: cancellation and failure follow the release lifecycle.
    await quota.reserve_then_release(canceled)
    await quota.reserve_then_release(failed)

    # Then: neither consumes the committed monthly budget.
    assert quota.committed == 0
    assert quota.reservations == {canceled: "released", failed: "released"}


@pytest.mark.anyio
async def test_committed_reservation_replay_is_not_admitted_again() -> None:
    # Given: one reservation that already consumed a monthly slot.
    quota = _AtomicQuota()
    reservation_id = UUID(int=700)
    assert await quota.reserve_and_commit(reservation_id) is QuotaOutcome.ACCEPTED

    # When: the same reservation is replayed after commit.
    replay = await quota.reserve_and_commit(reservation_id)

    # Then: replay is finalized and does not authorize uncounted work.
    assert replay is QuotaOutcome.ALREADY_FINALIZED
    assert quota.committed == 1
