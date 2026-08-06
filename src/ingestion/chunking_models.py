"""Typed values shared by deterministic ingestion chunking strategies."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

DEFAULT_CHUNK_SIZE: Final = 512
DEFAULT_CHUNK_OVERLAP: Final = 64
DEFAULT_PARENT_SIZE: Final = 2_048
DEFAULT_WINDOW_SENTENCES: Final = 2
MAX_CONTEXT_UNITS: Final = 10_000


class ChunkingStrategy(StrEnum):
    """Supported strategy markers persisted with ingestion search units."""

    STATIC = "static"
    RECURSIVE = "recursive"
    PARENT_DOCUMENT = "parent_document"
    SENTENCE_WINDOW = "sentence_window"
    CSV_ROW = "csv_row"


@dataclass(frozen=True, slots=True)
class ChunkingConfigurationError(ValueError):
    """Raised when a strategy configuration violates its bounded contract."""

    detail: str

    def __str__(self) -> str:
        return self.detail


@dataclass(frozen=True, slots=True)
class ChunkingLimitExceeded(ValueError):
    """Raised when one document produces more units than its hard cap."""

    max_units: int

    def __str__(self) -> str:
        return f"chunking_unit_limit_exceeded:{self.max_units}"


@dataclass(frozen=True, slots=True)
class TextRange:
    """Half-open character range into the original parsed text."""

    start: int
    end: int

    def __post_init__(self) -> None:
        if self.start < 0 or self.end <= self.start:
            raise ChunkingConfigurationError("invalid_text_range")

    def text(self, source: str) -> str:
        """Return the original source substring covered by this range."""
        return source[self.start : self.end]


@dataclass(frozen=True, slots=True)
class ChunkingConfig:
    """Validated internal configuration for one deterministic strategy run."""

    strategy: ChunkingStrategy = ChunkingStrategy.RECURSIVE
    chunk_size: int = DEFAULT_CHUNK_SIZE
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP
    parent_size: int = DEFAULT_PARENT_SIZE
    window_sentences: int = DEFAULT_WINDOW_SENTENCES
    max_units: int = MAX_CONTEXT_UNITS
    source_id: str = "document"

    def __post_init__(self) -> None:
        if self.strategy is ChunkingStrategy.CSV_ROW:
            raise ChunkingConfigurationError("csv_row_is_not_a_text_strategy")
        if self.chunk_size <= 0:
            raise ChunkingConfigurationError("chunk_size_must_be_positive")
        if self.chunk_overlap < 0 or self.chunk_overlap >= self.chunk_size:
            raise ChunkingConfigurationError("chunk_overlap_must_be_smaller_than_chunk_size")
        if self.parent_size < self.chunk_size:
            raise ChunkingConfigurationError("parent_size_must_cover_one_child")
        if self.window_sentences < 0:
            raise ChunkingConfigurationError("window_sentences_must_not_be_negative")
        if self.max_units <= 0 or self.max_units > MAX_CONTEXT_UNITS:
            raise ChunkingConfigurationError("max_units_must_be_between_one_and_hard_cap")
        if not self.source_id:
            raise ChunkingConfigurationError("source_id_must_not_be_empty")


@dataclass(frozen=True, slots=True)
class ChunkUnit:
    """One strategy search unit plus deterministic expansion metadata."""

    unit_id: str
    text: str
    strategy: ChunkingStrategy
    text_range: TextRange
    paragraph_index: int | None = None
    paragraph_range: TextRange | None = None
    parent_id: str | None = None
    parent_range: TextRange | None = None
    sentence_index: int | None = None
    window_range: TextRange | None = None
    is_atomic: bool = False
