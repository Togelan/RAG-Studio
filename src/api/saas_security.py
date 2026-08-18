"""Cookie and CSRF primitives for the Stage 3 BFF boundary."""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from typing import Final, NewType

from fastapi import Request
from fastapi.responses import JSONResponse, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

BffSessionHandle = NewType("BffSessionHandle", str)

SESSION_COOKIE_NAME: Final = "__Host-ragstudio-session"
CSRF_COOKIE_NAME: Final = "__Host-ragstudio-csrf"
CSRF_HEADER_NAME: Final = "X-CSRF-Token"
_SAAS_API_ROOT: Final = "/api/saas"
_UNSAFE_METHODS: Final = frozenset({"POST", "PUT", "PATCH", "DELETE"})


@dataclass(frozen=True, slots=True)
class BffSessionCookie:
    """Opaque server-side session handle and its bounded browser lifetime."""

    handle: BffSessionHandle
    max_age_seconds: int


def apply_bff_session_cookie(response: Response, cookie: BffSessionCookie) -> None:
    """Apply the non-browser-readable BFF session cookie contract."""
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=cookie.handle,
        max_age=cookie.max_age_seconds,
        path="/",
        secure=True,
        httponly=True,
        samesite="lax",
    )


def apply_csrf_cookie(response: Response, token: str, max_age_seconds: int) -> None:
    """Apply the browser-readable double-submit CSRF cookie."""
    response.set_cookie(
        key=CSRF_COOKIE_NAME,
        value=token,
        max_age=max_age_seconds,
        path="/",
        secure=True,
        httponly=False,
        samesite="lax",
    )


def clear_bff_cookies(response: Response) -> None:
    """Expire both BFF cookies without exposing their prior values."""
    response.delete_cookie(
        SESSION_COOKIE_NAME, path="/", secure=True, httponly=True, samesite="lax"
    )
    response.delete_cookie(
        CSRF_COOKIE_NAME, path="/", secure=True, httponly=False, samesite="lax"
    )


class SaasCsrfMiddleware(BaseHTTPMiddleware):
    """Reject unsafe SaaS API requests without double-submit CSRF proof."""

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        """Enforce CSRF before an unsafe SaaS request reaches route resolution."""
        is_saas_path = (
            request.url.path == _SAAS_API_ROOT
            or request.url.path.startswith(f"{_SAAS_API_ROOT}/")
        )
        if is_saas_path and request.method in _UNSAFE_METHODS:
            cookie_token = request.cookies.get(CSRF_COOKIE_NAME, "")
            header_token = request.headers.get(CSRF_HEADER_NAME, "")
            if (
                not cookie_token
                or not header_token
                or not secrets.compare_digest(cookie_token, header_token)
            ):
                return JSONResponse(
                    status_code=403,
                    content={"detail": "CSRF validation failed."},
                )
        return await call_next(request)
