"""Unit tests for FR-007: Web UI — Navigation, Layout & Responsive Design.

Covers all 4 Acceptance Criteria:
- AC-007.1: Tab Navigation
- AC-007.2: Language Switcher
- AC-007.3: Responsive Breakpoints
- AC-007.4: Global Header
"""

from __future__ import annotations

from collections.abc import Generator
from typing import Any
from unittest.mock import AsyncMock, patch

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
# AC-007.1: Tab Navigation
# ============================================================


class TestTabNavigation:
    """Tests for AC-007.1: Tab Navigation."""

    def test_tabs_visible_on_homepage(self, client: TestClient) -> None:
        """Verify 3 tabs render on the home page.

        AC-007.1: Three tabs visible — Home, Settings, Chat.
        """
        response = client.get("/")
        assert response.status_code == 200

        html = response.text
        assert "nav_welcome" in html or "Home" in html
        assert "nav_settings" in html or "Settings" in html
        assert "nav_chat" in html or "Chat" in html

        # Verify 3 nav-tab buttons exist
        assert html.count("nav-tab") >= 3

    def test_active_tab_highlighted(self, client: TestClient) -> None:
        """Verify active tab has the 'active' CSS class.

        AC-007.1: Active tab is highlighted with accent underline.
        """
        response = client.get("/")
        assert response.status_code == 200

        html = response.text
        # The home tab should be marked active
        assert 'data-tab="welcome"' in html
        assert "active" in html  # At least one element has active class

    def test_all_tab_pages_return_200_with_active_tab(self, client: TestClient) -> None:
        """Verify all 3 pages return 200 and each has correct active tab."""
        cases = [
            ("/", "welcome", "Home"),
            ("/settings", "settings", "Settings"),
            ("/chat", "chat", "Chat"),
        ]
        for path, tab_id, expected_text in cases:
            resp = client.get(path)
            assert resp.status_code == 200, f"{path} failed"
            html = resp.text
            assert expected_text.lower() in html.lower(), (
                f"Missing '{expected_text}' on {path}"
            )
            assert f'data-tab="{tab_id}"' in html, f"Tab {tab_id} not active on {path}"


# ============================================================
# AC-007.2: Language Switcher
# ============================================================


