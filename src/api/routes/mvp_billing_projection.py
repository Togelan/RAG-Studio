"""Authenticated display-safe Personal Lab billing projection route."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from src.api.billing_runtime import BillingConfiguration
from src.api.mvp_billing_store import BillingStoreUnavailableError
from src.api.mvp_entitlements import (
    BillingProjection,
    SubscriptionStatus,
    resolve_mvp_plan,
)
from src.api.personal_lab_registry import PersonalLabRouteDependencies


class BillingProjectionStore(Protocol):
    """Read the durable billing projection for one trusted Personal Lab."""

    async def projection_for_lab(
        self, personal_lab_id: UUID
    ) -> BillingProjection | None: ...


class BillingPlanResponse(BaseModel):
    """One browser-safe representation of the configured MVP plan."""

    model_config = ConfigDict(frozen=True)

    amount_usd_cents: int = Field(ge=0)
    currency: Literal["USD"] = "USD"
    interval: Literal["month"] = "month"


class BillingProjectionResponse(BaseModel):
    """Authenticated billing status without provider identifiers or event data."""

    model_config = ConfigDict(frozen=True)

    plan: BillingPlanResponse
    status: SubscriptionStatus
    pending: bool
    entitled: bool
    can_manage: bool


@dataclass(frozen=True, slots=True)
class _BillingProjectionHandlers:
    dependencies: PersonalLabRouteDependencies
    configuration: BillingConfiguration
    store: BillingProjectionStore

    async def read(self, request: Request) -> BillingProjectionResponse:
        """Resolve the caller's Personal Lab and return its safe projection."""
        trusted = await self.dependencies.auth_context.resolve(
            request, require_workspace=False
        )
        scope = await self.dependencies.scopes.resolve(trusted.claims.user_id)
        try:
            projection = await self.store.projection_for_lab(scope.id)
        except BillingStoreUnavailableError:
            raise HTTPException(503, detail="Billing state is unavailable.") from None
        if projection is None:
            resolved = BillingProjection(
                status=SubscriptionStatus.NONE,
                entitled=False,
                can_manage=False,
            )
        else:
            if (
                not isinstance(projection, BillingProjection)
                or not isinstance(projection.status, SubscriptionStatus)
                or not isinstance(projection.entitled, bool)
                or not isinstance(projection.can_manage, bool)
            ):
                raise HTTPException(503, detail="Billing state is unavailable.")
            resolved = projection
        plan = resolve_mvp_plan(self.configuration.price_id)
        return BillingProjectionResponse(
            plan=BillingPlanResponse(amount_usd_cents=plan.unit_amount_usd_cents),
            status=resolved.status,
            pending=resolved.status is SubscriptionStatus.INCOMPLETE,
            entitled=resolved.entitled,
            can_manage=resolved.can_manage,
        )


def create_mvp_billing_projection_router(
    dependencies: PersonalLabRouteDependencies,
    configuration: BillingConfiguration,
    store: BillingProjectionStore,
) -> APIRouter:
    """Create the authenticated read-only billing projection endpoint."""
    handlers = _BillingProjectionHandlers(dependencies, configuration, store)
    router = APIRouter(tags=["personal-billing"])
    router.add_api_route(
        "/api/personal/billing",
        handlers.read,
        methods=["GET"],
        response_model=BillingProjectionResponse,
    )
    return router
