"""In-memory sliding-window rate limiting middleware.

SEC-H04: Lightweight rate limiter using only Python stdlib + Starlette.
Tracks request timestamps per client IP in a dict, prunes stale entries
on each request, and returns HTTP 429 when limits are exceeded.

Environment variables:
    RAG_STUDIO_CHAT_RPM_LIMIT: Chat endpoint limit (default 30)
    RAG_STUDIO_UPLOAD_RPM_LIMIT: Upload endpoint limit (default 10)
    RAG_STUDIO_GENERAL_RPM_LIMIT: All other /api/ endpoints (default 60)
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Awaitable, Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_WINDOW_SECONDS: float = 60.0  # Sliding window duration

# Path prefixes used to determine which rate-limit tier applies.
_CHAT_PREFIX: str = "/api/chat/"
_UPLOAD_PREFIX: str = "/api/ingest/upload"
_HEALTH_PREFIX: str = "/api/health/"
_API_PREFIX: str = "/api/"


def _env_int(name: str, default: int) -> int:
    """Read an integer environment variable, falling back to *default*."""
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        logger.warning("Invalid value for %s, using default %d.", name, default)
        return default


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Starlette middleware that enforces per-IP sliding-window rate limits.

    Three rate-limit tiers are supported, each configurable via an
    environment variable:

    * Chat endpoints (``/api/chat/``) → ``RAG_STUDIO_CHAT_RPM_LIMIT``
    * Upload endpoint (``/api/ingest/upload``) → ``RAG_STUDIO_UPLOAD_RPM_LIMIT``
    * All other ``/api/`` paths → ``RAG_STUDIO_GENERAL_RPM_LIMIT``

    When a client exceeds its limit the middleware returns a ``429 Too Many
    Requests`` JSON response with a ``Retry-After`` header.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        chat_rpm: int | None = None,
        upload_rpm: int | None = None,
        general_rpm: int | None = None,
    ) -> None:
        """Initialise the middleware with configurable per-tier limits.

        Args:
            app: The inner ASGI application.
            chat_rpm: Override for chat RPM (default from env or 30).
            upload_rpm: Override for upload RPM (default from env or 10).
            general_rpm: Override for general RPM (default from env or 60).
        """
        super().__init__(app)
        self._chat_rpm: int = (
            chat_rpm
            if chat_rpm is not None
            else _env_int("RAG_STUDIO_CHAT_RPM_LIMIT", 30)
        )
        self._upload_rpm: int = (
            upload_rpm
            if upload_rpm is not None
            else _env_int("RAG_STUDIO_UPLOAD_RPM_LIMIT", 10)
        )
        self._general_rpm: int = (
            general_rpm
            if general_rpm is not None
            else _env_int("RAG_STUDIO_GENERAL_RPM_LIMIT", 60)
        )
        self._window: dict[tuple[str, str], list[float]] = {}
        self._lock: asyncio.Lock = asyncio.Lock()
        self._last_sweep: float = time.monotonic()

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    def _get_client_id(self, request: Request) -> str:
        """Extract the client identifier from the request.

        Uses ``request.client.host`` (the connecting IP).  Falls back to
        ``"unknown"`` when the client information is unavailable
        (e.g. behind certain proxy configurations).
        """
        if request.client is not None and request.client.host:
            return request.client.host
        return "unknown"

    def _get_limit(self, path: str) -> int:
        """Return the RPM limit for the given request *path*."""
        # Health endpoints are polled by the UI and Docker — never rate-limit.
        if path.startswith(_HEALTH_PREFIX):
            return 1_000_000
        if path.startswith(_CHAT_PREFIX):
            return self._chat_rpm
        if path.startswith(_UPLOAD_PREFIX):
            return self._upload_rpm
        if path.startswith(_API_PREFIX):
            return self._general_rpm
        # Non-API paths are not rate-limited (return a very high value).
        return 1_000_000

    def _get_tier(self, path: str) -> str | None:
        """Return the rate-limit tier for *path*, if it is limited."""
        if path.startswith(_CHAT_PREFIX):
            return "chat"
        if path.startswith(_UPLOAD_PREFIX):
            return "upload"
        if path.startswith(_API_PREFIX) and not path.startswith(_HEALTH_PREFIX):
            return "general"
        return None

    def _sweep_stale_clients(self, now: float) -> None:
        """Evict client entries whose timestamps are entirely stale.

        Must be called while holding ``self._lock``. Removes any client
        whose newest timestamp is older than the sliding window, preventing
        unbounded growth of ``self._window`` from one-off client IPs.
        """
        cutoff: float = now - _WINDOW_SECONDS
        stale_clients = [
            client_id
            for client_id, timestamps in self._window.items()
            if not timestamps or timestamps[-1] <= cutoff
        ]
        for client_id in stale_clients:
            del self._window[client_id]
        self._last_sweep = now

    # ------------------------------------------------------------------
    # Middleware dispatch
    # ------------------------------------------------------------------

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """Entry-point for every incoming HTTP request.

        Rate-limited paths are checked against the sliding window; all
        other paths pass through without tracking.
        """
        path: str = request.url.path
        limit: int = self._get_limit(path)
        tier = self._get_tier(path)

        # Paths outside /api/ are not rate-limited.
        if limit >= 1_000_000 or tier is None:
            return await call_next(request)

        client_key = (self._get_client_id(request), tier)
        now: float = time.monotonic()

        async with self._lock:
            if now - self._last_sweep > _WINDOW_SECONDS:
                self._sweep_stale_clients(now)

            timestamps: list[float] = self._window.get(client_key, [])
            # Prune entries outside the sliding window.
            cutoff: float = now - _WINDOW_SECONDS
            timestamps = [t for t in timestamps if t > cutoff]

            if len(timestamps) >= limit:
                # The *oldest* timestamp tells us when a slot opens.
                oldest: float = timestamps[0] if timestamps else now
                retry_after: int = max(1, int(oldest + _WINDOW_SECONDS - now))
                logger.warning(
                    "Rate limit hit: client=%s path=%s limit=%d rpm",
                    client_key[0],
                    path,
                    limit,
                )
                if timestamps:
                    self._window[client_key] = timestamps
                else:
                    self._window.pop(client_key, None)
                return Response(
                    content='{"detail":"Too Many Requests"}',
                    status_code=429,
                    media_type="application/json",
                    headers={"Retry-After": str(retry_after)},
                )

            timestamps.append(now)
            self._window[client_key] = timestamps

        return await call_next(request)
