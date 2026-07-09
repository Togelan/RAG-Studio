"""FastAPI router for settings management.

Endpoints:
- POST /api/settings/validate-key — validate & encrypt API key
- GET /api/settings — retrieve current settings (no API key)
- POST /api/settings — save settings
- GET /api/settings/models/{provider} — fetch available models with daily cache
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.api.dependencies import (
    decrypt_api_key,
    encrypt_api_key,
    load_secrets,
    save_secrets,
)
from src.api.routes.model_fetcher import (
    get_fallback_models,
    get_models_for_provider,
    get_supported_providers,
    is_cache_valid,
    load_models_cache,
    save_models_cache,
)

router = APIRouter(prefix="/api/settings", tags=["settings"])

logger = logging.getLogger(__name__)

# ============================================================
# Settings file path (configurable via env)
# ============================================================

_SETTINGS_PATH = Path(os.getenv("RAG_STUDIO_SETTINGS_PATH", "data/settings.enc.json"))

# ============================================================
# Provider validation endpoint URLs
# ============================================================

_VALIDATION_URLS: dict[str, str] = {
    "openai": "https://api.openai.com/v1/models",
    "deepseek": "https://api.deepseek.com/v1/models",
    "anthropic": "https://api.anthropic.com/v1/models",
}

# ============================================================
# Pydantic Models
# ============================================================


class ValidateKeyRequest(BaseModel):
    """Request schema for API key validation."""

    provider: str = Field(
        ...,
        description="Provider name: openai, deepseek, anthropic, or ollama",
    )
    api_key: str = Field(
        default="",
        min_length=0,
        description="The API key to validate (may be empty for Ollama)",
    )


class ValidateKeyResponse(BaseModel):
    """Response schema for API key validation."""

    valid: bool
    provider: str
    error: str | None = None


class SettingsData(BaseModel):
    """Settings payload for save/load."""

    provider: str = Field(default="deepseek")
    model: str = Field(default="gpt-4o-mini")
    temperature: float = Field(default=1.0, ge=0.0, le=2.0)
    max_tokens: int = Field(default=2048, ge=1, le=32768)
    system_prompt: str = Field(default="")
    top_k: int = Field(default=5, ge=1, le=100)
    chunk_size: int = Field(default=512, ge=128, le=4096)
    chunk_overlap: int = Field(default=64, ge=0, le=512)


class SaveSettingsResponse(BaseModel):
    """Response schema for POST /api/settings — includes change detection."""

    provider: str
    model: str
    temperature: float
    max_tokens: int
    system_prompt: str
    top_k: int
    chunk_size: int
    chunk_overlap: int
    chunks_changed: bool = Field(
        default=False,
        description="True if chunk_size or chunk_overlap differs from previously saved values",
    )


class GetSettingsResponse(BaseModel):
    """Response schema for GET /api/settings — API key masked."""

    provider: str
    model: str
    temperature: float
    max_tokens: int
    system_prompt: str
    top_k: int
    chunk_size: int
    chunk_overlap: int
    api_key: str | None = None  # "********" if set, null otherwise


class ModelsResponse(BaseModel):
    """Response schema for GET /api/settings/models/{provider}."""

    provider: str
    models: list[str]
    cached: bool = False
    error: str | None = None


# ============================================================
# Helpers
# ============================================================


def _get_settings_path() -> Path:
    """Return the path to the encrypted settings JSON file.

    Creates parent directories as needed.

    Returns:
        Path to settings.enc.json.
    """
    path = _SETTINGS_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def load_settings() -> dict[str, Any]:
    """Load settings from encrypted JSON file.

    Returns:
        Dictionary of settings, or empty dict if file doesn't exist.
    """
    path = _get_settings_path()
    if not path.exists():
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data: dict[str, Any] = json.load(f)
        return data
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to load settings: %s", e)
        return {}


def _save_settings(settings: dict[str, Any]) -> None:
    """Save settings to JSON file.

    Args:
        settings: Dictionary of settings to persist.
    """
    path = _get_settings_path()
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2)
    except OSError as e:
        logger.error("Failed to save settings: %s", e)
        raise HTTPException(status_code=500, detail="Failed to persist settings.")


# ============================================================
# Routes
# ============================================================


@router.post("/validate-key", response_model=ValidateKeyResponse)
async def validate_api_key(request: ValidateKeyRequest) -> ValidateKeyResponse:
    """Validate an API key by making a lightweight API call.

    For OpenAI, DeepSeek, and Anthropic: makes a GET request to the
    provider's models endpoint with the key in the auth header.
    For Ollama: always returns valid=True (skip validation).

    On success, encrypts the key with Fernet and saves to the secrets store.

    Args:
        request: Validation request with provider and API key.

    Returns:
        Validation result with validity status.
    """
    provider = request.provider.lower()

    # Skip validation for Ollama (local)
    if provider == "ollama":
        return ValidateKeyResponse(valid=True, provider=provider)

    # Validate provider is supported
    if provider not in _VALIDATION_URLS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported provider: {provider}. Must be one of: openai, deepseek, anthropic, ollama.",
        )

    url = _VALIDATION_URLS[provider]

    # Build auth header
    if provider == "anthropic":
        headers: dict[str, str] = {
            "x-api-key": request.api_key,
            "anthropic-version": "2023-06-01",
        }
    else:
        headers = {"Authorization": f"Bearer {request.api_key}"}

    # Validate via lightweight API call with 5s timeout
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(url, headers=headers)

        if resp.status_code in (200, 401, 403):
            # 200 = valid, 401/403 = invalid key
            valid = resp.status_code == 200
            if valid:
                # Save the API key to secrets store
                secrets = load_secrets()
                secrets[f"{provider}_api_key"] = encrypt_api_key(request.api_key)
                save_secrets(secrets)
                logger.info("API key validated and saved for provider: %s", provider)

            return ValidateKeyResponse(
                valid=valid,
                provider=provider,
                error=None if valid else "Invalid API key — authentication failed.",
            )
        else:
            logger.warning(
                "Unexpected status %d from %s validation", resp.status_code, provider
            )
            return ValidateKeyResponse(
                valid=False,
                provider=provider,
                error=f"Unexpected response from provider (status {resp.status_code}).",
            )

    except httpx.TimeoutException:
        logger.warning("Timeout validating key for provider: %s", provider)
        return ValidateKeyResponse(
            valid=False,
            provider=provider,
            error="Validation timed out. Check your network connection.",
        )
    except httpx.RequestError as e:
        logger.warning("Network error validating key for %s: %s", provider, e)
        return ValidateKeyResponse(
            valid=False,
            provider=provider,
            error=f"Network error: {e}",
        )


@router.get("", response_model=GetSettingsResponse)
async def get_settings() -> GetSettingsResponse:
    """Get the current application settings.

    Returns all settings except the actual API key value.
    API key is returned as "********" if set, or null if not.

    Returns:
        Current settings with masked API key.
    """
    settings = load_settings()
    secrets = load_secrets()

    # Determine if an API key is set for the current provider
    provider = str(settings.get("provider", "deepseek"))
    key_name = f"{provider}_api_key"
    api_key_masked: str | None = None
    if key_name in secrets or any(k.startswith(provider) for k in secrets):
        api_key_masked = "********"

    return GetSettingsResponse(
        provider=provider,
        model=str(settings.get("model", "gpt-4o-mini")),
        temperature=float(settings.get("temperature", 1.0)),
        max_tokens=int(settings.get("max_tokens", 2048)),
        system_prompt=str(
            settings.get(
                "system_prompt",
                "You are RAG-Studio AI assistant. Answer strictly based on the provided context. If you don't know, say so.",
            )
        ),
        top_k=int(settings.get("top_k", 5)),
        chunk_size=int(settings.get("chunk_size", 512)),
        chunk_overlap=int(settings.get("chunk_overlap", 64)),
        api_key=api_key_masked,
    )


@router.post("", response_model=SaveSettingsResponse)
async def save_settings(settings: SettingsData) -> SaveSettingsResponse:
    """Save application settings (all except API key).

    API key is handled separately via /api/settings/validate-key.
    Detects chunk-setting changes and signals them to the frontend.

    Args:
        settings: Settings payload to save.

    Returns:
        The saved settings with chunks_changed flag.
    """
    # v1.0: only DeepSeek is supported as a provider
    if settings.provider != "deepseek":
        logger.warning(
            "Rejected unsupported provider '%s' — only deepseek is allowed in v1.0. Falling back to deepseek.",
            settings.provider,
        )
        # Fall back to deepseek instead of raising an error
        settings.provider = "deepseek"

    current = load_settings()

    # Detect if chunk-related settings have changed (AC-010.5)
    prev_chunk_size = int(current.get("chunk_size", 512))
    prev_chunk_overlap = int(current.get("chunk_overlap", 64))
    chunks_changed = (
        settings.chunk_size != prev_chunk_size
        or settings.chunk_overlap != prev_chunk_overlap
    )

    current["provider"] = settings.provider
    current["model"] = settings.model
    current["temperature"] = settings.temperature
    current["max_tokens"] = settings.max_tokens
    current["system_prompt"] = settings.system_prompt
    current["top_k"] = settings.top_k
    current["chunk_size"] = settings.chunk_size
    current["chunk_overlap"] = settings.chunk_overlap

    _save_settings(current)
    logger.info(
        "Settings saved: provider=%s, model=%s, chunks_changed=%s",
        settings.provider,
        settings.model,
        chunks_changed,
    )

    return SaveSettingsResponse(
        provider=settings.provider,
        model=settings.model,
        temperature=settings.temperature,
        max_tokens=settings.max_tokens,
        system_prompt=settings.system_prompt,
        top_k=settings.top_k,
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
        chunks_changed=chunks_changed,
    )


@router.get("/models/{provider}", response_model=ModelsResponse)
async def get_models(provider: str) -> ModelsResponse:
    """Get available models for a provider with daily caching.

    Checks the local cache first. If the cache is valid (< 24 hours old),
    returns cached models. Otherwise, fetches from the provider API.

    For Anthropic (which has no /v1/models endpoint), uses a lightweight
    auth check and returns the hardcoded fallback list.

    Args:
        provider: Provider name (openai, deepseek, anthropic, ollama).

    Returns:
        ModelsResponse with the model list and cache status.
    """
    provider = provider.lower()
    supported = get_supported_providers()
    if provider not in supported:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unsupported provider: {provider}. "
                f"Must be one of: {', '.join(sorted(supported))}."
            ),
        )

    # Check cache
    cache = load_models_cache()
    cached_entry: dict[str, Any] | None = cache.get(provider)

    if is_cache_valid(cached_entry) and cached_entry is not None:
        models: list[str] = cached_entry.get("models", [])
        if models:
            return ModelsResponse(provider=provider, models=models, cached=True)

    # Try fetching from provider API.
    # The outer Fernet layer is decrypted by load_secrets(), but each
    # individual key value was encrypted separately by validate_api_key().
    # We must decrypt the inner value to get the real API key.
    secrets = load_secrets()
    encrypted_key = secrets.get(f"{provider}_api_key")
    api_key: str | None = decrypt_api_key(encrypted_key) if encrypted_key else None

    fetched_models, error = await get_models_for_provider(provider, api_key)

    # Save to cache if we got models without error
    if fetched_models and not error:
        cache[provider] = {
            "models": fetched_models,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }
        save_models_cache(cache)
        return ModelsResponse(provider=provider, models=fetched_models, cached=False)

    # Fallback to hardcoded list
    fallback = get_fallback_models(provider)
    return ModelsResponse(
        provider=provider,
        models=fallback,
        cached=False,
        error=error if error else "Could not fetch models; using defaults.",
    )
