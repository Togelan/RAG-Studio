"""Tests for the least-privilege CORS configuration."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.api.main import create_app


@pytest.fixture(name="client")
def fixture_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """Create an app with the default, local-only CORS configuration."""
    monkeypatch.delenv("RAG_STUDIO_CORS_ORIGINS", raising=False)
    return TestClient(create_app())


def test_default_cors_allows_local_origin_and_required_request_headers(
    client: TestClient,
) -> None:
    """The documented local origin may make API requests with needed headers."""
    response = client.options(
        "/api/chat/send",
        headers={
            "Origin": "http://localhost:8000",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Content-Type, X-API-Key",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:8000"
    assert (
        response.headers["access-control-allow-methods"]
        == "GET, POST, PATCH, DELETE"
    )
    allowed_headers = response.headers["access-control-allow-headers"].lower()
    assert "content-type" in allowed_headers
    assert "x-api-key" in allowed_headers
    assert "authorization" not in allowed_headers
    assert "access-control-allow-credentials" not in response.headers


def test_cors_rejects_unlisted_origin_method_and_header(client: TestClient) -> None:
    """Origins, HTTP methods, and request headers are all explicitly scoped."""
    blocked_origin = client.options(
        "/api/chat/send",
        headers={
            "Origin": "https://untrusted.example",
            "Access-Control-Request-Method": "POST",
        },
    )
    blocked_method = client.options(
        "/api/chat/send",
        headers={
            "Origin": "http://localhost:8000",
            "Access-Control-Request-Method": "PUT",
        },
    )
    blocked_header = client.options(
        "/api/chat/send",
        headers={
            "Origin": "http://localhost:8000",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Authorization",
        },
    )

    assert blocked_origin.status_code == 400
    assert blocked_method.status_code == 400
    assert blocked_header.status_code == 400


def test_cors_uses_explicit_configured_origin(monkeypatch: pytest.MonkeyPatch) -> None:
    """A deployment can replace, rather than extend, the local default list."""
    monkeypatch.setenv("RAG_STUDIO_CORS_ORIGINS", "https://rag.example.com")
    client = TestClient(create_app())

    response = client.options(
        "/api/chat/send",
        headers={
            "Origin": "https://rag.example.com",
            "Access-Control-Request-Method": "POST",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://rag.example.com"


@pytest.mark.parametrize("origins", ["*", "https://rag.example.com/path", "http://"])
def test_cors_rejects_unsafe_or_invalid_origin_config(
    monkeypatch: pytest.MonkeyPatch, origins: str
) -> None:
    """Invalid configuration must not silently expand allowed origins."""
    monkeypatch.setenv("RAG_STUDIO_CORS_ORIGINS", origins)

    with pytest.raises(ValueError):
        create_app()


def test_empty_cors_origin_config_disables_cross_origin_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An explicit empty configuration is a safe deny-all setting."""
    monkeypatch.setenv("RAG_STUDIO_CORS_ORIGINS", "")
    client = TestClient(create_app())

    response = client.options(
        "/api/chat/send",
        headers={
            "Origin": "http://localhost:8000",
            "Access-Control-Request-Method": "POST",
        },
    )

    assert response.status_code == 400
