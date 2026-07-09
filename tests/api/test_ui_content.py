"""Unit tests for Iteration 2: Welcome Tab, Settings Tab, and Layout Fix.

Covers:
- Sidebar exclusivity (chat only)
- Welcome page video placeholder
- Settings page controls and layout
"""

from __future__ import annotations

from collections.abc import Generator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# ============================================================
# Fixtures
# ============================================================


@pytest.fixture(name="client")
def fixture_client() -> Generator[TestClient, Any, None]:
    """Pytest fixture providing a TestClient with mocked Qdrant."""
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
    ):
        from src.api.main import create_app

        app = create_app()
        with TestClient(app) as c:
            yield c


# ============================================================
# Sidebar Exclusivity Tests
# ============================================================


class TestSidebarExclusivity:
    """Verify sidebar is present ONLY on chat page."""

    def test_chat_page_has_sidebar(self, client: TestClient) -> None:
        """GET /chat → assert 'chat-sidebar' IS present."""
        response = client.get("/chat")
        assert response.status_code == 200
        assert "chat-sidebar" in response.text

    def test_welcome_page_no_sidebar(self, client: TestClient) -> None:
        """GET / → assert 'chat-sidebar' is NOT present on home page."""
        response = client.get("/")
        assert response.status_code == 200
        assert "chat-sidebar" not in response.text

    def test_settings_page_no_sidebar(self, client: TestClient) -> None:
        """GET /settings → assert 'chat-sidebar' is NOT present on settings page."""
        response = client.get("/settings")
        assert response.status_code == 200
        assert "chat-sidebar" not in response.text

    def test_chat_page_is_full_width(self, client: TestClient) -> None:
        """GET /chat → assert chat-full-width class present (no container wrapper)."""
        response = client.get("/chat")
        assert response.status_code == 200
        assert "chat-full-width" in response.text

    def test_chat_page_has_two_column_layout(self, client: TestClient) -> None:
        """GET /chat → assert chat-layout class for sidebar+main columns."""
        response = client.get("/chat")
        assert response.status_code == 200
        assert "chat-layout" in response.text
        assert "chat-sidebar" in response.text
        assert "chat-main" in response.text

    def test_sidebar_backdrop_only_on_chat(self, client: TestClient) -> None:
        """sidebar-backdrop is present on /chat but NOT on / and /settings."""
        # Chat page has backdrop
        resp = client.get("/chat")
        assert resp.status_code == 200
        assert "sidebar-backdrop" in resp.text
        # Welcome page does not
        resp = client.get("/")
        assert resp.status_code == 200
        assert "sidebar-backdrop" not in resp.text
        # Settings page does not
        resp = client.get("/settings")
        assert resp.status_code == 200
        assert "sidebar-backdrop" not in resp.text

    def test_chat_page_no_page_scrollbar(self, client: TestClient) -> None:
        """CSS must have html,body { overflow: hidden } to prevent page scrollbar."""
        css_resp = client.get("/static/css/style.css")
        assert css_resp.status_code == 200
        css = css_resp.text
        assert "overflow: hidden" in css

    def test_welcome_page_has_container(self, client: TestClient) -> None:
        """GET / → assert container class wraps the home page content."""
        response = client.get("/")
        assert response.status_code == 200
        html = response.text
        assert "container" in html
        assert "welcome-video-placeholder" in html

    def test_settings_page_has_container(self, client: TestClient) -> None:
        """GET /settings → assert container class wraps the settings content."""
        response = client.get("/settings")
        assert response.status_code == 200
        html = response.text
        assert "container" in html
        assert "settings-layout" in html


# ============================================================
# Welcome Content Tests
# ============================================================


