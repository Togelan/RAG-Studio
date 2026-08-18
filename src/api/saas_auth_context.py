"""Reusable verified SaaS request context for protected BFF routers."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException, Request

from src.api.saas_identity import (
    IdentityRejectedError,
    IdentityUnavailableError,
    JwtClaims,
    TokenVerifier,
)
from src.api.saas_security import SESSION_COOKIE_NAME, BffSessionHandle
from src.api.saas_sessions import (
    BffSession,
    BffSessionStore,
    Membership,
    MembershipResolver,
)
from src.api.saas_workspace_context import MembershipResolutionUnavailableError


@dataclass(frozen=True, slots=True)
class AuthContext:
    """Verified provider identity plus an optional current membership."""

    session: BffSession
    claims: JwtClaims
    membership: Membership | None


@dataclass(frozen=True, slots=True)
class BffAuthContextResolver:
    """Revalidate the provider token and membership on every protected request."""

    token_verifier: TokenVerifier
    session_store: BffSessionStore
    membership_resolver: MembershipResolver

    async def resolve(
        self, request: Request, *, require_workspace: bool
    ) -> AuthContext:
        """Return a trusted context or a sanitized HTTP denial."""
        handle = self._session_handle(request)
        session = await self.session_store.get(handle)
        if session is None:
            raise _authentication_required()
        try:
            claims = await self.token_verifier.verify(session.access_token)
        except IdentityRejectedError, IdentityUnavailableError, PermissionError:
            await self.session_store.delete(handle)
            raise _authentication_required() from None
        if claims.user_id != session.user_id or claims.email != session.email:
            await self.session_store.delete(handle)
            raise _authentication_required()

        membership = await self._selected_membership(session)
        if require_workspace and membership is None:
            raise _workspace_unavailable()
        return AuthContext(session=session, claims=claims, membership=membership)

    async def _selected_membership(self, session: BffSession) -> Membership | None:
        workspace_id = session.active_workspace_id
        if workspace_id is None:
            return None
        try:
            membership = await self.membership_resolver.resolve(
                session.user_id, workspace_id
            )
        except MembershipResolutionUnavailableError:
            raise HTTPException(
                status_code=503,
                detail="Workspace authority is unavailable.",
            ) from None
        if membership is None:
            await self.session_store.select_workspace(session.handle, None)
        return membership

    @staticmethod
    def _session_handle(request: Request) -> BffSessionHandle:
        value = request.cookies.get(SESSION_COOKIE_NAME)
        if not value:
            raise _authentication_required()
        return BffSessionHandle(value)


def _authentication_required() -> HTTPException:
    return HTTPException(status_code=401, detail="Authentication required.")


def _workspace_unavailable() -> HTTPException:
    return HTTPException(status_code=403, detail="Workspace is unavailable.")
