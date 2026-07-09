"""Tests for settings API endpoints.

Covers:
- POST /api/settings/validate-key (valid + invalid)
- GET /api/settings (masked API key)
- POST /api/settings (save settings)
"""

from __future__ import annotations

from collections.abc import Generator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.api.dependencies import get_qdrant_client

# ============================================================
# Fixtures
# ============================================================


@pytest.fixture(name="client")
def fixture_client() -> Generator[TestClient, Any, None]:
    """Pytest fixture providing a TestClient with mocked Qdrant and no settings file."""
    with (
        patch(
            "src.api.main.wait_for_qdrant_ready",
            new_callable=AsyncMock,
            return_value=True,
        ),
        patch(
            "src.api.main.close_qdrant_client",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "src.api.routes.settings.load_settings",
            return_value={},
        ),
        patch(
            "src.api.routes.settings._save_settings",
            return_value=None,
        ),
        patch(
            "src.api.routes.settings.load_secrets",
            return_value={},
        ),
        patch(
            "src.api.routes.settings.save_secrets",
            return_value=None,
        ),
    ):
        from src.api.main import create_app

        app = create_app()
        with TestClient(app) as c:
            yield c


# ============================================================
# TestSettingsAPI
# ============================================================


class TestSettingsAPI:
    """Tests for the settings API endpoints."""

    def test_validate_key_invalid(self, client: TestClient) -> None:
        """POST /api/settings/validate-key with invalid key returns valid=false.

        We mock httpx.AsyncClient to return a 401.
        """
        mock_response = AsyncMock()
        mock_response.status_code = 401

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient", return_value=mock_client):
            resp = client.post(
                "/api/settings/validate-key",
                json={"provider": "openai", "api_key": "sk-invalid"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is False
        assert data["provider"] == "openai"
        assert data["error"] is not None

    def test_validate_key_valid(self, client: TestClient) -> None:
        """POST /api/settings/validate-key with mock success returns valid=true."""
        mock_response = AsyncMock()
        mock_response.status_code = 200

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient", return_value=mock_client):
            resp = client.post(
                "/api/settings/validate-key",
                json={"provider": "openai", "api_key": "sk-valid"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is True
        assert data["provider"] == "openai"
        assert data["error"] is None

    def test_validate_key_ollama_skips(self, client: TestClient) -> None:
        """POST /api/settings/validate-key for Ollama always returns valid=true."""
        resp = client.post(
            "/api/settings/validate-key",
            json={"provider": "ollama", "api_key": ""},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is True
        assert data["provider"] == "ollama"

    def test_validate_key_unsupported_provider(self, client: TestClient) -> None:
        """POST /api/settings/validate-key with unknown provider returns 400."""
        resp = client.post(
            "/api/settings/validate-key",
            json={"provider": "unknown", "api_key": "sk-test"},
        )

        assert resp.status_code == 400

    def test_get_settings(self, client: TestClient) -> None:
        """GET /api/settings returns settings without API key."""
        resp = client.get("/api/settings")

        assert resp.status_code == 200
        data = resp.json()
        assert "provider" in data
        assert "model" in data
        assert "temperature" in data
        assert "max_tokens" in data
        assert "system_prompt" in data
        assert "top_k" in data
        assert "chunk_size" in data
        assert "chunk_overlap" in data
        # API key should be None (not set)
        assert data.get("api_key") is None

    def test_save_settings(self, client: TestClient) -> None:
        """POST /api/settings saves settings successfully."""
        payload: dict[str, object] = {
            "provider": "deepseek",
            "model": "deepseek-chat",
            "temperature": 0.7,
            "max_tokens": 4096,
            "system_prompt": "You are a helpful assistant.",
            "top_k": 10,
            "chunk_size": 1024,
            "chunk_overlap": 128,
        }

        resp = client.post("/api/settings", json=payload)

        assert resp.status_code == 200
        data = resp.json()
        assert data["provider"] == "deepseek"
        assert data["model"] == "deepseek-chat"
        assert data["temperature"] == 0.7
        assert data["max_tokens"] == 4096
        assert data["top_k"] == 10
        assert data["chunk_size"] == 1024
        assert data["chunk_overlap"] == 128

    def test_save_settings_validation(self, client: TestClient) -> None:
        """POST /api/settings rejects invalid temperature range."""
        payload: dict[str, object] = {
            "provider": "openai",
            "model": "gpt-4o",
            "temperature": 3.0,  # out of range (0.0-2.0)
            "max_tokens": 2048,
            "system_prompt": "",
        }

        resp = client.post("/api/settings", json=payload)

        # FastAPI pydantic validation should reject
        assert resp.status_code == 422

    def test_get_document_chunks_success(self, client: TestClient) -> None:
        """GET /api/ingest/documents/{doc_id}/chunks returns chunks sorted by chunk_index."""
        # Create mock scroll result
        mock_point1 = MagicMock()
        mock_point1.payload = {
            "doc_id": "test-doc-123",
            "chunk_index": 2,
            "text": "Third chunk text here for testing purposes.",
            "token_count": 8,
            "page": 2,
        }

        mock_point2 = MagicMock()
        mock_point2.payload = {
            "doc_id": "test-doc-123",
            "chunk_index": 0,
            "text": "First chunk text.",
            "token_count": 4,
            "page": 1,
        }

        mock_client = AsyncMock()
        mock_client.scroll = AsyncMock(
            return_value=([mock_point1, mock_point2], None),  # (points, next_offset)
        )
        mock_client.collection_exists = AsyncMock(return_value=True)

        # Override the Qdrant client dependency
        from src.api.main import create_app

        app = create_app()
        app.dependency_overrides[get_qdrant_client] = lambda: mock_client

        with TestClient(app) as c:
            resp = c.get("/api/ingest/documents/test-doc-123/chunks")

        assert resp.status_code == 200
        data: list[dict[str, object]] = resp.json()  # type: ignore[assignment]
        assert len(data) == 2
        # Verify sorted by chunk_index
        assert data[0]["chunk_index"] == 0
        assert data[0]["text"] == "First chunk text."
        assert data[0]["token_count"] == 4
        assert data[0]["page"] == 1
        assert data[1]["chunk_index"] == 2
        assert data[1]["text"] == "Third chunk text here for testing purposes."
        assert data[1]["token_count"] == 8
        assert data[1]["page"] == 2

    def test_get_document_chunks_not_found(self, client: TestClient) -> None:
        """GET /api/ingest/documents/{doc_id}/chunks returns 404 for unknown doc."""
        mock_client = AsyncMock()
        mock_client.scroll = AsyncMock(return_value=([], None))  # no points
        mock_client.collection_exists = AsyncMock(return_value=True)

        from src.api.main import create_app

        app = create_app()
        app.dependency_overrides[get_qdrant_client] = lambda: mock_client

        with TestClient(app) as c:
            resp = c.get("/api/ingest/documents/nonexistent-doc/chunks")

        assert resp.status_code == 404
        data = resp.json()
        assert "detail" in data
