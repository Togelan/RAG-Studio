"""Bounded schemas for the isolated Stage 2 browser-QA runtime."""

from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class WorkloadProfile(BaseModel):
    """Fixed, reviewable workload used by Task 19 QA."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    profile: Literal["stage2-browser-v1"] = "stage2-browser-v1"
    latency_ms: Literal[50] = 50
    duration_seconds: Literal[30] = 30
    chat_engine: Literal["deterministic-fake-graph"] = "deterministic-fake-graph"
    concurrent_streams: Literal[10] = 10
    stream_hold_ms: Literal[1000] = 1000
    server_deadline_ms: Literal[100] = 100
    rate_limit_requests: Literal[30] = 30
    pagination_documents: Literal[1000] = 1000
    progress_polls_to_ready: Literal[2] = 2
    max_documents: Literal[20] = 20
    upload_samples: Literal[3] = 3
    duplicate_actions: tuple[Literal["cancel", "rename", "replace"], ...] = (
        "cancel",
        "rename",
        "replace",
    )
    status_oracles: tuple[int, ...] = (200, 202, 400, 404, 409, 422, 429, 503)


class ChunkSnapshot(BaseModel):
    """Redacted logical chunk metadata."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    chunk_index: int = Field(ge=0, le=99)
    page: int | None = Field(default=None, ge=0, le=10_000)
    token_count: int = Field(ge=0, le=100_000)
    text_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class DocumentSnapshot(BaseModel):
    """Canonical document state without raw content or filesystem paths."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    doc_id: str = Field(min_length=1, max_length=80)
    filename: str = Field(min_length=1, max_length=200)
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=0, le=50 * 1024 * 1024)
    chunk_size: int = Field(ge=128, le=4096)
    chunk_overlap: int = Field(ge=0, le=512)
    strategy: str = Field(min_length=1, max_length=40)
    chunks: tuple[ChunkSnapshot, ...] = Field(max_length=100)

    @field_validator("filename")
    @classmethod
    def filename_is_logical(cls, value: str) -> str:
        """Reject path-shaped or hidden snapshot filenames."""
        if value in {".", ".."} or "/" in value or "\\" in value:
            raise ValueError("filename must be a basename")
        return value


class SettingsSnapshot(BaseModel):
    """Logical settings with a boolean credential marker only."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: Literal["deepseek"] = "deepseek"
    model: Literal["qa-model"] = "qa-model"
    api_key_stored: bool = False
    temperature: float = Field(default=1.0, ge=0, le=2)
    max_tokens: int = Field(default=2048, ge=1, le=32_768)
    system_prompt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    top_k: int = Field(default=5, ge=1, le=100)
    chunk_size: int = Field(default=512, ge=128, le=4096)
    chunk_overlap: int = Field(default=64, ge=0, le=512)
    strategy: Literal["static", "recursive", "parent_document", "sentence_window"]


class LogicalSnapshot(BaseModel):
    """Canonical, redacted QA state transferable between disposable roots."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    project_id: str = Field(pattern=r"^rag-studio-stage2-qa-[0-9a-f]{8}$")
    settings: SettingsSnapshot
    documents: tuple[DocumentSnapshot, ...] = Field(max_length=20)
    workload: WorkloadProfile = WorkloadProfile()

    def canonical_bytes(self, *, ignore_project: bool = False) -> bytes:
        """Serialize deterministically for equality and hash checks."""
        payload = self.model_dump(mode="json")
        if ignore_project:
            payload["project_id"] = "rag-studio-stage2-qa-00000000"
        return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()

    def sha256(self, *, ignore_project: bool = False) -> str:
        """Return a stable logical-state digest."""
        return hashlib.sha256(
            self.canonical_bytes(ignore_project=ignore_project)
        ).hexdigest()
