"""Dispatch normalized ingestion settings through deterministic chunk strategies."""

from __future__ import annotations

from dataclasses import dataclass

from src.api.chunking_settings import ChunkingSettings
from src.ingestion.chunking_models import (
    DEFAULT_PARENT_SIZE,
    DEFAULT_WINDOW_SENTENCES,
    ChunkingConfig,
    ChunkingStrategy,
    ChunkUnit,
)
from src.ingestion.strategies import (
    chunk_csv_rows_with_strategy,
    chunk_text_with_strategy,
)
from src.vector_store.models import JsonValue


@dataclass(frozen=True, slots=True)
class ChunkingBatch:
    """One immutable strategy result and the source used by its ranges."""

    units: tuple[ChunkUnit, ...]
    source_text: str
    strategy: str
    settings: ChunkingSettings

    @property
    def texts(self) -> tuple[str, ...]:
        """Return embedding inputs in deterministic unit order."""
        return tuple(unit.text for unit in self.units)


def dispatch_text(
    text: str, settings: ChunkingSettings, source_id: str
) -> ChunkingBatch:
    """Build text search units with the selected normalized strategy."""
    parent_size = None
    if settings.strategy == "parent_document":
        parent_size = settings.parent_size or DEFAULT_PARENT_SIZE
    window_sentences = None
    if settings.strategy == "sentence_window":
        window_sentences = settings.window_sentences or DEFAULT_WINDOW_SENTENCES
    config = ChunkingConfig(
        strategy=ChunkingStrategy(settings.strategy),
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
        parent_size=parent_size,
        window_sentences=window_sentences,
        source_id=source_id,
    )
    return ChunkingBatch(
        units=tuple(chunk_text_with_strategy(text, config)),
        source_text=text,
        strategy=config.strategy.value,
        settings=settings,
    )


def dispatch_csv(
    row_texts: list[str], settings: ChunkingSettings, source_id: str
) -> ChunkingBatch:
    """Build atomic CSV-row units independently of the selected text strategy."""
    return ChunkingBatch(
        units=tuple(chunk_csv_rows_with_strategy(row_texts, source_id=source_id)),
        source_text="",
        strategy=ChunkingStrategy.CSV_ROW.value,
        settings=settings,
    )


def settings_payload(settings: ChunkingSettings) -> dict[str, JsonValue]:
    """Serialize the complete normalized settings snapshot for persistence."""
    return {
        "schema_version": settings.schema_version,
        "strategy": settings.strategy,
        "chunk_size": settings.chunk_size,
        "chunk_overlap": settings.chunk_overlap,
        "parent_size": settings.parent_size,
        "window_sentences": settings.window_sentences,
    }


def unit_payload(batch: ChunkingBatch, unit: ChunkUnit) -> dict[str, JsonValue]:
    """Serialize source ranges and expansion fields for one persisted unit."""
    payload: dict[str, JsonValue] = {
        "unit_id": unit.unit_id,
        "strategy": unit.strategy.value,
        "schema_version": batch.settings.schema_version,
        "chunking_fingerprint": batch.settings.fingerprint,
        "chunking_settings": settings_payload(batch.settings),
        "start_offset": unit.text_range.start,
        "end_offset": unit.text_range.end,
        "is_atomic": unit.is_atomic,
    }
    if unit.paragraph_range is not None:
        payload["paragraph_index"] = unit.paragraph_index
        payload["paragraph_start_offset"] = unit.paragraph_range.start
        payload["paragraph_end_offset"] = unit.paragraph_range.end
    if unit.parent_range is not None:
        payload["search_unit_type"] = "child"
        payload["parent_id"] = unit.parent_id
        payload["parent_start_offset"] = unit.parent_range.start
        payload["parent_end_offset"] = unit.parent_range.end
        payload["parent_text"] = unit.parent_range.text(batch.source_text)
    if unit.sentence_index is not None:
        payload["sentence_index"] = unit.sentence_index
    if unit.window_range is not None:
        payload["window_start_offset"] = unit.window_range.start
        payload["window_end_offset"] = unit.window_range.end
        payload["window_text"] = unit.window_range.text(batch.source_text)
    return payload
