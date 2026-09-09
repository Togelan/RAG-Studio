"""Transactional Postgres contracts for MVP entitlement and quota state."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal, assert_never
from uuid import UUID

import asyncpg

from src.api.mvp_entitlements import (
    BillingProjection,
    EntitlementMutation,
    SubscriptionStatus,
    VerifiedBillingEvent,
)


class LedgerOutcome(StrEnum):
    """Stable result of attempting one verified event transaction."""

    APPLIED = "applied"
    STALE = "stale"
    DUPLICATE = "duplicate"


class QuotaOutcome(StrEnum):
    """Stable result of a durable quota lifecycle operation."""

    ACCEPTED = "accepted"
    SATURATED = "saturated"
    ALREADY_FINALIZED = "already_finalized"


class BillingStoreUnavailableError(Exception):
    """Sanitized failure raised when durable billing state is unavailable."""


@asynccontextmanager
async def _transaction(database_url: str) -> AsyncIterator[asyncpg.Connection]:
    try:
        connection = await asyncpg.connect(database_url, timeout=5.0)
        try:
            async with connection.transaction():
                await connection.execute("SET LOCAL statement_timeout = '5s'")
                yield connection
        finally:
            await connection.close(timeout=5.0)
    except asyncpg.PostgresError, OSError, TimeoutError:
        raise BillingStoreUnavailableError from None


@dataclass(frozen=True, slots=True)
class PostgresMvpBillingStore:
    """Use Task 3 procedures as the durable transaction and quota authority."""

    database_url: str

    async def projection_for_lab(
        self, personal_lab_id: UUID
    ) -> BillingProjection | None:
        """Read one validated display-safe entitlement projection."""
        async with _transaction(self.database_url) as connection:
            row = await connection.fetchrow(
                "SELECT stripe_customer_id, subscription_status, entitled "
                "FROM public.personal_lab_billing_projections "
                "WHERE personal_lab_id=$1",
                personal_lab_id,
            )
        if row is None:
            return None
        customer_id = row["stripe_customer_id"]
        status = row["subscription_status"]
        entitled = row["entitled"]
        if (
            not isinstance(customer_id, str | None)
            or not isinstance(status, str)
            or not isinstance(entitled, bool)
        ):
            raise BillingStoreUnavailableError
        try:
            parsed_status = SubscriptionStatus(status)
        except ValueError:
            raise BillingStoreUnavailableError from None
        return BillingProjection(
            status=parsed_status,
            entitled=entitled,
            can_manage=customer_id is not None,
        )

    async def customer_for_lab(self, personal_lab_id: UUID) -> str | None:
        """Return the verified Stripe customer bound to one Personal Lab."""
        async with _transaction(self.database_url) as connection:
            customer_id: str | None = await connection.fetchval(
                "SELECT stripe_customer_id "
                "FROM public.personal_lab_billing_projections "
                "WHERE personal_lab_id=$1",
                personal_lab_id,
            )
        return customer_id

    async def personal_lab_for_customer(
        self, customer_id: str, claimed_lab_id: UUID | None = None
    ) -> UUID | None:
        """Resolve only an existing canonical or unclaimed Checkout binding."""
        async with _transaction(self.database_url) as connection:
            if claimed_lab_id is None:
                personal_lab_id: UUID | None = await connection.fetchval(
                    "SELECT personal_lab_id "
                    "FROM public.personal_lab_billing_projections "
                    "WHERE stripe_customer_id=$1",
                    customer_id,
                )
            else:
                personal_lab_id = await connection.fetchval(
                    "SELECT labs.id FROM public.personal_labs AS labs "
                    "LEFT JOIN public.personal_lab_billing_projections AS billing "
                    "ON billing.personal_lab_id=labs.id "
                    "WHERE labs.id=$1 AND "
                    "(billing.stripe_customer_id IS NULL "
                    "OR billing.stripe_customer_id=$2)",
                    claimed_lab_id,
                    customer_id,
                )
        return personal_lab_id

    async def apply_event(
        self,
        personal_lab_id: UUID,
        event: VerifiedBillingEvent,
        mutation: EntitlementMutation,
    ) -> LedgerOutcome:
        """Atomically append one ledger row and update its canonical projection."""
        async with _transaction(self.database_url) as connection:
            before = await connection.fetchval(
                "SELECT count(*) FROM public.stripe_event_ledger "
                "WHERE stripe_event_id=$1",
                event.event_id,
            )
            if before:
                return LedgerOutcome.DUPLICATE
            applied = bool(
                await connection.fetchval(
                    "SELECT private.apply_personal_lab_billing_event"
                    "($1,$2,$3,$4,$5,$6,$7,$8,$9)",
                    personal_lab_id,
                    event.event_id,
                    event.event_type,
                    mutation.customer_id,
                    mutation.subscription_id,
                    mutation.status.value,
                    mutation.entitled,
                    event.created_at,
                    mutation.current_period_end,
                )
            )
            if not applied:
                return LedgerOutcome.DUPLICATE
            outcome = await connection.fetchval(
                "SELECT outcome FROM public.stripe_event_ledger "
                "WHERE stripe_event_id=$1",
                event.event_id,
            )
        return LedgerOutcome(str(outcome))

    async def reserve(self, publication_id: UUID, reservation_id: UUID) -> QuotaOutcome:
        """Atomically reserve one slot in the current persistent UTC month."""
        async with _transaction(self.database_url) as connection:
            accepted = bool(
                await connection.fetchval(
                    "SELECT private.reserve_personal_lab_widget_message($1,$2)",
                    publication_id,
                    reservation_id,
                )
            )
        return QuotaOutcome.ACCEPTED if accepted else QuotaOutcome.SATURATED

    async def commit(self, reservation_id: UUID) -> QuotaOutcome:
        """Commit one reserved message exactly once."""
        return await self._finalize("commit", reservation_id)

    async def release(self, reservation_id: UUID) -> QuotaOutcome:
        """Release one canceled or failed reservation exactly once."""
        return await self._finalize("release", reservation_id)

    async def _finalize(
        self, action: Literal["commit", "release"], reservation_id: UUID
    ) -> QuotaOutcome:
        match action:
            case "commit":
                query = "SELECT private.commit_personal_lab_widget_message($1)"
            case "release":
                query = "SELECT private.release_personal_lab_widget_message($1)"
            case unreachable:
                assert_never(unreachable)
        async with _transaction(self.database_url) as connection:
            changed = bool(await connection.fetchval(query, reservation_id))
        return QuotaOutcome.ACCEPTED if changed else QuotaOutcome.ALREADY_FINALIZED
