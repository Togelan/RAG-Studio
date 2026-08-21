"""Reusable verified request context for protected BFF routers."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request

from src.api.saas_account_models import SelectedAccountContext
from src.api.saas_auth_models import AccountContextResolver
from src.api.saas_auth_service import SaasAuthContextService
from src.api.saas_identity import JwtClaims, TokenVerifier
from src.api.saas_sessions import (
    BffSession,
    BffSessionStore,
    Membership,
    MembershipResolver,
)


@dataclass(frozen=True, slots=True)
class AuthContext:
    """Verified provider identity plus an optional current membership."""

    session: BffSession
    claims: JwtClaims
    membership: Membership | None
    selected: SelectedAccountContext | None = None


@dataclass(frozen=True, slots=True)
class BffAuthContextResolver:
    """Revalidate identity and tenant authority before protected handlers."""

    token_verifier: TokenVerifier
    session_store: BffSessionStore
    membership_resolver: MembershipResolver
    account_context_resolver: AccountContextResolver | None = None

    async def resolve(
        self, request: Request, *, require_workspace: bool
    ) -> AuthContext:
        """Return a trusted downstream context or sanitized HTTP denial."""
        resolved = await SaasAuthContextService(
            self.token_verifier,
            self.session_store,
            self.membership_resolver,
            self.account_context_resolver,
        ).resolve(request, require_workspace=require_workspace)
        return AuthContext(
            resolved.session,
            resolved.claims,
            resolved.membership,
            resolved.selected,
        )
