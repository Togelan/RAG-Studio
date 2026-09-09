"""Safe citation projection for Personal Chat responses and persistence."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Final

from src.vector_store.models import JsonScalar, JsonValue

type CitationPayload = dict[str, JsonValue]
_SAFE_FIELDS: Final = frozenset(
    {
        "document_id",
        "doc_id",
        "filename",
        "source",
        "page",
        "chunk_index",
        "start_line",
        "end_line",
        "score",
    }
)


def project_safe_citation(item: Mapping[str, JsonValue]) -> CitationPayload:
    result: CitationPayload = {}
    metadata = item.get("metadata")
    sources = (item, metadata) if isinstance(metadata, Mapping) else (item,)
    for source in sources:
        for key, value in source.items():
            if key in _SAFE_FIELDS and isinstance(value, (str, int, float, bool)):
                result[str(key)] = (
                    _filename(value) if key in {"filename", "source"} else value
                )
    start_offset = _metadata_integer(sources, "start_offset")
    end_offset = _metadata_integer(sources, "end_offset")
    if (
        start_offset is not None
        and end_offset is not None
        and start_offset >= 0
        and start_offset <= end_offset
    ):
        result.update(
            {
                "end_offset": end_offset,
                "start_offset": start_offset,
                "location": f"Characters {start_offset}–{end_offset}",
            }
        )
    return result


def project_safe_citations(
    items: Iterable[Mapping[str, JsonValue]],
) -> tuple[CitationPayload, ...]:
    projected: list[CitationPayload] = []
    seen_locations: set[tuple[str, str]] = set()
    for item in items:
        citation = project_safe_citation(item)
        identity = _citation_identity(citation)
        if identity is not None and identity in seen_locations:
            continue
        if identity is not None:
            seen_locations.add(identity)
        projected.append(citation)
    return tuple(projected)


def _citation_identity(citation: CitationPayload) -> tuple[str, str] | None:
    source = next(
        (
            value
            for key in ("document_id", "doc_id", "filename", "source")
            if isinstance((value := citation.get(key)), str) and value
        ),
        None,
    )
    location = _location_identity(citation)
    return None if source is None or location is None else (source, location)


def _location_identity(citation: CitationPayload) -> str | None:
    location = citation.get("location")
    if isinstance(location, str) and location:
        return f"location:{location}"
    parts = tuple(
        f"{key}:{value}"
        for key in ("page", "chunk_index", "start_line", "end_line")
        if isinstance((value := citation.get(key)), int) and not isinstance(value, bool)
    )
    return "|".join(parts) or None


def _metadata_integer(
    sources: tuple[Mapping[str, JsonValue], ...], key: str
) -> int | None:
    values = tuple(source.get(key) for source in sources if key in source)
    if not values:
        return None
    value = values[-1]
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _filename(value: JsonScalar) -> JsonScalar:
    if not isinstance(value, str):
        return value
    return value.replace("\\", "/").rsplit("/", maxsplit=1)[-1][:255]
