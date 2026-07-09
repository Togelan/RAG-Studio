"""Tests for re-ingestion logic (FR-010).

Covers:
- AC-010.1: Silent save when no documents exist
- AC-010.2/AC-010.3: Re-ingestion modal when documents exist, skip path
- AC-010.4: Re-ingest all path with clear + reingest
- AC-010.5: Chunk-setting change detection via POST /api/settings
- AC-010.6: Error handling during re-ingestion
"""

from __future__ import annotations

from collections.abc import Generator
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
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
# TestSettingsReingest
# ============================================================


class TestSettingsReingest:
    """Tests for settings re-ingestion logic (FR-010)."""

    # ----------------------------------------------------------
    # AC-010.5: Chunk-Setting Change Detection
    # ----------------------------------------------------------

    def test_save_settings_no_chunk_change(self, client: TestClient) -> None:
        """AC-010.5: When chunk settings are unchanged, chunks_changed is false."""
        with patch(
            "src.api.routes.settings.load_settings",
            return_value={"chunk_size": 512, "chunk_overlap": 64},
        ):
            resp = client.post(
                "/api/settings",
                json={
                    "provider": "openai",
                    "model": "gpt-4o-mini",
                    "temperature": 1.0,
                    "max_tokens": 2048,
                    "system_prompt": "",
                    "top_k": 5,
                    "chunk_size": 512,
                    "chunk_overlap": 64,
                },
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["chunks_changed"] is False

    def test_save_settings_chunks_changed_chunk_size(self, client: TestClient) -> None:
        """AC-010.5: POST /api/settings returns chunks_changed=true when chunk_size changed."""
        with patch(
            "src.api.routes.settings.load_settings",
            return_value={"chunk_size": 512, "chunk_overlap": 64},
        ):
            resp = client.post(
                "/api/settings",
                json={
                    "provider": "openai",
                    "model": "gpt-4o-mini",
                    "temperature": 1.0,
                    "max_tokens": 2048,
                    "system_prompt": "",
                    "top_k": 5,
                    "chunk_size": 1024,
                    "chunk_overlap": 64,
                },
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["chunks_changed"] is True

    def test_save_settings_chunks_changed_chunk_overlap(
        self, client: TestClient
    ) -> None:
        """AC-010.5: POST /api/settings returns chunks_changed=true when chunk_overlap changed."""
        with patch(
            "src.api.routes.settings.load_settings",
            return_value={"chunk_size": 512, "chunk_overlap": 64},
        ):
            resp = client.post(
                "/api/settings",
                json={
                    "provider": "openai",
                    "model": "gpt-4o-mini",
                    "temperature": 1.0,
                    "max_tokens": 2048,
                    "system_prompt": "",
                    "top_k": 5,
                    "chunk_size": 512,
                    "chunk_overlap": 128,
                },
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["chunks_changed"] is True

    def test_save_settings_no_chunk_change_other_fields(
        self, client: TestClient
    ) -> None:
        """AC-010.5: Changes to non-chunk settings do NOT trigger chunks_changed."""
        with patch(
            "src.api.routes.settings.load_settings",
            return_value={"chunk_size": 512, "chunk_overlap": 64},
        ):
            resp = client.post(
                "/api/settings",
                json={
                    "provider": "deepseek",
                    "model": "deepseek-chat",
                    "temperature": 0.5,
                    "max_tokens": 4096,
                    "system_prompt": "You are helpful.",
                    "top_k": 10,
                    "chunk_size": 512,
                    "chunk_overlap": 64,
                },
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["chunks_changed"] is False

    # ----------------------------------------------------------
    # AC-010.4: Re-Ingest Endpoint
    # ----------------------------------------------------------

    def test_reingest_endpoint_accepts_request(self, client: TestClient) -> None:
        """AC-010.4: POST /api/ingest/reingest accepts doc_id and filename, returns file_id."""
        from pathlib import Path

        # Create a mock raw upload file keyed by doc_id (BUG-010-1 fix)
        raw_dir = Path("data/raw_uploads")
        raw_dir.mkdir(parents=True, exist_ok=True)
        test_doc_id = "test-doc-id-123"
        raw_path = raw_dir / f"{test_doc_id}.txt"
        raw_path.write_text("Test content for re-ingestion.", encoding="utf-8")

        app = cast(FastAPI, client.app)

        try:
            # Mock the Qdrant client dependency and background ingestion
            mock_client = AsyncMock()
            mock_client.collection_exists = AsyncMock(return_value=True)

            async def override_get_qdrant() -> AsyncMock:
                return mock_client

            app.dependency_overrides[get_qdrant_client] = override_get_qdrant

            # Mock ensure_collection_exists
            with patch(
                "src.ingestion.router.ensure_collection_exists",
                new_callable=AsyncMock,
                return_value=None,
            ):
                resp = client.post(
                    "/api/ingest/reingest",
                    json={"doc_id": test_doc_id, "filename": "test.txt"},
                )

            assert resp.status_code == 202
            data = resp.json()
            assert data["status"] == "processing"
            assert data["file_id"] is not None
            assert len(data["file_id"]) > 0
        finally:
            # Clean up mock file
            raw_path.unlink(missing_ok=True)
            # Clean up dependency override
            app.dependency_overrides.pop(get_qdrant_client, None)

    def test_reingest_endpoint_no_stored_file(self, client: TestClient) -> None:
        """AC-010.4: POST /api/ingest/reingest returns 200 with skipped status when no stored file found."""
        # Ensure raw_uploads dir exists but is empty
        from pathlib import Path

        raw_dir = Path("data/raw_uploads")
        raw_dir.mkdir(parents=True, exist_ok=True)

        app = cast(FastAPI, client.app)

        # Mock Qdrant client to avoid portalocker lock on local storage.
        # The skipped path never uses the client, but FastAPI resolves it
        # as a dependency before the handler runs.
        mock_client = AsyncMock()

        async def override_get_qdrant() -> AsyncMock:
            return mock_client

        app.dependency_overrides[get_qdrant_client] = override_get_qdrant

        try:
            resp = client.post(
                "/api/ingest/reingest",
                json={"doc_id": "test-doc-id", "filename": "nonexistent.xyz"},
            )

            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "skipped"
            assert "no longer available" in data["message"]
            assert data["detail"] is not None
        finally:
            app.dependency_overrides.pop(get_qdrant_client, None)

    # ----------------------------------------------------------
    # AC-010.4: Clear Then Re-Ingest Flow
    # ----------------------------------------------------------

    def test_clear_endpoint_exists(self, client: TestClient) -> None:
        """AC-010.4: DELETE /api/ingest/clear endpoint exists and returns 200."""
        mock_client = AsyncMock()
        mock_client.collection_exists = AsyncMock(return_value=True)
        mock_client.count = AsyncMock(return_value=MagicMock(count=5))
        mock_client.delete_collection = AsyncMock(return_value=None)

        async def override_get_qdrant() -> AsyncMock:
            return mock_client

        app = cast(FastAPI, client.app)
        app.dependency_overrides[get_qdrant_client] = override_get_qdrant

        try:
            with patch(
                "src.ingestion.router.ensure_collection_exists",
                new_callable=AsyncMock,
                return_value=None,
            ):
                resp = client.delete("/api/ingest/clear")

            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "ok"
            assert "deleted_count" in data
        finally:
            app.dependency_overrides.pop(get_qdrant_client, None)

    # ----------------------------------------------------------
    # AC-010.1: Silent Save When No Documents
    # ----------------------------------------------------------

    def test_chunks_changed_no_documents_no_effect(self, client: TestClient) -> None:
        """AC-010.1: When documents list is empty, chunks_changed is still returned
        but the frontend should skip the modal (frontend behavior, tested via unit).

        This test verifies that POST /api/settings still returns chunks_changed
        correctly — the frontend's document check is separate.
        """
        with patch(
            "src.api.routes.settings.load_settings",
            return_value={"chunk_size": 256, "chunk_overlap": 32},
        ):
            resp = client.post(
                "/api/settings",
                json={
                    "provider": "openai",
                    "model": "gpt-4o-mini",
                    "temperature": 1.0,
                    "max_tokens": 2048,
                    "system_prompt": "",
                    "top_k": 5,
                    "chunk_size": 512,
                    "chunk_overlap": 64,
                },
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["chunks_changed"] is True
        # The frontend checks /api/ingest/documents before showing modal

    # ----------------------------------------------------------
    # AC-010.6: Error Handling in Re-Ingestion
    # ----------------------------------------------------------

    def test_reingest_progress_endpoint_exists(self, client: TestClient) -> None:
        """AC-010.6: GET /api/ingest/progress/{file_id} returns 404 for unknown ID."""
        resp = client.get("/api/ingest/progress/nonexistent-file-id")
        assert resp.status_code == 404
