"""Cross-cutting regression coverage for bounded API state and localization."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import rate_limiter
from src.api.rate_limiter import RateLimitMiddleware


class FakeClock:
    """Mutable monotonic clock used to advance rate-limit windows deterministically."""

    def __init__(self) -> None:
        self.now = 10_000.0

    def monotonic(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _tiered_app() -> FastAPI:
    app = FastAPI()

    @app.get("/api/chat/stream")
    async def chat() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/api/ingest/upload")
    async def upload() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/api/settings")
    async def settings() -> dict[str, bool]:
        return {"ok": True}

    app.add_middleware(
        RateLimitMiddleware,
        chat_rpm=1,
        upload_rpm=1,
        general_rpm=1,
    )
    return app


def _middleware(app: FastAPI) -> RateLimitMiddleware:
    node = app.middleware_stack
    while node is not None:
        if isinstance(node, RateLimitMiddleware):
            return node
        node = getattr(node, "app", None)
    raise AssertionError("RateLimitMiddleware was not constructed")


def test_stale_rate_limit_tiers_are_evicted_to_finite_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = FakeClock()
    monkeypatch.setattr(rate_limiter, "time", clock)
    app = _tiered_app()

    with TestClient(app) as client:
        assert client.get("/api/chat/stream").status_code == 200
        assert client.get("/api/ingest/upload").status_code == 200
        assert client.get("/api/settings").status_code == 200
        assert client.get("/api/settings").status_code == 429

        clock.advance(61.0)
        assert client.get("/api/settings").status_code == 200

    limiter = _middleware(app)
    assert len(limiter._window) == 1
    assert {tier for _client, tier in limiter._window} == {"general"}
    assert all(len(timestamps) <= 1 for timestamps in limiter._window.values())


def test_shipped_locales_have_template_key_parity() -> None:
    project_root = Path(__file__).resolve().parents[2]
    locales_dir = project_root / "src" / "api" / "locales"
    templates_dir = project_root / "src" / "api" / "templates"
    locale_maps = {
        path.stem: json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(locales_dir.glob("*.json"))
    }
    assert set(locale_maps) == {"en", "ru"}

    canonical_keys = set(locale_maps["en"])
    for locale, translations in locale_maps.items():
        assert set(translations) == canonical_keys, locale
        assert all(isinstance(value, str) and value for value in translations.values())

    template_keys: set[str] = set()
    for template in templates_dir.glob("*.html"):
        template_keys.update(
            re.findall(
                r'data-i18n(?:-[a-z-]+)?="([^"]+)"',
                template.read_text(encoding="utf-8"),
            )
        )
    assert template_keys
    assert template_keys <= canonical_keys


def test_locale_initialization_hydrates_server_fallback_text() -> None:
    project_root = Path(__file__).resolve().parents[2]
    source = (project_root / "src" / "api" / "static" / "js" / "app.js").read_text(
        encoding="utf-8"
    )

    assert "function switchLanguage(locale, force)" in source
    assert "locale === currentLocale && !force" in source
    assert "switchLanguage(currentLocale, true)" in source
    assert "window.RAGStudio.translations = translations" in source
    assert "window.dispatchEvent(new CustomEvent('ragstudio:locale-changed'))" in source


def test_retrieval_settings_row_is_long_label_safe() -> None:
    project_root = Path(__file__).resolve().parents[2]
    source = (project_root / "src" / "api" / "static" / "css" / "style.css").read_text(
        encoding="utf-8"
    )
    row_rule = source.split(".retrieval-settings-row {", 1)[1].split("}", 1)[0]
    item_rule = source.split(".retrieval-setting-item {", 1)[1].split("}", 1)[0]

    assert "display: grid" in row_rule
    assert "repeat(3, minmax(0, 1fr))" in row_rule
    assert "height: auto" in row_rule
    assert "grid-template-rows: minmax(4.5em, auto) auto" in item_rule
    assert (
        "display: flex"
        in source.split(".retrieval-setting-item label {", 1)[1].split("}", 1)[0]
    )


def test_ui_asset_versions_cover_locale_and_layout_repairs() -> None:
    project_root = Path(__file__).resolve().parents[2]
    base = (project_root / "src" / "api" / "templates" / "base.html").read_text(
        encoding="utf-8"
    )
    chat = (project_root / "src" / "api" / "templates" / "chat.html").read_text(
        encoding="utf-8"
    )

    assert "/static/css/style.css?v=5" in base
    assert "/static/js/app.js?v=7" in base
    assert "/static/js/chat.js?v=1" in chat


def test_dynamic_empty_session_state_uses_active_locale() -> None:
    project_root = Path(__file__).resolve().parents[2]
    source = (project_root / "src" / "api" / "static" / "js" / "chat.js").read_text(
        encoding="utf-8"
    )

    assert "emptyDiv.setAttribute('data-i18n', 'chat_no_sessions')" in source
    assert "emptyDiv.textContent = t('chat_no_sessions')" in source
    assert (
        "window.addEventListener('ragstudio:locale-changed', renderSessionList)"
        in source
    )
