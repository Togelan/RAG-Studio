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
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

router = APIRouter(tags=["ui"])

# Template directory — relative to this file's location
_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
_LOCALES_DIR = Path(__file__).resolve().parent.parent / "locales"

# Jinja2 templates engine
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

# Cache loaded locale files
_locale_cache: dict[str, dict[str, str]] = {}


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


@router.get("/", response_class=HTMLResponse)
async def serve_welcome(request: Request) -> HTMLResponse:
    """Serve the Home page.

    Args:
        request: The incoming HTTP request.

    Returns:
        HTML response rendering welcome.html.
    """
    lang = _detect_locale(request)
    translations = _load_locale(lang)

    return templates.TemplateResponse(
        "welcome.html",
        {
            "request": request,
            "lang": lang,
            "active_tab": "welcome",
            "translations": translations,
        },
    )


@router.get("/settings", response_class=HTMLResponse)
async def serve_settings(request: Request) -> HTMLResponse:
    """Serve the Settings page.

    Args:
        request: The incoming HTTP request.

    Returns:
        HTML response rendering settings.html.
    """
    lang = _detect_locale(request)
    translations = _load_locale(lang)

    return templates.TemplateResponse(
        "settings.html",
        {
            "request": request,
            "lang": lang,
            "active_tab": "settings",
            "translations": translations,
        },
    )


@router.get("/chat", response_class=HTMLResponse)
async def serve_chat(request: Request) -> HTMLResponse:
    """Serve the Chat page.

    Args:
        request: The incoming HTTP request.

    Returns:
        HTML response rendering chat.html.
    """
    lang = _detect_locale(request)
    translations = _load_locale(lang)

    return templates.TemplateResponse(
        "chat.html",
        {
            "request": request,
            "lang": lang,
            "active_tab": "chat",
            "translations": translations,
        },
    )


class LocaleRequest(BaseModel):
    """Request schema for locale switching."""

    locale: str = Field(
        default="en",
        pattern=r"^(en|ru)$",
        description="Two-letter language code: 'en' or 'ru'",
    )


class LocaleResponse(BaseModel):
    """Response schema for locale switching."""

    locale: str = Field(description="The new active locale.")
    translations: dict[str, str] = Field(
        description="Full translation map for the new locale."
    )


@router.post("/api/ui/locale", response_model=LocaleResponse)
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

    # Set locale cookie (1 year expiry)
    response.set_cookie(
        key="locale",
        value=lang,
        max_age=60 * 60 * 24 * 365,
        samesite="lax",
        secure=False,  # Local tool, no HTTPS needed
        httponly=False,  # Allow JS to read if needed
    )

    return response
