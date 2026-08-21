"""Cookie and CSRF primitives for the Stage 3 BFF boundary."""

from __future__ import annotations

import os
import secrets
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final, NewType
from urllib.parse import urlsplit

from fastapi import Request
from fastapi.responses import JSONResponse, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.types import ASGIApp

BffSessionHandle = NewType("BffSessionHandle", str)

SESSION_COOKIE_NAME: Final = "__Host-ragstudio-session"
CSRF_COOKIE_NAME: Final = "__Host-ragstudio-csrf"
DEVELOPMENT_SESSION_COOKIE_NAME: Final = "ragstudio-development-session"
DEVELOPMENT_CSRF_COOKIE_NAME: Final = "ragstudio-development-csrf"
CSRF_HEADER_NAME: Final = "X-CSRF-Token"
_SAAS_API_ROOT: Final = "/api/saas"
_UNSAFE_METHODS: Final = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_COOKIE_SECURE_ENV: Final = "RAG_STUDIO_COOKIE_SECURE"
_TRUSTED_ORIGINS_ENV: Final = "RAG_STUDIO_CORS_ORIGINS"
_LOOPBACK_HOSTS: Final = frozenset({"localhost", "127.0.0.1", "::1"})


class CookieTransportConfigurationError(ValueError):
    """Reject an unsafe cookie transport configuration without echoing inputs."""


@dataclass(frozen=True, slots=True)
class CookieTransportPolicy:
    """Cookie attributes and names bound to one validated transport mode."""

    secure: bool

    @property
    def session_cookie_name(self) -> str:
        """Return the host-prefixed production or loopback-only development name."""
        return SESSION_COOKIE_NAME if self.secure else DEVELOPMENT_SESSION_COOKIE_NAME

    @property
    def csrf_cookie_name(self) -> str:
        """Return the host-prefixed production or loopback-only development name."""
        return CSRF_COOKIE_NAME if self.secure else DEVELOPMENT_CSRF_COOKIE_NAME


def load_cookie_transport_policy(
    trusted_origins: Sequence[str] | None = None,
) -> CookieTransportPolicy:
    """Parse an explicit fail-closed cookie policy from the process environment."""
    configured = os.getenv(_COOKIE_SECURE_ENV, "true").strip().lower()
    if configured not in {"true", "false"}:
        raise CookieTransportConfigurationError(
            "RAG_STUDIO_COOKIE_SECURE must be either 'true' or 'false'."
        )
    secure = configured == "true"
    if secure:
        return CookieTransportPolicy(secure=True)
    origins = _configured_origins(trusted_origins)
    if not origins or any(not _is_loopback_http_origin(item) for item in origins):
        raise CookieTransportConfigurationError(
            "Non-secure cookies require loopback HTTP trusted origins."
        )
    return CookieTransportPolicy(secure=False)


def _configured_origins(trusted_origins: Sequence[str] | None) -> tuple[str, ...]:
    if trusted_origins is not None:
        return tuple(trusted_origins)
    configured = os.getenv(_TRUSTED_ORIGINS_ENV, "")
    return tuple(item.strip() for item in configured.split(",") if item.strip())


def _is_loopback_http_origin(origin: str) -> bool:
    try:
        parsed = urlsplit(origin)
        port_is_valid = parsed.port is None or parsed.port >= 0
    except ValueError:
        return False
    return (
        parsed.scheme == "http"
        and port_is_valid
        and parsed.hostname in _LOOPBACK_HOSTS
        and parsed.username is None
        and parsed.password is None
        and parsed.path in {"", "/"}
        and not parsed.query
        and not parsed.fragment
    )


@dataclass(frozen=True, slots=True)
class BffSessionCookie:
    """Opaque server-side session handle and its bounded browser lifetime."""

    handle: BffSessionHandle
    max_age_seconds: int


def apply_bff_session_cookie(response: Response, cookie: BffSessionCookie) -> None:
    """Apply the non-browser-readable BFF session cookie contract."""
    policy = load_cookie_transport_policy()
    response.set_cookie(
        key=policy.session_cookie_name,
        value=cookie.handle,
        max_age=cookie.max_age_seconds,
        path="/",
        secure=policy.secure,
        httponly=True,
        samesite="lax",
    )


def apply_csrf_cookie(response: Response, token: str, max_age_seconds: int) -> None:
    """Apply the browser-readable double-submit CSRF cookie."""
    policy = load_cookie_transport_policy()
    response.set_cookie(
        key=policy.csrf_cookie_name,
        value=token,
        max_age=max_age_seconds,
        path="/",
        secure=policy.secure,
        httponly=False,
        samesite="lax",
    )


def clear_bff_cookies(response: Response) -> None:
    """Expire both BFF cookies without exposing their prior values."""
    policy = load_cookie_transport_policy()
    response.delete_cookie(
        policy.session_cookie_name,
        path="/",
        secure=policy.secure,
        httponly=True,
        samesite="lax",
    )
    response.delete_cookie(
        policy.csrf_cookie_name,
        path="/",
        secure=policy.secure,
        httponly=False,
        samesite="lax",
    )


class SaasCsrfMiddleware(BaseHTTPMiddleware):
    """Reject unsafe SaaS requests without CSRF and trusted-Origin proof."""

    def __init__(
        self,
        app: ASGIApp,
        trusted_origins: Sequence[str] = (),
        protected_roots: Sequence[str] = (_SAAS_API_ROOT,),
    ) -> None:
        super().__init__(app)
        self._cookie_policy = load_cookie_transport_policy(trusted_origins)
        self._trusted_origins = frozenset(
            origin.rstrip("/") for origin in trusted_origins
        )
        self._protected_roots = frozenset(root.rstrip("/") for root in protected_roots)

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        """Enforce CSRF before an unsafe SaaS request reaches route resolution."""
        is_protected_path = any(
            request.url.path == root or request.url.path.startswith(f"{root}/")
            for root in self._protected_roots
        )
        if is_protected_path and request.method in _UNSAFE_METHODS:
            cookie_token = request.cookies.get(self._cookie_policy.csrf_cookie_name, "")
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
            origin = request.headers.get("Origin")
            same_origin = f"{request.url.scheme}://{request.url.netloc}"
            if origin and origin.rstrip("/") not in (
                self._trusted_origins | {same_origin}
            ):
                return JSONResponse(
                    status_code=403,
                    content={"detail": "Origin validation failed."},
                )
        return await call_next(request)
