"""Body-size limiting middleware.

EDGE-H01: Reject oversized requests based on the ``Content-Length`` header
BEFORE Starlette reads the body into memory.

Environment variables:
    RAG_STUDIO_MAX_CHAT_BODY_BYTES: Chat endpoint limit (default 102400 = 100 KB)
    RAG_STUDIO_MAX_UPLOAD_BODY_BYTES: Upload endpoint limit (default 52428800 = 50 MB)
"""

from __future__ import annotations

import logging
import os
from typing import Awaitable, Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_CHAT_LIMIT: int = 100 * 1024  # 100 KB
_DEFAULT_UPLOAD_LIMIT: int = 50 * 1024 * 1024  # 50 MB

_CHAT_PREFIX: str = "/api/chat/"
_UPLOAD_PREFIX: str = "/api/ingest/upload"

_SAFE_METHODS: frozenset[str] = frozenset({"GET", "HEAD", "DELETE", "OPTIONS"})


def _env_bytes(name: str, default: int) -> int:
    """Read a byte-count environment variable, falling back to *default*.

    Args:
        name: Environment variable name.
        default: Fallback value in bytes.

    Returns:
        The parsed byte limit.
    """
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning("Invalid value for %s=%r, using default %d.", name, raw, default)
        return default


class BodySizeLimitMiddleware(BaseHTTPMiddleware):
    """Reject requests whose ``Content-Length`` exceeds a configurable limit.

    Two tiers are supported, each configurable via an environment variable:

    * Chat endpoints (``/api/chat/``) → ``RAG_STUDIO_MAX_CHAT_BODY_BYTES``
    * Upload endpoint (``/api/ingest/upload``) → ``RAG_STUDIO_MAX_UPLOAD_BODY_BYTES``

    All other paths pass through without any limit check.
    ``GET``, ``HEAD``, ``DELETE``, and ``OPTIONS`` are always allowed
    (they carry no request body).

    When ``Content-Length`` exceeds the limit the middleware returns a
    ``413 Payload Too Large`` JSON response.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        chat_limit: int | None = None,
        upload_limit: int | None = None,
    ) -> None:
        """Initialise the middleware with configurable per-tier limits.

        Args:
            app: The inner ASGI application.
            chat_limit: Override for chat body limit (default from env or 100 KB).
            upload_limit: Override for upload body limit (default from env or 50 MB).
        """
        super().__init__(app)
        self._chat_limit: int = (
            chat_limit
            if chat_limit is not None
            else _env_bytes("RAG_STUDIO_MAX_CHAT_BODY_BYTES", _DEFAULT_CHAT_LIMIT)
        )
        self._upload_limit: int = (
            upload_limit
            if upload_limit is not None
            else _env_bytes("RAG_STUDIO_MAX_UPLOAD_BODY_BYTES", _DEFAULT_UPLOAD_LIMIT)
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_content_length(request: Request) -> int | None:
        """Parse the ``Content-Length`` header as an integer.

        Args:
            request: The incoming HTTP request.

        Returns:
            The content length in bytes, or ``None`` if the header is
            missing or unparseable.
        """
        raw = request.headers.get("Content-Length")
        if raw is None:
            return None
        try:
            return int(raw)
        except ValueError:
            return None

    def _get_limit(self, path: str) -> int | None:
        """Return the byte limit for *path*, or ``None`` for unlimited."""
        if path.startswith(_CHAT_PREFIX):
            return self._chat_limit
        if path.startswith(_UPLOAD_PREFIX):
            return self._upload_limit
        return None

    # ------------------------------------------------------------------
    # Middleware dispatch
    # ------------------------------------------------------------------

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """Entry-point for every incoming HTTP request.

        Safe methods (GET, HEAD, DELETE, OPTIONS) pass through immediately.
        For other methods the ``Content-Length`` header is compared against
        the path-specific limit; oversized requests receive a 413 response.
        """
        # Skip safe methods — they carry no body.
        if request.method in _SAFE_METHODS:
            return await call_next(request)

        path: str = request.url.path
        limit: int | None = self._get_limit(path)

        # No limit configured for this path — pass through.
        if limit is None:
            return await call_next(request)

        content_length: int | None = self._get_content_length(request)

        # Missing or unparseable Content-Length — allow through (we
        # cannot determine the size beforehand).
        if content_length is None:
            content_length = len(await request.body())

        if content_length > limit:
            logger.warning(
                "Body size limit exceeded: path=%s content_length=%d limit=%d",
                path,
                content_length,
                limit,
            )
            return Response(
                content='{"detail":"Payload Too Large"}',
                status_code=413,
                media_type="application/json",
            )

        return await call_next(request)
