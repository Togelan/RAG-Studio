"""Sanitized BFF authentication and trusted workspace-context routes."""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from typing import assert_never
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from src.api.saas_identity import (
    IdentityProvider,
    IdentityRejectedError,
    IdentityTokens,
    IdentityUnavailableError,
    JwtClaims,
    SignupPending,
    TokenVerifier,
)
from src.api.saas_security import (
    SESSION_COOKIE_NAME,
    BffSessionCookie,
    BffSessionHandle,
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
from src.api.saas_workspace_context import MembershipResolutionUnavailableError

_CSRF_LIFETIME_SECONDS = 3600


class CredentialsRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    email: str = Field(min_length=3, max_length=320, pattern=r"^[^@\s]+@[^@\s]+$")
    password: str = Field(min_length=8, max_length=256)


class WorkspaceSelectionRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    workspace_id: UUID


class WorkspaceResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    role: str


class SessionResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    user_id: UUID
    email: str
    workspace: WorkspaceResponse | None


class SignupResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    confirmation_required: bool


@dataclass(frozen=True, slots=True)
class AuthContext:
    """Verified identity and current active membership."""

    session: BffSession
    claims: JwtClaims
    membership: Membership | None


def create_saas_auth_router(
    *,
    identity_provider: IdentityProvider,
    token_verifier: TokenVerifier,
    session_store: BffSessionStore,
    membership_resolver: MembershipResolver,
) -> APIRouter:
    """Build the FR-013 BFF routes around injected identity and membership authorities."""
    router = APIRouter(prefix="/api/saas/auth", tags=["saas-auth"])

    async def context(request: Request, *, require_workspace: bool) -> AuthContext:
        handle = _session_handle(request)
        session = await session_store.get(handle)
        if session is None:
            raise _authentication_required()
        try:
            claims = await token_verifier.verify(session.access_token)
        except IdentityRejectedError, IdentityUnavailableError, PermissionError:
            await session_store.delete(handle)
            raise _authentication_required() from None
        if claims.user_id != session.user_id:
            await session_store.delete(handle)
            raise _authentication_required()
        membership = None
        if session.active_workspace_id is not None:
            try:
                membership = await membership_resolver.resolve(
                    session.user_id, session.active_workspace_id
                )
            except MembershipResolutionUnavailableError:
                raise HTTPException(
                    status_code=503,
                    detail="Workspace authority is unavailable.",
                ) from None
            if membership is None:
                await session_store.select_workspace(handle, None)
        if require_workspace and membership is None:
            raise _workspace_unavailable()
        return AuthContext(session=session, claims=claims, membership=membership)

    @router.get("/csrf", status_code=status.HTTP_204_NO_CONTENT)
    async def establish_csrf(response: Response) -> None:
        apply_csrf_cookie(response, secrets.token_urlsafe(32), _CSRF_LIFETIME_SECONDS)

    @router.post(
        "/signup", response_model=SignupResponse, status_code=status.HTTP_201_CREATED
    )
    async def signup(payload: CredentialsRequest, response: Response) -> SignupResponse:
        try:
            outcome = await identity_provider.signup(
                str(payload.email), payload.password
            )
        except IdentityRejectedError:
            raise HTTPException(
                status_code=400, detail="Signup could not be completed."
            ) from None
        except IdentityUnavailableError:
            raise HTTPException(
                status_code=503, detail="Identity service is unavailable."
            ) from None
        match outcome:
            case IdentityTokens() as tokens:
                await _establish_session(tokens, response, session_store)
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
            tokens = await identity_provider.signin(
                str(payload.email), payload.password
            )
            claims = await token_verifier.verify(tokens.access_token)
        except IdentityRejectedError, PermissionError:
            raise _authentication_required() from None
        except IdentityUnavailableError:
            raise HTTPException(
                status_code=503, detail="Identity service is unavailable."
            ) from None
        if claims.user_id != tokens.user.id:
            raise _authentication_required()
        session = await _establish_session(tokens, response, session_store)
        return _session_response(session, None)

    @router.post("/refresh", response_model=SessionResponse)
    async def refresh(request: Request, response: Response) -> SessionResponse:
        handle = _session_handle(request)
        current = await session_store.get(handle)
        if current is None:
            raise _authentication_required()
        try:
            tokens = await identity_provider.refresh(current.refresh_token)
            claims = await token_verifier.verify(tokens.access_token)
        except IdentityRejectedError, PermissionError:
            await session_store.delete(handle)
            clear_bff_cookies(response)
            raise _authentication_required() from None
        except IdentityUnavailableError:
            raise HTTPException(
                status_code=503, detail="Identity service is unavailable."
            ) from None
        if claims.user_id != current.user_id:
            await session_store.delete(handle)
            clear_bff_cookies(response)
            raise _authentication_required()
        rotated = await session_store.rotate(
            handle,
            user_id=tokens.user.id,
            email=tokens.user.email,
            access_token=tokens.access_token,
            refresh_token=tokens.refresh_token,
            lifetime_seconds=tokens.expires_in_seconds,
        )
        if rotated is None:
            raise _authentication_required()
        apply_bff_session_cookie(
            response, BffSessionCookie(rotated.handle, tokens.expires_in_seconds)
        )
        membership = await _resolve_selected(
            rotated, membership_resolver, session_store
        )
        return _session_response(rotated, membership)

    @router.post("/signout", status_code=status.HTTP_204_NO_CONTENT)
    async def signout(request: Request, response: Response) -> None:
        handle = _session_handle(request)
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
        current = await context(request, require_workspace=False)
        return _session_response(current.session, current.membership)

    @router.get("/context", response_model=SessionResponse)
    async def current_context(request: Request) -> SessionResponse:
        current = await context(request, require_workspace=True)
        return _session_response(current.session, current.membership)

    @router.put("/workspace", response_model=SessionResponse)
    async def select_workspace(
        payload: WorkspaceSelectionRequest, request: Request
    ) -> SessionResponse:
        current = await context(request, require_workspace=False)
        try:
            membership = await membership_resolver.resolve(
                current.session.user_id, payload.workspace_id
            )
        except MembershipResolutionUnavailableError:
            raise HTTPException(
                status_code=503,
                detail="Workspace authority is unavailable.",
            ) from None
        if membership is None:
            raise _workspace_unavailable()
        updated = await session_store.select_workspace(
            current.session.handle, payload.workspace_id
        )
        if updated is None:
            raise _authentication_required()
        return _session_response(updated, membership)

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
    )
    apply_bff_session_cookie(
        response, BffSessionCookie(session.handle, tokens.expires_in_seconds)
    )
    return session


async def _resolve_selected(
    session: BffSession,
    resolver: MembershipResolver,
    store: BffSessionStore,
) -> Membership | None:
    if session.active_workspace_id is None:
        return None
    membership = await resolver.resolve(session.user_id, session.active_workspace_id)
    if membership is None:
        await store.select_workspace(session.handle, None)
    return membership


def _session_handle(request: Request) -> BffSessionHandle:
    value = request.cookies.get(SESSION_COOKIE_NAME)
    if not value:
        raise _authentication_required()
    return BffSessionHandle(value)


def _session_response(
    session: BffSession, membership: Membership | None
) -> SessionResponse:
    workspace = None
    if membership is not None:
        workspace = WorkspaceResponse(
            id=membership.workspace_id, role=membership.role.value
        )
    return SessionResponse(
        user_id=session.user_id, email=session.email, workspace=workspace
    )


def _authentication_required() -> HTTPException:
    return HTTPException(status_code=401, detail="Authentication required.")


def _workspace_unavailable() -> HTTPException:
    return HTTPException(status_code=403, detail="Workspace is unavailable.")
