"""Trusted request-context service for unified BFF authentication."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from fastapi import HTTPException, Request

from src.api.saas_account_models import (
    AccountContext,
    AccountContextError,
    AccountContextErrorCode,
    SelectedAccountContext,
)
from src.api.saas_auth_models import AccountContextResolver
from src.api.saas_identity import (
    IdentityRejectedError,
    IdentityUnavailableError,
    JwtClaims,
    TokenVerifier,
)
from src.api.saas_security import BffSessionHandle, load_cookie_transport_policy
from src.api.saas_sessions import (
    BffSession,
    BffSessionStore,
    Membership,
    MembershipResolver,
)
from src.api.saas_workspace_context import MembershipResolutionUnavailableError


@dataclass(frozen=True, slots=True)
class AuthContext:
    """Verified identity and current server-confirmed selection."""

    session: BffSession
    claims: JwtClaims
    membership: Membership | None
    selected: SelectedAccountContext | None


@dataclass(frozen=True, slots=True)
class SaasAuthContextService:
    """Revalidate identity, Account, and Workspace on every protected request."""

    token_verifier: TokenVerifier
    session_store: BffSessionStore
    membership_resolver: MembershipResolver
    account_resolver: AccountContextResolver | None = None

    async def resolve(
        self, request: Request, *, require_workspace: bool
    ) -> AuthContext:
        """Resolve the browser cookie, then revalidate its server-side session."""
        handle = session_handle(request)
        session = await self.session_store.get(handle)
        if session is None:
            raise authentication_required()
        return await self.revalidate(session, require_workspace=require_workspace)

    async def revalidate(
        self, session: BffSession, *, require_workspace: bool
    ) -> AuthContext:
        """Return a trusted context or a sanitized HTTP denial."""
        claims = await self._verified_claims(session)
        selected = await self._selected_account(session)
        membership = await self._membership(session, selected)
        if require_workspace and membership is None:
            if self.account_resolver is None:
                raise workspace_unavailable()
            raise context_unavailable()
        return AuthContext(session, claims, membership, selected)

    async def available(self, user_id: UUID) -> tuple[AccountContext, ...]:
        """List trusted contexts when the Account authority is configured."""
        if self.account_resolver is None:
            return ()
        try:
            return await self.account_resolver.available(user_id)
        except AccountContextError as error:
            raise _account_http_error(error) from None

    async def select(
        self,
        session: BffSession,
        *,
        account_id: UUID,
        workspace_id: UUID | None,
    ) -> SelectedAccountContext:
        """Validate then persist an explicit Account/Workspace choice."""
        if self.account_resolver is None:
            raise context_unavailable()
        try:
            selected = await self.account_resolver.resolve(
                session.user_id,
                account_id=account_id,
                workspace_id=workspace_id,
            )
        except AccountContextError as error:
            raise _account_http_error(error) from None
        updated = await self.session_store.select_account(session.handle, account_id)
        if updated is None:
            raise authentication_required()
        if workspace_id is not None:
            updated = await self.session_store.select_workspace(
                session.handle, workspace_id
            )
            if updated is None:
                raise authentication_required()
        return selected

    async def _verified_claims(self, session: BffSession) -> JwtClaims:
        try:
            claims = await self.token_verifier.verify(session.access_token)
        except IdentityRejectedError, PermissionError:
            await self.session_store.delete(session.handle)
            raise authentication_required() from None
        except IdentityUnavailableError:
            raise HTTPException(
                status_code=503, detail="Identity service is unavailable."
            ) from None
        if claims.user_id != session.user_id or claims.email != session.email:
            await self.session_store.delete(session.handle)
            raise authentication_required()
        return claims

    async def _selected_account(
        self, session: BffSession
    ) -> SelectedAccountContext | None:
        if self.account_resolver is None or session.active_account_id is None:
            return None
        try:
            return await self.account_resolver.resolve(
                session.user_id,
                account_id=session.active_account_id,
                workspace_id=session.active_workspace_id,
            )
        except AccountContextError as error:
            if error.code is AccountContextErrorCode.DENIED:
                await self.session_store.select_account(session.handle, None)
                return None
            raise _account_http_error(error) from None

    async def _membership(
        self,
        session: BffSession,
        selected: SelectedAccountContext | None,
    ) -> Membership | None:
        if selected is not None and selected.workspace is not None:
            return Membership(selected.workspace.id, selected.workspace.role)
        if self.account_resolver is not None or session.active_workspace_id is None:
            return None
        try:
            membership = await self.membership_resolver.resolve(
                session.user_id, session.active_workspace_id
            )
        except MembershipResolutionUnavailableError:
            raise HTTPException(
                status_code=503, detail="Workspace authority is unavailable."
            ) from None
        if membership is None:
            await self.session_store.select_workspace(session.handle, None)
        return membership


def session_handle(request: Request) -> BffSessionHandle:
    """Parse the opaque browser cookie without exposing it in a response."""
    value = request.cookies.get(load_cookie_transport_policy().session_cookie_name)
    if not value:
        raise authentication_required()
    return BffSessionHandle(value)


def authentication_required() -> HTTPException:
    """Return the stable sanitized authentication denial."""
    return HTTPException(status_code=401, detail="Authentication required.")


def context_unavailable() -> HTTPException:
    """Return the stable sanitized Account/Workspace denial."""
    return HTTPException(status_code=403, detail="Account or Workspace is unavailable.")


def workspace_unavailable() -> HTTPException:
    """Return the legacy-compatible sanitized Workspace denial."""
    return HTTPException(status_code=403, detail="Workspace is unavailable.")


def _account_http_error(error: AccountContextError) -> HTTPException:
    if error.code is AccountContextErrorCode.UNAVAILABLE:
        return HTTPException(
            status_code=503, detail="Account authority is unavailable."
        )
    return context_unavailable()
