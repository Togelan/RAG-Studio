"""Canonical chunking metadata normalization for persisted payloads."""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Final

from src.vector_store.models import DocumentMetadata, JsonValue

_CHUNKING_SETTING_KEYS = (
    "schema_version",
    "strategy",
    "chunk_size",
    "chunk_overlap",
    "parent_size",
    "window_sentences",
)
_VALID_STRATEGIES: Final = frozenset(
    {"static", "recursive", "parent_document", "sentence_window"}
)


def document_metadata(
    raw: Mapping[str, object], *, doc_id: str, filename: str
) -> DocumentMetadata:
    """Normalize one Qdrant point payload into document metadata."""
    return DocumentMetadata(
        doc_id=str(raw.get("doc_id", doc_id)),
        filename=str(raw.get("source", filename)),
        file_hash=str(raw.get("file_hash", "")),
        chunk_count=integer(raw.get("total_chunks")),
        chunk_size=integer(raw.get("chunk_size")),
        chunk_overlap=integer(raw.get("chunk_overlap")),
        strategy=strategy(raw),
        schema_version=schema_version(raw),
        chunking_fingerprint=optional_text(raw.get("chunking_fingerprint")),
        chunking_settings=MappingProxyType(
            chunking_settings(raw.get("chunking_settings", raw.get("chunking")))
        ),
    )


def document_payload(raw: Mapping[str, object]) -> dict[str, JsonValue]:
    """Normalize a chunk payload into one canonical document-index payload."""
    normalized_strategy = strategy(raw)
    normalized_schema = schema_version(raw)
    payload: dict[str, JsonValue] = {
        "record_type": "document",
        "doc_id": str(raw.get("doc_id", "")),
        "source": str(raw.get("source", "unknown")),
        "created_at": str(raw.get("created_at", "")),
        "total_chunks": integer(raw.get("total_chunks")),
        "chunk_size": integer(raw.get("chunk_size")),
        "chunk_overlap": integer(raw.get("chunk_overlap")),
        "file_hash": str(raw.get("file_hash", "")),
        "strategy": normalized_strategy,
        "schema_version": normalized_schema,
        "chunking_strategy": normalized_strategy,
        "chunking_schema_version": normalized_schema,
    }
    fingerprint = optional_text(raw.get("chunking_fingerprint"))
    if fingerprint is not None:
        payload["chunking_fingerprint"] = fingerprint
    settings = chunking_settings(raw.get("chunking_settings", raw.get("chunking")))
    _add_settings(payload, settings)
    return payload


def metadata_payload(
    metadata: DocumentMetadata, created_at: str
) -> dict[str, JsonValue]:
    """Serialize typed document metadata into its canonical index payload."""
    payload: dict[str, JsonValue] = {
        "record_type": "document",
        "doc_id": metadata.doc_id,
        "source": metadata.filename,
        "total_chunks": metadata.chunk_count,
        "chunk_size": metadata.chunk_size,
        "chunk_overlap": metadata.chunk_overlap,
        "created_at": created_at,
        "file_hash": metadata.file_hash,
        "strategy": metadata.strategy,
        "schema_version": metadata.schema_version,
        "chunking_strategy": metadata.strategy,
        "chunking_schema_version": metadata.schema_version,
    }
    if metadata.chunking_fingerprint is not None:
        payload["chunking_fingerprint"] = metadata.chunking_fingerprint
    _add_settings(payload, dict(metadata.chunking_settings))
    return payload


def json_payload(raw: Mapping[str, object]) -> dict[str, JsonValue]:
    """Preserve an index record type while canonicalizing its metadata."""
    payload = document_payload(raw)
    payload["record_type"] = str(raw.get("record_type", "document"))
    return payload


def strategy(raw: Mapping[str, object], default: str = "recursive") -> str:
    """Return the canonical strategy with legacy recursive fallback."""
    value = raw.get("strategy", raw.get("chunking_strategy", default))
    fallback = default if default in _VALID_STRATEGIES else "recursive"
    if isinstance(value, str) and value in _VALID_STRATEGIES:
        return value
    return fallback


def schema_version(raw: Mapping[str, object], default: int = 1) -> int:
    """Return the canonical positive schema fallback used by persistence."""
    value = integer(
        raw.get("schema_version", raw.get("chunking_schema_version", default)),
        default=default,
    )
    return value or 1


def chunking_settings(value: object) -> dict[str, JsonValue]:
    """Keep only canonical scalar chunking settings from an external payload."""
    if not isinstance(value, Mapping):
        return {}
    settings: dict[str, JsonValue] = {}
    for key in _CHUNKING_SETTING_KEYS:
        candidate = value.get(key)
        if candidate is None or isinstance(candidate, (str, int, float, bool)):
            settings[key] = candidate
    return settings


def integer(value: object, *, default: int = 0) -> int:
    """Normalize a persisted integer without leaking parsing exceptions."""
    try:
        return int(str(value))
    except ValueError:
        return default


def optional_text(value: object) -> str | None:
    """Return non-empty persisted text or no value."""
    return value if isinstance(value, str) and value else None


def _add_settings(
    payload: dict[str, JsonValue], settings: dict[str, JsonValue]
) -> None:
    if not settings:
        return
    payload["chunking_settings"] = settings
    for key in ("parent_size", "window_sentences"):
        if key in settings:
            payload[key] = settings[key]
