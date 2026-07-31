"""Unit tests for RateLimitMiddleware (R2-H02: stale client eviction)."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.responses import Response

from src.api.rate_limiter import RateLimitMiddleware


def _build_app(general_rpm: int = 2) -> FastAPI:
    """Create a minimal FastAPI app with RateLimitMiddleware."""
    app = FastAPI()

    @app.get("/api/thing")
    async def thing() -> Response:
        return Response(content='{"ok":true}', media_type="application/json")

    app.add_middleware(RateLimitMiddleware, general_rpm=general_rpm)
    return app


def _find_rate_limiter(app: FastAPI) -> RateLimitMiddleware | None:
    """Locate the constructed RateLimitMiddleware instance via the app's stack.

    Note: `app.middleware_stack` is only built lazily on the first request,
    so callers must trigger a request before invoking this helper.
    """
    rate_limiter = None
    node = app.middleware_stack
    while node is not None:
        if isinstance(node, RateLimitMiddleware):
            rate_limiter = node
            break
        node = getattr(node, "app", None)
    return rate_limiter


class TestActiveLimiting:
    """AC: Requests over the limit still receive 429 responses."""

    def test_limit_enforced(self) -> None:
        app = _build_app(general_rpm=2)
        client = TestClient(app)

        assert client.get("/api/thing").status_code == 200
        assert client.get("/api/thing").status_code == 200
        response = client.get("/api/thing")
        assert response.status_code == 429
        assert "Retry-After" in response.headers


class TestStaleClientEviction:
    """AC: Stale client IP entries are evicted from self._window."""

    def test_stale_entry_removed_on_sweep(self) -> None:
        app = _build_app(general_rpm=5)
        client = TestClient(app)

        response = client.get("/api/thing")
        assert response.status_code == 200

        rate_limiter = _find_rate_limiter(app)
        assert rate_limiter is not None
        assert len(rate_limiter._window) == 1

        # Simulate the window and last sweep both being in the past.
        client_id = next(iter(rate_limiter._window))
        rate_limiter._window[client_id] = [rate_limiter._last_sweep - 1000.0]
        rate_limiter._last_sweep -= 1000.0

        response = client.get("/api/thing")
        assert response.status_code == 200
        # Sweep should have evicted the stale entry and inserted a fresh one.
        assert len(rate_limiter._window) == 1
        assert rate_limiter._window[client_id][0] > rate_limiter._last_sweep - 1.0

    def test_rejected_request_does_not_leave_empty_list(self) -> None:
        app = _build_app(general_rpm=1)
        client = TestClient(app)

        assert client.get("/api/thing").status_code == 200
        assert client.get("/api/thing").status_code == 429

        rate_limiter = _find_rate_limiter(app)
        assert rate_limiter is not None

        client_id = next(iter(rate_limiter._window))
        assert rate_limiter._window[client_id] != []
