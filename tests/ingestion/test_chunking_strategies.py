"""Behavioral contracts for the bounded text chunking strategies."""

from __future__ import annotations

import pytest

from src.ingestion.chunking_models import (
    ChunkingConfig,
    ChunkingLimitExceeded,
    ChunkingStrategy,
)
from src.ingestion.strategies import chunk_text_with_strategy


def test_static_strategy_has_deterministic_overlapping_ranges_and_identifiers() -> None:
    # Given: fixed text and a static configuration.
    config = ChunkingConfig(
        strategy=ChunkingStrategy.STATIC,
        chunk_size=5,
        chunk_overlap=2,
        source_id="fixture",
    )

    # When: the same text is chunked twice.
    first = chunk_text_with_strategy("abcdefghij", config)
    second = chunk_text_with_strategy("abcdefghij", config)

    # Then: fixed slicing, offsets, and stable identifiers are reproducible.
    assert [unit.text for unit in first] == ["abcde", "defgh", "ghij"]
    assert [(unit.text_range.start, unit.text_range.end) for unit in first] == [
        (0, 5),
        (3, 8),
        (6, 10),
    ]
    assert [unit.unit_id for unit in first] == [unit.unit_id for unit in second]


def test_recursive_strategy_matches_the_legacy_compatibility_facade() -> None:
    # Given: a legacy-compatible recursive configuration.
    from src.ingestion.chunker import chunk_text

    text = "Sentence one has enough content. Sentence two also has enough content."
    config = ChunkingConfig(
        strategy=ChunkingStrategy.RECURSIVE,
        chunk_size=40,
        chunk_overlap=8,
    )

    # When: both public surfaces split the same input.
    units = chunk_text_with_strategy(text, config)
    legacy_chunks = chunk_text(text, chunk_size=40, chunk_overlap=8)

    # Then: the strategy domain preserves the established recursive output.
    assert [unit.text for unit in units] == legacy_chunks


def test_non_parent_strategies_allow_large_chunk_sizes_without_parent_bounds() -> None:
    # Given: a valid static configuration at the maximum supported chunk size.
    config = ChunkingConfig(
        strategy=ChunkingStrategy.STATIC,
        chunk_size=4096,
        chunk_overlap=64,
        source_id="large-static",
    )

    # When: the text crosses the internal strategy boundary.
    units = chunk_text_with_strategy("x" * 5000, config)

    # Then: parent-document-only validation does not block large static chunks.
    assert len(units) == 2
    assert all(len(unit.text) <= config.chunk_size for unit in units)


def test_parent_document_strategy_keeps_children_inside_bounded_parents() -> None:
    # Given: two paragraphs including a blank separator.
    text = (
        "First sentence is intentionally long. Second sentence stays here.\n\n"
        "Third sentence belongs only to paragraph two."
    )
    config = ChunkingConfig(
        strategy=ChunkingStrategy.PARENT_DOCUMENT,
        chunk_size=36,
        chunk_overlap=8,
        parent_size=64,
        source_id="parent-fixture",
    )

    # When: parent-document search units are created.
    units = chunk_text_with_strategy(text, config)

    # Then: each child is bounded and references only its own paragraph parent.
    assert units
    assert all(len(unit.text) <= config.chunk_size for unit in units)
    assert {unit.paragraph_index for unit in units} == {0, 1}
    assert all(unit.parent_id is not None for unit in units)
    assert all(unit.parent_range is not None for unit in units)
    assert all(
        unit.parent_range.start
        <= unit.text_range.start
        < unit.text_range.end
        <= unit.parent_range.end
        for unit in units
        if unit.parent_range is not None
    )


def test_sentence_window_strategy_never_builds_a_window_across_paragraphs() -> None:
    # Given: neighboring sentences separated into two paragraphs.
    text = "One is first. Two is second.\n\nThree is elsewhere. Four is last."
    config = ChunkingConfig(
        strategy=ChunkingStrategy.SENTENCE_WINDOW,
        chunk_size=40,
        chunk_overlap=8,
        window_sentences=1,
    )

    # When: sentence-window search units are created.
    units = chunk_text_with_strategy(text, config)

    # Then: every window remains in the unit's paragraph.
    assert all(unit.window_range is not None for unit in units)
    assert all(
        unit.window_range.start >= unit.paragraph_range.start
        and unit.window_range.end <= unit.paragraph_range.end
        for unit in units
        if unit.window_range is not None and unit.paragraph_range is not None
    )


