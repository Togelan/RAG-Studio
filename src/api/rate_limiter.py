"""In-memory, per-IP sliding-window rate limiting with bounded state."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

logger = logging.getLogger(__name__)

_WINDOW_SECONDS = 60.0
_CHAT_PREFIX = "/api/chat/"
_UPLOAD_PREFIX = "/api/ingest/upload"
_HEALTH_PREFIX = "/api/health/"
_API_PREFIX = "/api/"


def _env_int(name: str, default: int) -> int:
    """Return an integer setting or the safe default for invalid values."""
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        logger.warning("Invalid value for %s; using default %d.", name, default)
        return default


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Apply configurable API request limits and evict inactive IP windows."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        chat_rpm: int | None = None,
        upload_rpm: int | None = None,
        general_rpm: int | None = None,
    ) -> None:
        super().__init__(app)
        self._chat_rpm = chat_rpm if chat_rpm is not None else _env_int("RAG_STUDIO_CHAT_RPM_LIMIT", 30)
        self._upload_rpm = upload_rpm if upload_rpm is not None else _env_int("RAG_STUDIO_UPLOAD_RPM_LIMIT", 10)
        self._general_rpm = general_rpm if general_rpm is not None else _env_int("RAG_STUDIO_GENERAL_RPM_LIMIT", 60)
        self._window: dict[tuple[str, str], list[float]] = {}
        self._lock = asyncio.Lock()
        self._last_sweep = time.monotonic()

    @staticmethod
    def _client_id(request: Request) -> str:
        return request.client.host if request.client and request.client.host else "unknown"

    def _tier_and_limit(self, path: str) -> tuple[str | None, int]:
        if path.startswith(_HEALTH_PREFIX):
            return None, 0
        if path.startswith(_CHAT_PREFIX):
            return "chat", self._chat_rpm
        if path.startswith(_UPLOAD_PREFIX):
            return "upload", self._upload_rpm
        if path.startswith(_API_PREFIX):
            return "general", self._general_rpm
        return None, 0

    def _sweep_stale_clients(self, now: float) -> None:
        """Delete windows inactive for a complete limit window; lock is held."""
        cutoff = now - _WINDOW_SECONDS
        for key in [key for key, values in self._window.items() if not values or values[-1] <= cutoff]:
            del self._window[key]
        self._last_sweep = now

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        tier, limit = self._tier_and_limit(request.url.path)
        if tier is None:
            return await call_next(request)

        now = time.monotonic()
        client_key = (self._client_id(request), tier)
        async with self._lock:
            if now - self._last_sweep >= _WINDOW_SECONDS:
                self._sweep_stale_clients(now)

            cutoff = now - _WINDOW_SECONDS
            timestamps = [timestamp for timestamp in self._window.get(client_key, []) if timestamp > cutoff]
            if len(timestamps) >= limit:
                self._window[client_key] = timestamps
                retry_after = max(1, int(timestamps[0] + _WINDOW_SECONDS - now))
                return Response(
                    content='{"detail":"Too Many Requests"}',
                    status_code=429,
                    media_type="application/json",
                    headers={"Retry-After": str(retry_after)},
                )
            timestamps.append(now)
            self._window[client_key] = timestamps

        return await call_next(request)
