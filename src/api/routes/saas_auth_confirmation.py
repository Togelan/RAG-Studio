"""Bounded public email-confirmation handoff to the local Auth authority."""

from __future__ import annotations

from typing import Protocol

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse


class ConfirmationRejectedError(PermissionError):
    """Raised when GoTrue rejects an expired, malformed, or used email link."""


class ConfirmationUnavailableError(RuntimeError):
    """Raised when the local identity authority cannot answer in time."""


class ConfirmationVerifier(Protocol):
    """Verify only the opaque query from a public GoTrue email link."""

    async def verify(self, query: str) -> None: ...


class SupabaseConfirmationVerifier:
    """Forward email-link verification to the private GoTrue service only."""

    def __init__(self, base_url: str) -> None:
        self._verify_url = f"{base_url.rstrip('/')}/verify"
        self._timeout = httpx.Timeout(connect=5.0, read=10.0, write=10.0, pool=5.0)

    async def verify(self, query: str) -> None:
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout,
                follow_redirects=False,
                trust_env=False,
            ) as client:
                response = await client.get(self._verify_url, params=httpx.QueryParams(query))
        except httpx.ConnectError, httpx.TimeoutException, httpx.RemoteProtocolError:
            raise ConfirmationUnavailableError from None
        if 300 <= response.status_code < 400:
            return
        if 400 <= response.status_code < 500:
            raise ConfirmationRejectedError from None
        raise ConfirmationUnavailableError


def create_saas_auth_confirmation_router(
    *, completion_url: str, verifier: ConfirmationVerifier
) -> APIRouter:
    """Create the same-origin confirmation endpoint without exposing Auth internals."""
    router = APIRouter(tags=["saas-auth"])

    @router.get("/auth/v1/verify", include_in_schema=False)
    async def confirm_email(request: Request) -> RedirectResponse:
        query = request.url.query
        if not request.query_params.get("token") or not request.query_params.get("type"):
            raise HTTPException(status_code=400, detail="Confirmation link is invalid.")
        try:
            await verifier.verify(query)
        except ConfirmationRejectedError:
            raise HTTPException(status_code=400, detail="Confirmation link is invalid.") from None
        except ConfirmationUnavailableError:
            raise HTTPException(
                status_code=503, detail="Identity service is unavailable."
            ) from None
        return RedirectResponse(completion_url, status_code=303)

    return router
