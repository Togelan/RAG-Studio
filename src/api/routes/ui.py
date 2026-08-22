"""FastAPI router for serving HTML pages and UI locale management.

Handles:
- GET / — Welcome page
- GET /settings — Settings page
- GET /chat — Chat page
- POST /api/ui/locale — Locale switching with cookie persistence
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from src.api.react_ui import (
    UiMode,
    UiServingConfiguration,
    react_asset_response,
    react_document_response,
)

# Template directory — relative to this file's location
_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
_LOCALES_DIR = Path(__file__).resolve().parent.parent / "locales"

# Jinja2 templates engine
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

# Cache loaded locale files
_locale_cache: dict[str, dict[str, str]] = {}


class LocaleRequest(BaseModel):
    """Request schema for locale switching."""

    locale: str = Field(
        default="en",
        pattern=r"^(en|ru)$",
        description="Two-letter language code: 'en' or 'ru'.",
    )


class LocaleResponse(BaseModel):
    """Response schema for locale switching."""

    locale: str = Field(description="The new active locale.")
    translations: dict[str, str] = Field(
        description="Full translation map for the new locale."
    )


def _load_locale(lang: str) -> dict[str, str]:
    """Load a locale JSON file from disk, with in-memory caching.

    Args:
        lang: Two-letter language code ('en' or 'ru').

    Returns:
        Dictionary of translation key → translated string.
    """
    if lang in _locale_cache:
        return _locale_cache[lang]

    locale_path = _LOCALES_DIR / f"{lang}.json"
    if locale_path.is_file():
        with open(locale_path, encoding="utf-8") as f:
            data: dict[str, str] = json.load(f)
    else:
        data = {}

    _locale_cache[lang] = data
    return data


def _detect_locale(request: Request) -> str:
    """Determine user locale from cookie, query param, or Accept-Language header.

    Priority:
        1. Query parameter `lang`
        2. Cookie `locale`
        3. Accept-Language header
        4. Default 'en'

    Args:
        request: The FastAPI Request object.

    Returns:
        Two-letter language code ('en' or 'ru').
    """
    # 1. Query parameter
    lang = request.query_params.get("lang", "").lower()
    if lang in ("en", "ru"):
        return lang

    # 2. Cookie
    cookie_lang = request.cookies.get("locale", "").lower()
    if cookie_lang in ("en", "ru"):
        return cookie_lang

    # 3. Accept-Language header
    accept_lang = request.headers.get("Accept-Language", "")
    if accept_lang:
        # Simple parsing: take first language code
        first_lang = accept_lang.split(",")[0].split(";")[0].strip().lower()
        if first_lang in ("en", "ru"):
            return first_lang
        if first_lang.startswith("ru"):
            return "ru"

    # 4. Default
    return "en"


def _legacy_page_response(request: Request, page: str) -> HTMLResponse:
    """Render one explicit legacy page with a no-store cache policy."""
    lang = _detect_locale(request)
    translations = _load_locale(lang)
    response = templates.TemplateResponse(
        f"{page}.html",
        {
            "request": request,
            "lang": lang,
            "active_tab": "welcome" if page == "welcome" else page,
            "translations": translations,
        },
    )
    response.headers["Cache-Control"] = "no-store"
    return response


def _canonical_page_response(
    request: Request,
    page: str,
    configuration: UiServingConfiguration,
) -> Response:
    """Render the selected canonical page without allowing route capture."""
    if configuration.mode is UiMode.REACT:
        return react_document_response(configuration)
    return _legacy_page_response(request, page)


def _react_preview_response(configuration: UiServingConfiguration) -> Response:
    """Serve a React alias or its sanitized legacy-mode unavailable response."""
    return react_document_response(configuration)


def create_ui_router(configuration: UiServingConfiguration) -> APIRouter:
    """Create explicit UI routes bound to one validated serving configuration."""
    ui_router = APIRouter(tags=["ui"])

    @ui_router.get("/", response_class=HTMLResponse)
    async def serve_welcome(request: Request) -> Response:
        """Serve the selected canonical Home page."""
        return _canonical_page_response(request, "welcome", configuration)

    @ui_router.get("/settings", response_class=HTMLResponse)
    async def serve_settings(request: Request) -> Response:
        """Serve the selected canonical Settings page."""
        return _canonical_page_response(request, "settings", configuration)

    @ui_router.get("/chat", response_class=HTMLResponse)
    async def serve_chat(request: Request) -> Response:
        """Serve the selected canonical Chat page."""
        return _canonical_page_response(request, "chat", configuration)

    @ui_router.get("/app", response_class=HTMLResponse)
    @ui_router.get("/app/settings", response_class=HTMLResponse)
    @ui_router.get("/app/chat", response_class=HTMLResponse)
    async def serve_react_preview() -> Response:
        """Serve an explicit React preview route."""
        return _react_preview_response(configuration)

    if configuration.mode is UiMode.REACT:

        @ui_router.get("/app/{app_path:path}", response_class=HTMLResponse)
        async def serve_react_app_fallback(app_path: str) -> Response:
            del app_path
            return react_document_response(configuration)

    @ui_router.get("/saas", response_class=HTMLResponse)
    @ui_router.get("/saas/{retired_path:path}", response_class=HTMLResponse)
    async def serve_retired_saas_route(retired_path: str = "") -> Response:
        """Serve retired SaaS document requests through the unified React router."""
        del retired_path
        return _react_preview_response(configuration)

    @ui_router.get("/legacy", response_class=HTMLResponse)
    async def serve_legacy_welcome(request: Request) -> HTMLResponse:
        """Serve the explicit legacy Home rollback alias."""
        return _legacy_page_response(request, "welcome")

    @ui_router.get("/legacy/settings", response_class=HTMLResponse)
    async def serve_legacy_settings(request: Request) -> HTMLResponse:
        """Serve the explicit legacy Settings rollback alias."""
        return _legacy_page_response(request, "settings")

    @ui_router.get("/legacy/chat", response_class=HTMLResponse)
    async def serve_legacy_chat(request: Request) -> HTMLResponse:
        """Serve the explicit legacy Chat rollback alias."""
        return _legacy_page_response(request, "chat")

    @ui_router.get("/react-assets/{asset_path:path}")
    async def serve_react_asset(asset_path: str) -> Response:
        """Serve a manifest-validated React static asset."""
        return react_asset_response(configuration, asset_path)

    @ui_router.post("/api/ui/locale", response_model=LocaleResponse)
    async def set_locale(
        request: Request,
        body: LocaleRequest,
    ) -> JSONResponse:
        """Set the UI locale and return translations.

        Sets a cookie to persist the locale preference.
        Returns the full translation map for client-side i18n updates.

        Args:
            request: The incoming HTTP request.
            body: Locale request with the target language code.

        Returns:
            JSON response with the new locale and translation map.
        """
        lang = body.locale
        translations = _load_locale(lang)

        response = JSONResponse(
            content={
                "locale": lang,
                "translations": translations,
            }
        )

        response.set_cookie(
            key="locale",
            value=lang,
            max_age=60 * 60 * 24 * 365,
            samesite="lax",
            secure=False,
            httponly=False,
        )

        return response

    return ui_router


router = create_ui_router(UiServingConfiguration(mode=UiMode.LEGACY, react_build=None))
