"""Sanitized BFF authentication and trusted Account-context routes."""

from __future__ import annotations

import secrets
from typing import assert_never

from fastapi import APIRouter, HTTPException, Request, Response, status

from src.api.saas_auth_models import (
    AccountBootstrapper,
    AccountContextResolver,
    ContextSelectionRequest,
    CredentialsRequest,
    SessionResponse,
    SignupResponse,
    WorkspaceSelectionRequest,
    account_for_workspace,
    session_response,
)
from src.api.saas_auth_service import (
    SaasAuthContextService,
    authentication_required,
    session_handle,
    workspace_unavailable,
)
from src.api.saas_identity import (
    IdentityProvider,
    IdentityRejectedError,
    IdentityTokens,
    IdentityUnavailableError,
    SignupPending,
    TokenVerifier,
)
from src.api.saas_security import (
    BffSessionCookie,
    apply_bff_session_cookie,
    apply_csrf_cookie,
    clear_bff_cookies,
)
from src.api.saas_sessions import (
    BffSession,
    BffSessionStore,
    Membership,
    MembershipResolver,
)

_CSRF_LIFETIME_SECONDS = 3600
_SESSION_LIFETIME_SECONDS = 60 * 60 * 24 * 30


def create_saas_auth_router(
    *,
    identity_provider: IdentityProvider,
    token_verifier: TokenVerifier,
    session_store: BffSessionStore,
    membership_resolver: MembershipResolver,
    account_context_resolver: AccountContextResolver | None = None,
    account_bootstrapper: AccountBootstrapper | None = None,
) -> APIRouter:
    """Build unified BFF auth routes around server-owned authorities."""
    router = APIRouter(prefix="/api/saas/auth", tags=["saas-auth"])
    contexts = SaasAuthContextService(
        token_verifier,
        session_store,
        membership_resolver,
        account_context_resolver,
    )

    @router.get("/csrf", status_code=status.HTTP_204_NO_CONTENT)
    async def establish_csrf(response: Response) -> None:
        apply_csrf_cookie(response, secrets.token_urlsafe(32), _CSRF_LIFETIME_SECONDS)

    @router.post(
        "/signup", response_model=SignupResponse, status_code=status.HTTP_201_CREATED
    )
    async def signup(payload: CredentialsRequest, response: Response) -> SignupResponse:
        try:
            outcome = await identity_provider.signup(payload.email, payload.password)
        except IdentityRejectedError:
            raise HTTPException(
                status_code=400, detail="Signup could not be completed."
            ) from None
        except IdentityUnavailableError:
            raise _identity_unavailable() from None
        match outcome:
            case IdentityTokens() as tokens:
                session = await _establish_session(tokens, response, session_store)
                session = await _select_default_personal_lab(
                    session, account_bootstrapper, session_store
                )
                return SignupResponse(confirmation_required=False)
            case SignupPending():
                return SignupResponse(confirmation_required=True)
            case unreachable:
                assert_never(unreachable)

    @router.post("/signin", response_model=SessionResponse)
    async def signin(
        payload: CredentialsRequest, response: Response
    ) -> SessionResponse:
        try:
            tokens = await identity_provider.signin(payload.email, payload.password)
            claims = await token_verifier.verify(tokens.access_token)
        except IdentityRejectedError, PermissionError:
            raise authentication_required() from None
        except IdentityUnavailableError:
            raise _identity_unavailable() from None
        if claims.user_id != tokens.user.id or claims.email != tokens.user.email:
            raise authentication_required()
        session = await _establish_session(tokens, response, session_store)
        session = await _select_default_personal_lab(
            session, account_bootstrapper, session_store
        )
        return session_response(session, await contexts.available(session.user_id))

    @router.post("/refresh", response_model=SessionResponse)
    async def refresh(request: Request, response: Response) -> SessionResponse:
        handle = session_handle(request)
        lease = await session_store.begin_refresh(handle)
        if lease is None:
            raise authentication_required()
        try:
            tokens = await identity_provider.refresh(lease.session.refresh_token)
            claims = await token_verifier.verify(tokens.access_token)
        except IdentityRejectedError, PermissionError:
            await session_store.delete(handle)
            clear_bff_cookies(response)
            raise authentication_required() from None
        except IdentityUnavailableError:
            raise _identity_unavailable() from None
        if claims.user_id != lease.session.user_id or claims.email != tokens.user.email:
            await session_store.delete(handle)
            clear_bff_cookies(response)
            raise authentication_required()
        rotated = await session_store.rotate(
            handle,
            user_id=tokens.user.id,
            email=tokens.user.email,
            access_token=tokens.access_token,
            refresh_token=tokens.refresh_token,
            lifetime_seconds=tokens.expires_in_seconds,
            refresh_lifetime_seconds=_SESSION_LIFETIME_SECONDS,
            lease=lease,
        )
        if rotated is None:
            raise authentication_required()
        apply_bff_session_cookie(
            response, BffSessionCookie(rotated.handle, _SESSION_LIFETIME_SECONDS)
        )
        await contexts.revalidate(rotated, require_workspace=False)
        refreshed = await session_store.get(rotated.handle)
        if refreshed is None:
            raise authentication_required()
        return session_response(refreshed, await contexts.available(refreshed.user_id))

    @router.post("/signout", status_code=status.HTTP_204_NO_CONTENT)
    async def signout(request: Request, response: Response) -> None:
        handle = session_handle(request)
        session = await session_store.delete(handle)
        clear_bff_cookies(response)
        if session is None:
            return
        try:
            await identity_provider.signout(session.access_token)
        except IdentityRejectedError, IdentityUnavailableError:
            return

    @router.get("/session", response_model=SessionResponse)
    async def current_session(request: Request) -> SessionResponse:
        current = await contexts.resolve(request, require_workspace=False)
        refreshed = await session_store.get(current.session.handle)
        if refreshed is None:
            raise authentication_required()
        return session_response(
            refreshed,
            await contexts.available(refreshed.user_id),
            current.membership,
        )

    @router.get("/context", response_model=SessionResponse)
    async def current_context(request: Request) -> SessionResponse:
        current = await contexts.resolve(request, require_workspace=True)
        return session_response(
            current.session,
            await contexts.available(current.session.user_id),
            current.membership,
        )

    @router.put("/context", response_model=SessionResponse)
    async def select_context(
        payload: ContextSelectionRequest, request: Request
    ) -> SessionResponse:
        current = await contexts.resolve(request, require_workspace=False)
        selected = await contexts.select(
            current.session,
            account_id=payload.account_id,
            workspace_id=payload.workspace_id,
        )
        updated = await session_store.get(current.session.handle)
        if updated is None:
            raise authentication_required()
        membership = None
        if selected.workspace is not None:
            membership = Membership(selected.workspace.id, selected.workspace.role)
        return session_response(
            updated, await contexts.available(updated.user_id), membership
        )

    @router.put("/workspace", response_model=SessionResponse)
    async def select_workspace(
        payload: WorkspaceSelectionRequest, request: Request
    ) -> SessionResponse:
        current = await contexts.resolve(request, require_workspace=False)
        accounts = await contexts.available(current.session.user_id)
        account_id = account_for_workspace(accounts, payload.workspace_id)
        if account_id is not None:
            selected = await contexts.select(
                current.session,
                account_id=account_id,
                workspace_id=payload.workspace_id,
            )
            membership = (
                Membership(payload.workspace_id, selected.workspace.role)
                if selected.workspace is not None
                else None
            )
        else:
            membership = await membership_resolver.resolve(
                current.session.user_id, payload.workspace_id
            )
            if membership is None:
                raise workspace_unavailable()
            await session_store.select_workspace(
                current.session.handle, payload.workspace_id
            )
        updated = await session_store.get(current.session.handle)
        if updated is None:
            raise authentication_required()
        return session_response(updated, accounts, membership)

    return router


async def _establish_session(
    tokens: IdentityTokens, response: Response, store: BffSessionStore
) -> BffSession:
    session = await store.create(
        user_id=tokens.user.id,
        email=tokens.user.email,
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        lifetime_seconds=tokens.expires_in_seconds,
        refresh_lifetime_seconds=_SESSION_LIFETIME_SECONDS,
    )
    apply_bff_session_cookie(
        response, BffSessionCookie(session.handle, _SESSION_LIFETIME_SECONDS)
    )
    return session


async def _select_default_personal_lab(
    session: BffSession,
    account_bootstrapper: AccountBootstrapper | None,
    session_store: BffSessionStore,
) -> BffSession:
    """Select only the server-created owned Account for a new BFF session."""
    if account_bootstrapper is None:
        return session
    account = await account_bootstrapper.bootstrap_default_account(session.user_id)
    selected = await session_store.select_account(session.handle, account.id)
    if selected is None:
        raise authentication_required()
    return selected


def _identity_unavailable() -> HTTPException:
    return HTTPException(status_code=503, detail="Identity service is unavailable.")
