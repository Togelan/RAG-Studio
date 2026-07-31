"""Authentication middleware for RAG-Studio API endpoints.

Provides:
- Shared-secret token auth via RAG_STUDIO_AUTH_TOKEN env var
- Middleware that checks Authorization: Bearer <token> on /api/* paths
- FastAPI dependency for per-route auth enforcement
- Public path exceptions for health checks and static files

When RAG_STUDIO_AUTH_TOKEN is not set, authentication is disabled
(backward-compatible for local development).
"""

from __future__ import annotations

import logging
import os
import secrets
from typing import Awaitable, Callable

from fastapi import HTTPException, Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)

# ============================================================
# Configuration
# ============================================================

# Public paths that never require authentication
_PUBLIC_PATH_PREFIXES: tuple[str, ...] = (
    "/health",
    "/api/health",
    "/static/",
)

# API paths that require authentication (when token is set)
_PROTECTED_PATH_PREFIX: str = "/api/"

# Auth header name and scheme
_AUTH_HEADER: str = "Authorization"
_AUTH_SCHEME: str = "Bearer "


def _get_configured_token() -> str | None:
    """Read the auth token from the environment at call time.

    Using a function (not a module-level constant) so that tests
    can monkeypatch the environment after import.

    Returns:
        The configured token, or None if not set.
    """
    return os.getenv("RAG_STUDIO_AUTH_TOKEN")


def is_auth_enabled() -> bool:
    """Check if authentication is enabled.

    Returns:
        True if RAG_STUDIO_AUTH_TOKEN is set and non-empty.
    """
    return bool(_get_configured_token())


def get_auth_token() -> str | None:
    """Return the configured auth token, or None if auth is disabled.

    Returns:
        The configured token string, or None.
    """
    return _get_configured_token()


def verify_token(token: str | None) -> bool:
    """Verify a Bearer token against the configured auth token.

    Args:
        token: The token extracted from the Authorization header.

    Returns:
        True if the token matches, False otherwise.
    """
    configured = _get_configured_token()
    if not configured:
        return True
    if not token:
        return False
    # Use constant-time comparison to avoid timing attacks
    return secrets.compare_digest(token, configured)


def _extract_bearer_token(request: Request) -> str | None:
    """Extract the Bearer token from the Authorization header.

    Args:
        request: The incoming FastAPI/Starlette request.

    Returns:
        The token string or None if not present/invalid format.
    """
    header = request.headers.get(_AUTH_HEADER, "")
    if header.startswith(_AUTH_SCHEME):
        return header[len(_AUTH_SCHEME) :].strip()
    # Also support raw token (no "Bearer " prefix) for simpler clients
    if header and not header.startswith(_AUTH_SCHEME):
        return header.strip()
    return None


def _is_public_path(path: str) -> bool:
    """Check if the request path is exempt from authentication.

    Args:
        path: The request URL path.

    Returns:
        True if the path is public.
    """
    return path.startswith(_PUBLIC_PATH_PREFIXES)


def _is_api_path(path: str) -> bool:
    """Check if the request path is a protected API path.

    Args:
        path: The request URL path.

    Returns:
        True if the path starts with /api/ (but not /api/health).
    """
    if not path.startswith(_PROTECTED_PATH_PREFIX):
        return False
    return not _is_public_path(path)


class AuthMiddleware(BaseHTTPMiddleware):
    """FastAPI middleware that checks Bearer token on protected API routes.

    Skips authentication for:
        - /health, /api/health (Docker HEALTHCHECK)
        - /static/* (CSS, JS, images)
        - Non-API paths (/, /settings, /chat HTML pages)

    When RAG_STUDIO_AUTH_TOKEN is not set, all requests pass through.
    """

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        # Skip if auth is disabled or path is public/non-API
        if (
            request.method == "OPTIONS"
            or not is_auth_enabled()
            or not _is_api_path(request.url.path)
        ):
            return await call_next(request)

        token = _extract_bearer_token(request)
        if not verify_token(token):
            logger.warning(
                "Auth failed for %s from %s",
                request.url.path,
                request.client.host if request.client else "unknown",
            )
            return JSONResponse(
                status_code=401,
                content={
                    "detail": "Authentication required. "
                    "Provide a valid token via Authorization: Bearer <token> header.",
                },
            )

        return await call_next(request)


# ============================================================
# FastAPI Dependency (for per-route enforcement)
# ============================================================


async def require_auth(request: Request) -> None:
    """FastAPI dependency that enforces authentication on a specific route.

    Use as a route dependency when you need auth but the middleware
    doesn't cover the path (e.g., non-/api routes that need protection):

        @router.get("/protected")
        async def protected(auth: None = Depends(require_auth)): ...

    Raises:
        HTTPException: 401 if authentication fails.
    """
    if not is_auth_enabled():
        return

    token = _extract_bearer_token(request)
    if not verify_token(token):
        raise HTTPException(
            status_code=401,
            detail="Authentication required.",
        )
