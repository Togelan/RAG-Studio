"""Validated chunking-settings contract and persistence migration helpers."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Final, Literal, TypedDict

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator

CHUNK_SIZE_PRESETS: Final[tuple[int, ...]] = (256, 512, 1024)
CHUNK_OVERLAP_PRESETS: Final[tuple[int, ...]] = (32, 64, 128)
PARENT_SIZE_PRESETS: Final[tuple[int, ...]] = (512, 1024, 2048, 4096)
WINDOW_SENTENCE_PRESETS: Final[tuple[int, ...]] = (1, 2, 3)

ChunkingStrategy = Literal["static", "recursive", "parent_document", "sentence_window"]


class ChunkingPayload(TypedDict):
    """Versioned chunking representation persisted inside application settings."""

    schema_version: int
    strategy: ChunkingStrategy
    chunk_size: int
    chunk_overlap: int
    parent_size: int | None
    window_sentences: int | None


class ChunkingPersistence(TypedDict):
    """Settings fields written for nested and legacy readers."""

    chunk_size: int
    chunk_overlap: int
    chunking: ChunkingPayload


class ChunkingSettings(BaseModel):
    """Normalized global chunking configuration for all supported strategies."""

    model_config = ConfigDict(populate_by_name=True, frozen=True)

    schema_version: Literal[1] = 1
    strategy: ChunkingStrategy = "recursive"
    chunk_size: int = Field(
        default=512,
        validation_alias=AliasChoices("chunk_size", "child_size"),
    )
    chunk_overlap: int = Field(
        default=64,
        validation_alias=AliasChoices("chunk_overlap", "child_overlap"),
    )
    parent_size: int | None = None
    window_sentences: int | None = None

    @model_validator(mode="after")
    def validate_strategy_parameters(self) -> ChunkingSettings:
        """Enforce bounded presets and relationships at the configuration boundary."""
        if self.chunk_size not in CHUNK_SIZE_PRESETS and self.chunk_size != 128:
            raise ValueError("chunk_size must use a supported preset")
        if self.chunk_overlap not in CHUNK_OVERLAP_PRESETS and self.chunk_overlap != 0:
            raise ValueError("chunk_overlap must use a supported preset")
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("chunk_overlap must be smaller than chunk_size")
        if self.parent_size is not None and self.parent_size not in PARENT_SIZE_PRESETS:
            raise ValueError("parent_size must use a supported preset")
        if (
            self.window_sentences is not None
            and self.window_sentences not in WINDOW_SENTENCE_PRESETS
        ):
            raise ValueError("window_sentences must use a supported preset")
        if self.strategy == "parent_document":
            parent_size = self.parent_size or 2048
            if parent_size < self.chunk_size:
                raise ValueError("parent_size must be at least chunk_size")
        return self

    @property
    def fingerprint(self) -> str:
        """Return a stable digest of the normalized configuration."""
        canonical = json.dumps(
            self.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
        )
        return hashlib.sha256(canonical.encode()).hexdigest()


def read_chunking_settings(settings: Mapping[str, object]) -> ChunkingSettings:
    """Read nested settings or migrate legacy flat values as recursive settings."""
    nested = settings.get("chunking")
    if isinstance(nested, Mapping):
        return ChunkingSettings.model_validate(nested)
    return ChunkingSettings.model_validate(
        {
            "strategy": "recursive",
            "chunk_size": settings.get("chunk_size", 512),
            "chunk_overlap": settings.get("chunk_overlap", 64),
        }
    )


def merge_chunking_settings(
    previous: ChunkingSettings, submitted: ChunkingSettings
) -> ChunkingSettings:
    """Merge a submitted active strategy while retaining inactive saved values."""
    return ChunkingSettings(
        schema_version=submitted.schema_version,
        strategy=submitted.strategy,
        chunk_size=submitted.chunk_size,
        chunk_overlap=submitted.chunk_overlap,
        parent_size=submitted.parent_size or previous.parent_size,
        window_sentences=submitted.window_sentences or previous.window_sentences,
    )


def chunking_for_persistence(chunking: ChunkingSettings) -> ChunkingPersistence:
    """Return a nested versioned representation plus legacy flat compatibility fields."""
    nested: ChunkingPayload = {
        "schema_version": chunking.schema_version,
        "strategy": chunking.strategy,
        "chunk_size": chunking.chunk_size,
        "chunk_overlap": chunking.chunk_overlap,
        "parent_size": chunking.parent_size,
        "window_sentences": chunking.window_sentences,
    }
    return {
        "chunk_size": chunking.chunk_size,
        "chunk_overlap": chunking.chunk_overlap,
        "chunking": nested,
    }
