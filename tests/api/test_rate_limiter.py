"""Regression tests for rate-limit enforcement and stale-window eviction."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.rate_limiter import RateLimitMiddleware


def _app(limit: int = 2) -> FastAPI:
    app = FastAPI()

    @app.get("/api/thing")
    async def thing() -> dict[str, bool]:
        return {"ok": True}

    app.add_middleware(RateLimitMiddleware, general_rpm=limit)
    return app


def _middleware(app: FastAPI) -> RateLimitMiddleware:
    node = app.middleware_stack
    while node is not None:
        if isinstance(node, RateLimitMiddleware):
            return node
        node = getattr(node, "app", None)
    raise AssertionError("RateLimitMiddleware was not constructed")


def test_limit_is_enforced() -> None:
    client = TestClient(_app())
    assert client.get("/api/thing").status_code == 200
    assert client.get("/api/thing").status_code == 200
    response = client.get("/api/thing")
    assert response.status_code == 429
    assert "Retry-After" in response.headers


def test_idle_entry_is_evicted_during_sweep() -> None:
    app = _app(5)
    client = TestClient(app)
    assert client.get("/api/thing").status_code == 200
    limiter = _middleware(app)
    stale_key = ("198.51.100.42", "general")
    limiter._window[stale_key] = [limiter._last_sweep - 1_000]
    limiter._last_sweep -= 1_000
    assert client.get("/api/thing").status_code == 200
    assert stale_key not in limiter._window


def test_rejected_request_does_not_create_an_empty_window() -> None:
    app = _app(1)
    client = TestClient(app)
    assert client.get("/api/thing").status_code == 200
    assert client.get("/api/thing").status_code == 429
    assert all(values for values in _middleware(app)._window.values())