class TestWelcomeContent:
    """Verify home page video placeholder content."""

    def test_video_placeholder_present(self, client: TestClient) -> None:
        """GET / → assert 'welcome-video-placeholder' is present."""
        response = client.get("/")
        assert response.status_code == 200
        html = response.text
        assert "welcome-video-placeholder" in html
        assert "welcome.video_placeholder" in html or "Video tutorial" in html

    def test_video_placeholder_localized_ru(self, client: TestClient) -> None:
        """GET /?lang=ru → assert RU locale is active and i18n key is present on home page."""
        response = client.get("/?lang=ru")
        assert response.status_code == 200
        html = response.text
        # Verify lang attribute is set to ru
        assert 'lang="ru"' in html
        # Verify the i18n data attribute for the video placeholder key
        assert 'data-i18n="welcome.video_placeholder"' in html
        # Verify the ru.json locale file contains the Russian translation
        import json
        from pathlib import Path

        locales_dir = (
            Path(__file__).resolve().parent.parent.parent / "src" / "api" / "locales"
        )
        with open(locales_dir / "ru.json", encoding="utf-8") as f:
            ru_data = json.load(f)
        assert "welcome.video_placeholder" in ru_data
        assert ru_data["welcome.video_placeholder"] == "Видео-инструкция появится здесь"

    def test_counter_cards_present(self, client: TestClient) -> None:
        """GET / → response contains counters-row, counter-card, data-counter attrs."""
        response = client.get("/")
        assert response.status_code == 200
        html = response.text
        assert "counters-row" in html
        assert "counter-card" in html
        assert 'data-counter="10"' in html
        assert 'data-counter="100"' in html

    def test_get_started_button_present(self, client: TestClient) -> None:
        """GET / → response contains btn-get-started and welcome.get_started."""
        response = client.get("/")
        assert response.status_code == 200
        html = response.text
        assert "btn-get-started" in html
        assert "welcome.get_started" in html

    def test_counter_labels_localized_ru(self, client: TestClient) -> None:
        """GET /?lang=ru → Russian text for counter labels appears in ru.json."""
        import json
        from pathlib import Path

        locales_dir = (
            Path(__file__).resolve().parent.parent.parent / "src" / "api" / "locales"
        )
        with open(locales_dir / "ru.json", encoding="utf-8") as f:
            ru_data = json.load(f)

        assert "welcome.counter_speed" in ru_data
        assert ru_data["welcome.counter_speed"] == "До 10× быстрее анализ документов"
        assert "welcome.counter_hours" in ru_data
        assert (
            ru_data["welcome.counter_hours"]
            == "Экономьте 100+ часов/мес на ручном поиске"
        )
        assert "welcome.counter_privacy" in ru_data
        assert (
            ru_data["welcome.counter_privacy"]
            == "100% приватно — ваши данные остаются на вашем устройстве"
        )
        assert "welcome.get_started" in ru_data
        assert ru_data["welcome.get_started"] == "Начать работу"

    def test_video_placeholder_still_present(self, client: TestClient) -> None:
        """GET / → video placeholder still exists (regression test)."""
        response = client.get("/")
        assert response.status_code == 200
        html = response.text
        assert "welcome-video-placeholder" in html
        assert 'data-testid="video-placeholder"' in html


# ============================================================
# Settings Content Tests
# ============================================================


