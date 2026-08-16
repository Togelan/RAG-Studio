"""Typed logical contracts for the isolated Stage 2 QA runtime."""

from __future__ import annotations

from typing import Literal, NotRequired, TypedDict

ChunkingStrategy = Literal["static", "recursive", "parent_document", "sentence_window"]


class ChunkingSettings(TypedDict):
    schema_version: Literal[1]
    strategy: ChunkingStrategy
    chunk_size: int
    chunk_overlap: int
    parent_size: int | None
    window_sentences: int | None


class SettingsPayload(TypedDict):
    provider: Literal["deepseek"]
    model: Literal["qa-model"]
    temperature: float
    max_tokens: int
    system_prompt: str
    top_k: int
    chunk_size: int
    chunk_overlap: int
    chunking: ChunkingSettings


class SettingsResponse(SettingsPayload):
    api_key: None


class SavedSettings(SettingsPayload):
    chunks_changed: bool


class DocumentInfo(TypedDict):
    doc_id: str
    filename: str
    chunks_count: int
    chunk_size: int
    chunk_overlap: int
    created_at: str
    strategy: str
    schema_version: Literal[1]


class DocumentsPage(TypedDict):
    documents: list[DocumentInfo]
    total: int
    next_cursor: str | None
    truncated: bool


class ChunkInfo(TypedDict):
    point_id: str
    chunk_index: int
    text: str
    token_count: int
    page: int | None


class ChunksPage(TypedDict):
    chunks: list[ChunkInfo]
    next_cursor: str | None
    truncated: bool


class UploadResponse(TypedDict):
    status: Literal["processing", "cancelled", "unchanged"]
    file_id: str
    message: str


class DuplicateResponse(TypedDict):
    status: Literal["duplicate"]
    filename: str
    existing_chunks: int
    existing_size: int
    stored_chunk_size: int
    stored_chunk_overlap: int
    new_file_size: int
    estimated_chunks: int
    chunks_settings_changed: bool
    current_chunk_size: int
    current_chunk_overlap: int


class ProgressResponse(TypedDict):
    file_id: str
    status: Literal["processing", "done", "error"]
    message: str
    chunks_count: NotRequired[int]


class ReingestResponse(TypedDict):
    status: Literal["processing", "skipped"]
    file_id: str
    message: str


class DeleteResponse(TypedDict):
    status: Literal["ok"]
    message: str
    deleted_count: int


class ModelsResponse(TypedDict):
    provider: str
    models: list[str]
    cached: bool
    error: str | None


class ValidateKeyResponse(TypedDict):
    valid: bool
    provider: Literal["deepseek"]
    error: str | None


class HealthResponse(TypedDict):
    status: Literal["ok"]
    mode: Literal["stage2-isolated-qa"]
    project_id: str


class LocaleResponse(TypedDict):
    locale: Literal["en", "ru"]
    translations: dict[str, str]


class LoadResponse(TypedDict):
    status: Literal["ok"]
    sha256: str


class SeedDocumentsResponse(TypedDict):
    status: Literal["ok"]
    count: int
