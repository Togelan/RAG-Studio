"""Typed settings and snapshot transformations for the Stage 2 QA runtime."""

from __future__ import annotations

import hashlib

from scripts.qa.stage2_qa_schema import SettingsSnapshot
from scripts.qa.stage2_qa_types import (
    ChunkingSettings,
    ChunkingStrategy,
    SavedSettings,
    SettingsPayload,
    SettingsResponse,
)


def default_settings() -> SettingsPayload:
    """Return the credential-free production-shaped settings fixture."""
    return {
        "provider": "deepseek",
        "model": "qa-model",
        "temperature": 1.0,
        "max_tokens": 2048,
        "system_prompt": "Use only deterministic QA context.",
        "top_k": 5,
        "chunk_size": 512,
        "chunk_overlap": 64,
        "chunking": {
            "schema_version": 1,
            "strategy": "recursive",
            "chunk_size": 512,
            "chunk_overlap": 64,
            "parent_size": 2048,
            "window_sentences": 2,
        },
    }


def settings_response(settings: SettingsPayload) -> SettingsResponse:
    return {**settings, "api_key": None}


def save_settings(settings: SettingsPayload, payload: SettingsPayload) -> SavedSettings:
    return {**payload, "chunks_changed": settings["chunking"] != payload["chunking"]}


def snapshot_settings(
    settings: SettingsPayload,
    prompt_sha256_override: str | None,
) -> SettingsSnapshot:
    prompt_hash = (
        prompt_sha256_override
        or hashlib.sha256(settings["system_prompt"].encode()).hexdigest()
    )
    return SettingsSnapshot(
        system_prompt_sha256=prompt_hash,
        temperature=settings["temperature"],
        max_tokens=settings["max_tokens"],
        top_k=settings["top_k"],
        chunk_size=settings["chunk_size"],
        chunk_overlap=settings["chunk_overlap"],
        strategy=settings["chunking"]["strategy"],
    )


def restore_settings(snapshot: SettingsSnapshot) -> SettingsPayload:
    settings = default_settings()
    chunking: ChunkingSettings = {
        **settings["chunking"],
        "strategy": normalize_strategy(snapshot.strategy),
    }
    return {
        **settings,
        "temperature": snapshot.temperature,
        "max_tokens": snapshot.max_tokens,
        "top_k": snapshot.top_k,
        "chunk_size": snapshot.chunk_size,
        "chunk_overlap": snapshot.chunk_overlap,
        "chunking": chunking,
    }


def normalize_strategy(value: str) -> ChunkingStrategy:
    if value == "static":
        return "static"
    if value == "recursive":
        return "recursive"
    if value == "parent_document":
        return "parent_document"
    if value == "sentence_window":
        return "sentence_window"
    raise ValueError("snapshot chunking strategy is invalid")