def test_sentence_window_default_expands_two_sentences_per_side_within_paragraph() -> (
    None
):
    # Given: a middle sentence with two neighbors on each side in one paragraph.
    text = "S0. S1. S2. S3. S4.\n\nOutside the sentence window paragraph."
    config = ChunkingConfig(
        strategy=ChunkingStrategy.SENTENCE_WINDOW,
        chunk_size=100,
        chunk_overlap=0,
    )

    # When: sentence-window units are created without an explicit window override.
    units = chunk_text_with_strategy(text, config)

    # Then: the middle sentence spans exactly its two adjacent neighbors per side.
    middle = units[2]
    assert middle.window_range is not None
    assert middle.paragraph_range is not None
    assert middle.window_range.text(text) == "S0. S1. S2. S3. S4."
    assert middle.window_range == middle.paragraph_range


def test_oversized_sentence_uses_bounded_character_fallback() -> None:
    # Given: one malformed, punctuation-free sentence larger than the hard size.
    config = ChunkingConfig(
        strategy=ChunkingStrategy.SENTENCE_WINDOW,
        chunk_size=128,
        chunk_overlap=16,
        window_sentences=1,
    )

    # When: the oversized text is segmented.
    units = chunk_text_with_strategy("x" * 20_000, config)

    # Then: fallback units are bounded rather than discarded or oversized.
    assert len(units) > 1
    assert all(len(unit.text) <= config.chunk_size for unit in units)


def test_strategy_raises_at_the_configured_unit_cap() -> None:
    # Given: input that requires more static units than the configured cap.
    config = ChunkingConfig(
        strategy=ChunkingStrategy.STATIC,
        chunk_size=4,
        chunk_overlap=0,
        max_units=2,
    )

    # When / Then: the bounded failure mode is explicit.
    with pytest.raises(ChunkingLimitExceeded):
        chunk_text_with_strategy("abcdefghij", config)


def test_parent_document_splits_an_oversized_paragraph_into_bounded_parents() -> None:
    # Given: one paragraph whose only sentence exceeds both parent and child bounds.
    text = "z" * 95
    config = ChunkingConfig(
        strategy=ChunkingStrategy.PARENT_DOCUMENT,
        chunk_size=20,
        chunk_overlap=5,
        parent_size=40,
    )

    # When: parent-document units are formed with the character fallback.
    units = chunk_text_with_strategy(text, config)

    # Then: every child and parent is bounded and source-backed.
    assert units
    assert all(len(unit.text) <= 20 for unit in units)
    assert all(unit.parent_range is not None for unit in units)
    assert all(
        unit.parent_range.end - unit.parent_range.start <= 40
        for unit in units
        if unit.parent_range is not None
    )
    assert all(unit.text_range.text(text) == unit.text for unit in units)


def test_sentence_window_emits_one_search_unit_per_sentence() -> None:
    # Given: three bounded sentences in one paragraph.
    text = "First sentence. Second sentence! Third sentence?"
    config = ChunkingConfig(
        strategy=ChunkingStrategy.SENTENCE_WINDOW,
        chunk_size=32,
        chunk_overlap=4,
        window_sentences=1,
    )

    # When: sentence search units are formed.
    units = chunk_text_with_strategy(text, config)

    # Then: each sentence is searchable and the middle window includes its neighbors.
    assert [unit.text for unit in units] == [
        "First sentence.",
        "Second sentence!",
        "Third sentence?",
    ]
    assert units[1].window_range is not None
    assert units[1].window_range.text(text) == text


def test_empty_and_blank_only_text_produces_no_units() -> None:
    # Given: text without any content.
    config = ChunkingConfig(strategy=ChunkingStrategy.STATIC)

    # When / Then: no invalid empty ranges or units are invented.
    assert chunk_text_with_strategy("", config) == []
    assert chunk_text_with_strategy(" \n\n\t", config) == []
