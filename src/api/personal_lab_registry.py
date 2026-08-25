"""Declarative registration seam for Personal Lab leaf routers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from fastapi import APIRouter

from src.api.personal_lab_scope import PersonalLabScopeResolver
from src.api.saas_auth_context import BffAuthContextResolver


class PersonalLabRouterRegistrationError(ValueError):
    """Raised when two Personal Lab leaves claim the same registration name."""


@dataclass(frozen=True, slots=True)
class PersonalLabRouteDependencies:
    """Shared server authorities supplied to every Personal Lab leaf router."""

    auth_context: BffAuthContextResolver
    scopes: PersonalLabScopeResolver


class PersonalLabRouterFactory(Protocol):
    """Build one leaf router from trusted Personal Lab dependencies."""

    def __call__(self, dependencies: PersonalLabRouteDependencies) -> APIRouter: ...


class PersonalLabRouterRegistry:
    """Mutable composition-time registry for explicitly named leaf routers."""

    def __init__(self) -> None:
        self._factories: dict[str, PersonalLabRouterFactory] = {}

    @property
    def names(self) -> tuple[str, ...]:
        """Return registered leaf names in deterministic registration order."""
        return tuple(self._factories)

    def register(self, name: str, factory: PersonalLabRouterFactory) -> None:
        """Register one unique leaf factory before application composition."""
        if name in self._factories:
            raise PersonalLabRouterRegistrationError(
                f"Personal Lab router {name!r} is already registered."
            )
        self._factories[name] = factory

    def build(
        self, dependencies: PersonalLabRouteDependencies
    ) -> tuple[APIRouter, ...]:
        """Build every explicitly registered leaf router."""
        return tuple(factory(dependencies) for factory in self._factories.values())
