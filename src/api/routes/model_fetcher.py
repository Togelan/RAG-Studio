"""Provider-specific model fetching and daily caching for the Settings API.

Provides:
- Cache helpers (load_models_cache, save_models_cache, is_cache_valid)
- Provider fetchers (fetch_ollama_models, fetch_openai_models, etc.)
- Hardcoded fallback model lists
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, cast

import httpx

logger = logging.getLogger(__name__)

# ============================================================
# Models cache
# ============================================================

_MODELS_CACHE_PATH = Path("data/models_cache.json")

_FALLBACK_MODELS: dict[str, list[str]] = {
    "openai": [
        "gpt-5.5",
        "gpt-5.5-pro",
        "gpt-5.4",
        "gpt-5.4-pro",
        "gpt-5.4-mini",
        "gpt-5.4-nano",
        "gpt-5.2",
        "gpt-5.2-pro",
        "gpt-5.1",
        "gpt-5",
        "gpt-5-mini",
        "gpt-5-nano",
        "gpt-5-pro",
        "o3-pro",
        "o3",
        "gpt-4.1",
        "gpt-4.1-mini",
        "gpt-4o-mini",
    ],
    "deepseek": [
        "deepseek-v4-flash",
        "deepseek-v4-pro",
    ],
    "anthropic": [
        "claude-fable-5",
        "claude-mythos-5",
        "claude-opus-4-8",
        "claude-opus-4-7",
        "claude-opus-4-6",
        "claude-opus-4-5",
        "claude-sonnet-5",
        "claude-sonnet-4-6",
        "claude-sonnet-4-5",
        "claude-haiku-4-5",
    ],
    "ollama": [],
}


def get_fallback_models(provider: str) -> list[str]:
    """Get the hardcoded fallback model list for a provider.

    Args:
        provider: Provider name.

    Returns:
        List of model name strings, or empty list if unknown.
    """
    return _FALLBACK_MODELS.get(provider, [])


def get_supported_providers() -> frozenset[str]:
    """Return the set of supported provider names."""
    return frozenset(_FALLBACK_MODELS.keys())


# ============================================================
# Cache Helpers
# ============================================================


def load_models_cache() -> dict[str, Any]:
    """Load the models cache from disk.

    Returns:
        Cache dictionary, or empty dict if not available.
    """
    if not _MODELS_CACHE_PATH.exists():
        return {}
    try:
        with open(_MODELS_CACHE_PATH, encoding="utf-8") as f:
            return cast("dict[str, Any]", json.load(f))
    except json.JSONDecodeError, OSError:
        return {}


def save_models_cache(cache: dict[str, Any]) -> None:
    """Save the models cache to disk.

    Args:
        cache: Cache dictionary to persist.
    """
    _MODELS_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(_MODELS_CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2)


def is_cache_valid(entry: dict[str, Any] | None) -> bool:
    """Check if a cache entry is still valid (less than 24 hours old).

    Args:
        entry: Cache entry dict with 'fetched_at' ISO timestamp.

    Returns:
        True if the entry exists and is less than 24 hours old.
    """
    if not entry or "fetched_at" not in entry:
        return False
    fetched = datetime.fromisoformat(entry["fetched_at"])
    return datetime.now(timezone.utc) - fetched < timedelta(hours=24)


# ============================================================
# Provider-Specific Model Fetching
# ============================================================


async def fetch_ollama_models() -> list[str]:
    """Fetch models from a local Ollama instance.

    Returns:
        List of model names, or empty list on failure.
    """
    url = "http://localhost:11434/api/tags"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(url)
            if resp.status_code == 200:
                data: dict[str, object] = resp.json()
                models_raw = data.get("models", [])
                if isinstance(models_raw, list):
                    return [
                        str(cast("dict[str, Any]", m)["name"])
                        for m in models_raw
                        if isinstance(m, dict) and "name" in m
                    ]
    except (httpx.TimeoutException, httpx.RequestError, OSError) as e:
        logger.warning("Failed to fetch Ollama models: %s", e)
    return []


async def fetch_openai_models(api_key: str) -> list[str]:
    """Fetch chat-capable models from OpenAI.

    Args:
        api_key: OpenAI API key.

    Returns:
        List of model IDs starting with 'gpt-', or empty list on failure.
    """
    url = "https://api.openai.com/v1/models"
    headers: dict[str, str] = {"Authorization": f"Bearer {api_key}"}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code == 200:
                data: dict[str, object] = resp.json()
                all_models = data.get("data", [])
                if isinstance(all_models, list):
                    return sorted(
                        [
                            str(cast("dict[str, Any]", m)["id"])
                            for m in all_models
                            if isinstance(m, dict)
                            and "id" in m
                            and str(cast("dict[str, Any]", m)["id"]).startswith("gpt-")
                        ]
                    )
    except (httpx.TimeoutException, httpx.RequestError, OSError) as e:
        logger.warning("Failed to fetch OpenAI models: %s", e)
    return []


async def fetch_deepseek_models(api_key: str) -> list[str]:
    """Fetch models from DeepSeek.

    Args:
        api_key: DeepSeek API key.

    Returns:
        List of model IDs, or empty list on failure.
    """
    url = "https://api.deepseek.com/v1/models"
    headers = {"Authorization": f"Bearer {api_key}"}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code == 200:
                data: dict[str, object] = resp.json()
                all_models = data.get("data", [])
                if isinstance(all_models, list):
                    return sorted(
                        [
                            str(cast("dict[str, Any]", m)["id"])
                            for m in all_models
                            if isinstance(m, dict)
                            and "id" in m
                            and str(cast("dict[str, Any]", m)["id"]).startswith(
                                "deepseek-"
                            )
                        ]
                    )
    except (httpx.TimeoutException, httpx.RequestError, OSError) as e:
        logger.warning("Failed to fetch DeepSeek models: %s", e)
    return []


async def check_anthropic_auth(api_key: str) -> bool:
    """Check if the Anthropic API key is valid by making a lightweight call.

    Args:
        api_key: Anthropic API key.

    Returns:
        True if the key appears valid.
    """
    url = "https://api.anthropic.com/v1/messages"
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }
    payload: dict[str, object] = {
        "model": "claude-haiku-4-5",
        "max_tokens": 1,
        "messages": [{"role": "user", "content": "Hi"}],
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, headers=headers, json=payload)
            return resp.status_code in (200, 429)  # 429 = rate-limited but auth valid
    except httpx.TimeoutException, httpx.RequestError, OSError:
        return False


# ============================================================
# Orchestrator
# ============================================================


async def get_models_for_provider(
    provider: str,
    api_key: str | None,
) -> tuple[list[str], str | None]:
    """Fetch models for a provider, with error handling.

    Args:
        provider: Provider name (openai, deepseek, anthropic, ollama).
        api_key: API key for the provider, None if not configured.

    Returns:
        Tuple of (models list, error string or None).
    """
    if provider == "ollama":
        return await fetch_ollama_models(), None

    if provider == "openai":
        if api_key:
            return await fetch_openai_models(api_key), None
        return [], "No API key configured for OpenAI."

    if provider == "deepseek":
        if api_key:
            return await fetch_deepseek_models(api_key), None
        return [], "No API key configured for DeepSeek."

    if provider == "anthropic":
        if api_key:
            auth_ok = await check_anthropic_auth(api_key)
            if auth_ok:
                return list(_FALLBACK_MODELS["anthropic"]), None
            return [], "Anthropic API key validation failed."
        return [], "No API key configured for Anthropic."

    return [], f"Unknown provider: {provider}"