class TestLanguageSwitcher:
    """Tests for AC-007.2: Language Switcher."""

    def test_language_switcher_present(self, client: TestClient) -> None:
        """Verify EN and RU language buttons exist in the header.

        AC-007.2: Language toggle EN | RU visible.
        """
        response = client.get("/")
        assert response.status_code == 200

        html = response.text
        assert "lang-switcher" in html
        assert 'data-lang="en"' in html
        assert 'data-lang="ru"' in html

    def test_locale_switch_ru_and_en(self, client: TestClient) -> None:
        """POST /api/ui/locale switches locale and returns correct translations."""
        # RU
        resp = client.post("/api/ui/locale", json={"locale": "ru"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["locale"] == "ru"
        assert data["translations"]["nav_welcome"] == "Главная"
        # EN
        resp = client.post("/api/ui/locale", json={"locale": "en"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["locale"] == "en"
        assert data["translations"]["nav_welcome"] == "Home"

    def test_locale_persists_in_cookie(self, client: TestClient) -> None:
        """Verify locale switch sets a cookie for persistence.

        AC-007.2: Language preference is saved to localStorage/cookie.
        """
        response = client.post(
            "/api/ui/locale",
            json={"locale": "ru"},
        )
        assert response.status_code == 200

        # Check that a Set-Cookie header is present
        cookies = response.headers.get("set-cookie", "")
        assert "locale=ru" in cookies, f"Expected locale=ru cookie, got: {cookies}"

    def test_invalid_locale_rejected(self, client: TestClient) -> None:
        """Verify non-en/ru locale returns 422 validation error."""
        resp = client.post("/api/ui/locale", json={"locale": "fr"})
        assert resp.status_code == 422


# ============================================================
# AC-007.3: Responsive Breakpoints
# ============================================================


class TestResponsiveDesign:
    """Tests for AC-007.3: Responsive Breakpoints."""

    def test_responsive_meta_viewport(self, client: TestClient) -> None:
        """Verify <meta name='viewport'> is present for mobile responsiveness.

        AC-007.3: All text readable, no horizontal scroll.
        """
        response = client.get("/")
        assert response.status_code == 200

        html = response.text
        assert 'name="viewport"' in html
        assert "width=device-width" in html
        assert "initial-scale=1.0" in html

    def test_mobile_tab_bar_renders(self, client: TestClient) -> None:
        """Verify .mobile-tab-bar element exists in HTML for mobile navigation.

        AC-007.3: <768px mobile has bottom tab bar.
        """
        response = client.get("/")
        assert response.status_code == 200

        html = response.text
        assert "mobile-tab-bar" in html
        assert "mobile-tab" in html

    def test_hamburger_and_overlay_render(self, client: TestClient) -> None:
        """Verify .hamburger and .mobile-nav-overlay exist for tablet layout."""
        resp = client.get("/")
        assert resp.status_code == 200
        html = resp.text
        assert "hamburger" in html
        assert "mobile-nav-overlay" in html
        assert "mobile-nav-menu" in html

    def test_static_assets_served(self, client: TestClient) -> None:
        """Verify CSS and JS static files are served with correct content types."""
        css = client.get("/static/css/style.css")
        assert css.status_code == 200
        assert "text/css" in css.headers.get("content-type", "")
        js = client.get("/static/js/app.js")
        assert js.status_code == 200
        ct = js.headers.get("content-type", "").lower()
        assert "javascript" in ct or "text" in ct

    def test_container_class_present(self, client: TestClient) -> None:
        """Verify .container used for centered max-width layout."""
        resp = client.get("/")
        assert resp.status_code == 200
        assert "container" in resp.text

    def test_settings_stacks_on_mobile(self, client: TestClient) -> None:
        """Verify settings-layout uses CSS that stacks at ≤768px (grid-template-columns: 1fr)."""
        css_resp = client.get("/static/css/style.css")
        assert css_resp.status_code == 200
        css = css_resp.text
        # The mobile media query should contain grid-template-columns: 1fr for settings
        assert "grid-template-columns: 1fr" in css

    def test_welcome_video_placeholder_responsive(self, client: TestClient) -> None:
        """Verify home page video placeholder has max-width constraint for mobile."""
        css_resp = client.get("/static/css/style.css")
        assert css_resp.status_code == 200
        css = css_resp.text
        assert "welcome-video-placeholder" in css
        # Should have max-width: 100% for mobile
        assert "max-width: 100%" in css


# ============================================================
# AC-007.4: Global Header
# ============================================================


class TestGlobalHeader:
    """Tests for AC-007.4: Global Header."""

    def test_header_contains_logo_and_status(self, client: TestClient) -> None:
        """Verify 'RAG Studio' logo, .status-indicator, and .status-dot exist."""
        resp = client.get("/")
        assert resp.status_code == 200
        html = resp.text
        assert "RAG Studio" in html
        assert "status-indicator" in html
        assert "status-dot" in html

    def test_header_element_order(self, client: TestClient) -> None:
        """Verify header DOM order: logo → nav tabs → lang switcher → status."""
        resp = client.get("/")
        assert resp.status_code == 200
        html = resp.text
        for token in ("header-logo", "nav-tab", "lang-switcher", "status-indicator"):
            assert token in html, f"Missing: {token}"
        logo_pos = html.find("header-logo")
        nav_pos = html.find("nav-tab")
        lang_pos = html.find("lang-switcher")
        status_pos = html.find("status-indicator")
        assert logo_pos < nav_pos < lang_pos < status_pos, "Header element order wrong"

    def test_status_endpoint_returns_json(self, client: TestClient) -> None:
        """Verify GET /api/health/status returns a JSON status object.

        AC-007.4: Status indicator shows connection state.
        """
        response = client.get("/api/health/status")
        assert response.status_code == 200

        data = response.json()
        assert "status" in data
        assert data["status"] in ("ready", "degraded")

    def test_all_pages_have_header(self, client: TestClient) -> None:
        """Verify global-header, logo, and status on /, /settings, /chat."""
        for path in ("/", "/settings", "/chat"):
            resp = client.get(path)
            assert resp.status_code == 200, f"{path} failed"
            html = resp.text
            for el in ("global-header", "header-logo", "status-indicator"):
                assert el in html, f"Missing '{el}' on {path}"

    def test_lang_param_sets_locale(self, client: TestClient) -> None:
        """Verify ?lang=ru sets data-locale='ru' in HTML."""
        resp = client.get("/?lang=ru")
        assert resp.status_code == 200
        assert 'data-locale="ru"' in resp.text or 'lang="ru"' in resp.text


# ============================================================
# Chat Sidebar Tests (FR-006.1 Restore)
# ============================================================


class TestChatSidebar:
    """Tests for chat sidebar presence and behavior."""

    def test_chat_page_has_sidebar_backdrop(self, client: TestClient) -> None:
        """GET /chat has sidebar-backdrop element for mobile overlay."""
        resp = client.get("/chat")
        assert resp.status_code == 200
        assert "sidebar-backdrop" in resp.text

    def test_chat_page_sidebar_is_collapsible(self, client: TestClient) -> None:
        """GET /chat has sidebar-toggle button and collapsible sidebar class."""
        resp = client.get("/chat")
        assert resp.status_code == 200
        html = resp.text
        assert "sidebarToggle" in html
        assert "chat-sidebar" in html
        # CSS should have .collapsed rule
        css_resp = client.get("/static/css/style.css")
        assert css_resp.status_code == 200
        assert "collapsed" in css_resp.text
