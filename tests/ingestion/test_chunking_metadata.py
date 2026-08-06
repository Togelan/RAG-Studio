"""Metadata contracts for deterministic strategy search units."""

from __future__ import annotations

from src.ingestion.chunker import chunk_csv_rows
from src.ingestion.chunking_models import ChunkingConfig, ChunkingStrategy
from src.ingestion.strategies import (
    chunk_csv_rows_with_strategy,
    chunk_text_with_strategy,
)


def test_all_text_unit_ranges_reproduce_the_original_source_text() -> None:
    # Given: source text with repeated content and paragraph whitespace.
    text = "Repeated sentence. Repeated sentence.\n\nFinal paragraph."

    # When: every text strategy creates search units.
    strategy_units = [
        chunk_text_with_strategy(
            text,
            ChunkingConfig(
                strategy=strategy,
                chunk_size=24,
                chunk_overlap=4,
                parent_size=40,
                source_id="ranges",
            ),
        )
        for strategy in ChunkingStrategy
        if strategy is not ChunkingStrategy.CSV_ROW
    ]

    # Then: every persisted range points to exactly its search text.
    assert all(
        unit.text_range.text(text) == unit.text
        for units in strategy_units
        for unit in units
    )


def test_identifiers_change_for_source_strategy_and_range() -> None:
    # Given: otherwise identical static runs with one identity input changed.
    base = ChunkingConfig(
        strategy=ChunkingStrategy.STATIC,
        chunk_size=5,
        chunk_overlap=0,
        source_id="source-a",
    )
    other_source = ChunkingConfig(
        strategy=ChunkingStrategy.STATIC,
        chunk_size=5,
        chunk_overlap=0,
        source_id="source-b",
    )
    recursive = ChunkingConfig(
        strategy=ChunkingStrategy.RECURSIVE,
        chunk_size=5,
        chunk_overlap=0,
        source_id="source-a",
    )

    # When: identifiers are generated from each run.
    base_units = chunk_text_with_strategy("abcdefghijabcdefghij", base)
    source_units = chunk_text_with_strategy("abcdefghijabcdefghij", other_source)
    recursive_units = chunk_text_with_strategy("abcdefghijabcdefghij", recursive)

    # Then: source, strategy, and range participate in identity.
    assert base_units[0].unit_id != source_units[0].unit_id
    assert base_units[0].unit_id != recursive_units[0].unit_id
    assert len({unit.unit_id for unit in base_units}) == len(base_units)


def test_parent_and_window_metadata_is_deterministic_across_runs() -> None:
    # Given: two paragraphs and each metadata-bearing strategy.
    text = "Alpha one. Alpha two.\n\nBeta one. Beta two."
    configs = (
        ChunkingConfig(
            strategy=ChunkingStrategy.PARENT_DOCUMENT,
            chunk_size=16,
            chunk_overlap=2,
            parent_size=32,
            source_id="metadata",
        ),
        ChunkingConfig(
            strategy=ChunkingStrategy.SENTENCE_WINDOW,
            chunk_size=16,
            chunk_overlap=2,
            window_sentences=1,
            source_id="metadata",
        ),
    )

    # When: each strategy runs twice.
    paired_runs = [
        (
            chunk_text_with_strategy(text, config),
            chunk_text_with_strategy(text, config),
        )
        for config in configs
    ]

    # Then: complete immutable records compare equal and stay paragraph-local.
    assert all(first == second for first, second in paired_runs)
    assert all(
        unit.paragraph_range is not None
        and unit.paragraph_range.start <= unit.text_range.start
        and unit.text_range.end <= unit.paragraph_range.end
        for first, _second in paired_runs
        for unit in first
    )


def test_csv_rows_remain_atomic_and_receive_csv_row_strategy_metadata() -> None:
    # Given: normal, oversized, and blank CSV row text.
    rows = ["Name: Alice | Age: 30", "x" * 600, "   "]

    # When: legacy and metadata-aware CSV surfaces process the rows.
    legacy = chunk_csv_rows(rows, chunk_size=32)
    units = chunk_csv_rows_with_strategy(rows, source_id="table", max_units=10)

    # Then: legacy strings are unchanged and metadata marks atomic CSV rows.
    assert legacy == rows[:2]
    assert [unit.text for unit in units] == legacy
    assert all(unit.strategy is ChunkingStrategy.CSV_ROW for unit in units)
    assert all(unit.is_atomic for unit in units)
    assert len(units[1].text) == 600