class TestSettingsContent:
    """Verify all settings page controls are present."""

    def test_provider_dropdown_present(self, client: TestClient) -> None:
        """GET /settings → assert 'settings-provider' in html."""
        response = client.get("/settings")
        assert response.status_code == 200
        assert "settings-provider" in response.text

    def test_api_key_input_present(self, client: TestClient) -> None:
        """GET /settings → assert 'settings-api-key' with type=password."""
        response = client.get("/settings")
        assert response.status_code == 200
        html = response.text
        assert "settings-api-key" in html
        assert 'type="password"' in html

    def test_model_selector_present(self, client: TestClient) -> None:
        """GET /settings → assert 'settings-model' in html."""
        response = client.get("/settings")
        assert response.status_code == 200
        assert "settings-model" in response.text

    def test_temperature_slider_present(self, client: TestClient) -> None:
        """GET /settings → assert 'settings-temperature' in html."""
        response = client.get("/settings")
        assert response.status_code == 200
        assert "settings-temperature" in response.text

    def test_max_tokens_dropdown_present(self, client: TestClient) -> None:
        """GET /settings → assert 'settings-max-tokens' in html."""
        response = client.get("/settings")
        assert response.status_code == 200
        assert "settings-max-tokens" in response.text

    def test_system_prompt_textarea_present(self, client: TestClient) -> None:
        """GET /settings → assert 'settings-system-prompt' in html."""
        response = client.get("/settings")
        assert response.status_code == 200
        assert "settings-system-prompt" in response.text

    def test_document_upload_zone_present(self, client: TestClient) -> None:
        """GET /settings → assert 'upload-dropzone' in html."""
        response = client.get("/settings")
        assert response.status_code == 200
        assert "upload-dropzone" in response.text

    def test_browse_files_button_present(self, client: TestClient) -> None:
        """GET /settings → assert 'btn-browse-files' in html."""
        response = client.get("/settings")
        assert response.status_code == 200
        assert "btn-browse-files" in response.text

    def test_document_table_present(self, client: TestClient) -> None:
        """GET /settings → assert 'doc-table' in html."""
        response = client.get("/settings")
        assert response.status_code == 200
        assert "doc-table" in response.text

    def test_langsmith_card_present(self, client: TestClient) -> None:
        """GET /settings → assert 'langsmith-card' in html."""
        response = client.get("/settings")
        assert response.status_code == 200
        assert "langsmith-card" in response.text

    def test_connect_langsmith_button_present(self, client: TestClient) -> None:
        """GET /settings → assert 'connect-langsmith-btn' in html."""
        response = client.get("/settings")
        assert response.status_code == 200
        assert "connect-langsmith-btn" in response.text

    def test_two_column_layout_present(self, client: TestClient) -> None:
        """GET /settings → assert 'settings-layout' in html."""
        response = client.get("/settings")
        assert response.status_code == 200
        assert "settings-layout" in response.text

    def test_all_settings_controls_have_testids(self, client: TestClient) -> None:
        """GET /settings → verify data-testid attributes on all key elements."""
        response = client.get("/settings")
        assert response.status_code == 200
        html = response.text

        expected_testids = [
            "settings-layout",
            "settings-left",
            "settings-right",
            "provider-select",
            "api-key-input",
            "model-select",
            "temperature-slider",
            "max-tokens-select",
            "system-prompt-textarea",
            "doc-upload-zone",
            "upload-dropzone",
            "browse-files-btn",
            "doc-table",
            "langsmith-card",
            "connect-langsmith-btn",
            "top-k-select",
            "chunk-size-select",
            "chunk-overlap-select",
            "retrieval-settings-row",
        ]

        for testid in expected_testids:
            assert f'data-testid="{testid}"' in html, (
                f"Missing data-testid='{testid}' in settings page"
            )

    def test_save_settings_button_present(self, client: TestClient) -> None:
        """GET /settings → assert btn-save-settings with data-testid exists."""
        response = client.get("/settings")
        assert response.status_code == 200
        assert "btn-save-settings" in response.text
        assert 'data-testid="save-settings-btn"' in response.text

    def test_reset_prompt_button_present(self, client: TestClient) -> None:
        """GET /settings → assert btn-reset-prompt with data-testid exists."""
        response = client.get("/settings")
        assert response.status_code == 200
        assert "btn-reset-prompt" in response.text
        assert 'data-testid="reset-prompt-btn"' in response.text

    def test_langsmith_modal_present(self, client: TestClient) -> None:
        """GET /settings → assert langsmithModal with data-testid exists."""
        response = client.get("/settings")
        assert response.status_code == 200
        assert "langsmithModal" in response.text
        assert 'data-testid="langsmith-modal"' in response.text

    def test_top_k_dropdown_present(self, client: TestClient) -> None:
        """GET /settings → assert 'settings-top-k' in html."""
        response = client.get("/settings")
        assert response.status_code == 200
        assert "settings-top-k" in response.text

    def test_chunk_size_dropdown_present(self, client: TestClient) -> None:
        """GET /settings → assert 'settings-chunk-size' in html."""
        response = client.get("/settings")
        assert response.status_code == 200
        assert "settings-chunk-size" in response.text

    def test_chunk_overlap_dropdown_present(self, client: TestClient) -> None:
        """GET /settings → assert 'settings-chunk-overlap' in html."""
        response = client.get("/settings")
        assert response.status_code == 200
        assert "settings-chunk-overlap" in response.text

    def test_retrieval_settings_row_present(self, client: TestClient) -> None:
        """GET /settings → assert 'retrieval-settings-row' in html."""
        response = client.get("/settings")
        assert response.status_code == 200
        assert "retrieval-settings-row" in response.text


class TestChunkSettingsColumn:
    """Tests for the Chunk Settings column in the document list table."""

    def test_settings_page_has_chunk_settings_column_header(
        self, client: TestClient
    ) -> None:
        """GET /settings → assert 'Chunk Settings' column header in HTML."""
        response = client.get("/settings")
        assert response.status_code == 200
        assert "settings_doc_col_chunk_settings" in response.text
        assert "Chunk Settings" in response.text

    def test_api_returns_chunk_size_and_overlap(self, client: TestClient) -> None:
        """GET /api/ingest/documents → documents include chunk_size and chunk_overlap.

        Overrides the Qdrant client dependency on the fixture's app to return
        mock scroll results with chunk_size and chunk_overlap payload fields.
        """
        from src.api.dependencies import get_qdrant_client

        mock_point = MagicMock()
        mock_point.payload = {
            "doc_id": "doc-abc",
            "source": "test-doc.txt",
            "total_chunks": 3,
            "chunk_index": 0,
            "chunk_size": 512,
            "chunk_overlap": 64,
            "created_at": "2026-01-01T00:00:00",
        }

        mock_qdrant = AsyncMock()
        mock_qdrant.scroll = AsyncMock(return_value=([mock_point], None))
        mock_qdrant.collection_exists = AsyncMock(return_value=True)

        # Override the Qdrant dependency on the fixture-created app.
        client.app.dependency_overrides[get_qdrant_client] = lambda: mock_qdrant

        resp = client.get("/api/ingest/documents")

        assert resp.status_code == 200
        data = resp.json()
        assert "documents" in data
        docs = data["documents"]
        assert len(docs) == 1
        assert docs[0]["chunk_size"] == 512
        assert docs[0]["chunk_overlap"] == 64
        assert docs[0]["filename"] == "test-doc.txt"
        assert docs[0]["chunks_count"] == 3
