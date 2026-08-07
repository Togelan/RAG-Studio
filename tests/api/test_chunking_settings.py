from __future__ import annotations

from itertools import product

import pytest
from pydantic import ValidationError

from src.api.chunking_settings import (
    ChunkingSettings,
    merge_chunking_settings,
)

EXPECTED_CHUNK_SIZE_PRESETS = (256, 512, 1024)
EXPECTED_CHUNK_OVERLAP_PRESETS = (32, 64, 128)
EXPECTED_PARENT_SIZE_PRESETS = (512, 1024, 2048, 4096)
EXPECTED_WINDOW_SENTENCE_PRESETS = (1, 2, 3)


def _fixed_payloads() -> list[dict[str, int | str]]:
    return [
        {"strategy": strategy, "chunk_size": size, "chunk_overlap": overlap}
        for strategy, size, overlap in product(
            ("static", "recursive"),
            EXPECTED_CHUNK_SIZE_PRESETS,
            EXPECTED_CHUNK_OVERLAP_PRESETS,
        )
    ]


def _parent_payloads() -> list[dict[str, int | str]]:
    return [
        {
            "strategy": "parent_document",
            "child_size": child_size,
            "child_overlap": child_overlap,
            "parent_size": parent_size,
        }
        for child_size, child_overlap, parent_size in product(
            EXPECTED_CHUNK_SIZE_PRESETS,
            EXPECTED_CHUNK_OVERLAP_PRESETS,
            EXPECTED_PARENT_SIZE_PRESETS,
        )
        if parent_size >= child_size
    ]


def _window_payloads() -> list[dict[str, int | str]]:
    return [
        {
            "strategy": "sentence_window",
            "chunk_size": size,
            "chunk_overlap": overlap,
            "window_sentences": window_sentences,
        }
        for size, overlap, window_sentences in product(
            EXPECTED_CHUNK_SIZE_PRESETS,
            EXPECTED_CHUNK_OVERLAP_PRESETS,
            EXPECTED_WINDOW_SENTENCE_PRESETS,
        )
    ]


@pytest.mark.parametrize(
    "payload", _fixed_payloads() + _parent_payloads() + _window_payloads()
)
def test_chunking_settings_accepts_every_valid_preset(
    payload: dict[str, int | str],
) -> None:
    # Given: one complete valid configuration.
    # When: it crosses the Pydantic boundary.
    settings = ChunkingSettings.model_validate(payload)

    # Then: the strategy and canonical size fields are retained.
    assert settings.strategy == payload["strategy"]
    if payload["strategy"] == "parent_document":
        assert settings.chunk_overlap == payload["child_overlap"]
    else:
        assert settings.chunk_overlap == payload["chunk_overlap"]


@pytest.mark.parametrize(
    "payload",
    (
        {"strategy": "unknown", "chunk_size": 512, "chunk_overlap": 64},
        {"strategy": "static", "chunk_size": 384, "chunk_overlap": 64},
        {"strategy": "recursive", "chunk_size": 512, "chunk_overlap": 512},
        {
            "strategy": "parent_document",
            "child_size": 1024,
            "child_overlap": 64,
            "parent_size": 512,
        },
        {
            "strategy": "sentence_window",
            "chunk_size": 512,
            "chunk_overlap": 64,
            "window_sentences": 0,
        },
    ),
)
def test_chunking_settings_rejects_invalid_strategy_or_relation(
    payload: dict[str, int | str],
) -> None:
    # Given: an invalid external configuration.
    # When / Then: parsing fails before it reaches consumers.
    with pytest.raises(ValidationError):
        ChunkingSettings.model_validate(payload)


def test_merge_preserves_inactive_strategy_values() -> None:
    # Given: parent and window values saved by earlier selections.
    previous = ChunkingSettings(
        strategy="parent_document",
        chunk_size=512,
        chunk_overlap=64,
        parent_size=2048,
        window_sentences=3,
    )
    submitted = ChunkingSettings(
        strategy="sentence_window",
        chunk_size=1024,
        chunk_overlap=128,
        window_sentences=2,
    )

    # When: the active selection is merged for persistence.
    merged = merge_chunking_settings(previous, submitted)

    # Then: inactive parent configuration survives unchanged.
    assert merged.parent_size == 2048
    assert merged.window_sentences == 2


def test_fingerprint_is_deterministic_and_detects_changes() -> None:
    # Given: semantically identical mappings with different source order.
    first = ChunkingSettings.model_validate(
        {"strategy": "recursive", "chunk_size": 512, "chunk_overlap": 64}
    )
    second = ChunkingSettings.model_validate(
        {"chunk_overlap": 64, "chunk_size": 512, "strategy": "recursive"}
    )
    changed = ChunkingSettings.model_validate(
        {"strategy": "static", "chunk_size": 512, "chunk_overlap": 64}
    )

    # When / Then: canonical settings fingerprint consistently distinguishes state.
    assert first.fingerprint == second.fingerprint
    assert first.fingerprint != changed.fingerprint
