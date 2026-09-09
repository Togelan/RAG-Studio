"""Loopback-only demo projections for billing and widget preview."""

from __future__ import annotations

import ipaddress
import os
from dataclasses import dataclass
from typing import Final, Literal, assert_never
from urllib.parse import urlsplit

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict

from src.api.personal_lab_registry import PersonalLabRouteDependencies

_ENABLED_ENV: Final = "RAG_STUDIO_LOCAL_DEMO_MODE"


class LocalDemoConfigurationError(ValueError):
    """Raised when demo mode could escape its loopback-only boundary."""


class _LocalDemoFeatureFlag(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    enabled: Literal["true", "false"]


class LocalDemoPlanResponse(BaseModel):
    """Display-only MVP price without payment or entitlement authority."""

    model_config = ConfigDict(frozen=True)

    amount_usd_cents: Literal[1_000] = 1_000
    currency: Literal["USD"] = "USD"
    interval: Literal["month"] = "month"


class LocalDemoBillingResponse(BaseModel):
    """Safe billing display state with no payment-provider authority."""

    model_config = ConfigDict(frozen=True)

    mode: Literal["local_demo"] = "local_demo"
    access: Literal["demo"] = "demo"
    stripe_configured: Literal[False] = False
    plan: LocalDemoPlanResponse = LocalDemoPlanResponse()


class LocalDemoWidgetResponse(BaseModel):
    """Safe widget preview state with no public publication authority."""

    model_config = ConfigDict(frozen=True)

    mode: Literal["local_demo"] = "local_demo"
    protected_preview: Literal[True] = True
    public_publication: Literal[False] = False


def load_local_demo_mode(
    trusted_origins: tuple[str, ...],
    *,
    billing_configured: bool,
    publication_enabled: bool,
) -> bool:
    """Load the opt-in flag and reject any non-loopback or real-commerce mix."""
    feature = _LocalDemoFeatureFlag.model_validate(
        {"enabled": os.getenv(_ENABLED_ENV, "false").strip().lower()}
    )
    match feature.enabled:
        case "false":
            return False
        case "true":
            safe = (
                not billing_configured
                and not publication_enabled
                and bool(trusted_origins)
                and all(_is_loopback_origin(origin) for origin in trusted_origins)
            )
            if not safe:
                raise LocalDemoConfigurationError(
                    "Local demo mode requires a loopback-only SaaS runtime "
                    "with billing and publication disabled."
                )
            return True
        case unreachable:
            assert_never(unreachable)


def _is_loopback_origin(origin: str) -> bool:
    host = urlsplit(origin).hostname
    if host is None:
        return False
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


@dataclass(frozen=True, slots=True)
class _LocalDemoHandlers:
    dependencies: PersonalLabRouteDependencies

    async def billing(self, request: Request) -> LocalDemoBillingResponse:
        await self._authorize(request)
        return LocalDemoBillingResponse()

    async def widget(self, request: Request) -> LocalDemoWidgetResponse:
        await self._authorize(request)
        return LocalDemoWidgetResponse()

    async def _authorize(self, request: Request) -> None:
        trusted = await self.dependencies.auth_context.resolve(
            request, require_workspace=False
        )
        await self.dependencies.scopes.resolve(trusted.claims.user_id)


def create_mvp_local_demo_router(
    dependencies: PersonalLabRouteDependencies,
) -> APIRouter:
    """Create authenticated read-only demo projections without mutation routes."""
    handlers = _LocalDemoHandlers(dependencies)
    router = APIRouter(tags=["personal-local-demo"])
    router.add_api_route(
        "/api/personal/billing",
        handlers.billing,
        methods=["GET"],
        response_model=LocalDemoBillingResponse,
    )
    router.add_api_route(
        "/api/personal/widget-publication",
        handlers.widget,
        methods=["GET"],
        response_model=LocalDemoWidgetResponse,
    )
    return router
