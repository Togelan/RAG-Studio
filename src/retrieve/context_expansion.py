"""Convert searched chunk hits into bounded, citation-ready context units."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from types import MappingProxyType

from src.vector_store.models import JsonValue, Payload, VectorSearchHit

_SUPPORTED_STRATEGIES = frozenset(
    {"static", "recursive", "parent_document", "sentence_window", "csv_row"}
)


@dataclass(frozen=True, slots=True)
class ContextUnit:
    """One expanded, deduplicated text unit ready for reranking and prompting."""

    point_id: str
    score: float
    text: str
    metadata: Payload


def expand_context_units(
    hits: Iterable[VectorSearchHit], *, top_k: int, character_budget: int
) -> tuple[ContextUnit, ...]:
    """Expand strategy payloads, deduplicate them, and apply final bounds."""
    if top_k < 1 or character_budget < 1:
        return ()

    deduplicated: dict[tuple[str, str, str], ContextUnit] = {}
    for hit in hits:
        unit = _expand_hit(hit)
        identity = _identity(unit)
        previous = deduplicated.get(identity)
        if previous is None or _rank_key(unit) < _rank_key(previous):
            deduplicated[identity] = unit

    remaining = character_budget
    selected: list[ContextUnit] = []
    for unit in sorted(deduplicated.values(), key=_rank_key):
        if len(selected) == top_k:
            break
        if len(unit.text) > remaining:
            continue
        selected.append(unit)
        remaining -= len(unit.text)
    return tuple(selected)


def _expand_hit(hit: VectorSearchHit) -> ContextUnit:
    metadata = dict(hit.payload)
    strategy = _strategy(metadata.get("strategy"))
    text, start_key, end_key = _expanded_text(metadata, strategy)
    metadata["strategy"] = strategy
    metadata["context_strategy"] = strategy
    _set_location(metadata, start_key, end_key)
    return ContextUnit(
        point_id=str(hit.point_id),
        score=hit.score,
        text=text,
        metadata=MappingProxyType(metadata),
    )


def _expanded_text(
    metadata: dict[str, JsonValue], strategy: str
) -> tuple[str, str, str]:
    raw_text = _text(metadata.get("text"))
    if strategy == "parent_document":
        parent_text = _text(metadata.get("parent_text"))
        if parent_text:
            return parent_text, "parent_start_offset", "parent_end_offset"
    if strategy == "sentence_window":
        window_text = _text(metadata.get("window_text"))
        if window_text:
            return window_text, "window_start_offset", "window_end_offset"
    return raw_text, "start_offset", "end_offset"


def _set_location(metadata: dict[str, JsonValue], start_key: str, end_key: str) -> None:
    start = metadata.get(start_key)
    end = metadata.get(end_key)
    if _offset(start) is None or _offset(end) is None or _offset(start) > _offset(end):
        metadata["location_unavailable"] = True
        return
    metadata["start_offset"] = _offset(start)
    metadata["end_offset"] = _offset(end)
    metadata["location_unavailable"] = False


def _identity(unit: ContextUnit) -> tuple[str, str, str]:
    metadata = unit.metadata
    document = _text(metadata.get("doc_id")) or _text(metadata.get("source"))
    strategy = _text(metadata.get("context_strategy"))
    if strategy == "parent_document":
        expansion = _text(metadata.get("parent_id")) or unit.text
    else:
        expansion = (
            f"{metadata.get('start_offset')}:{metadata.get('end_offset')}:{unit.text}"
        )
    return document or unit.point_id, strategy, expansion


def _rank_key(unit: ContextUnit) -> tuple[float, str]:
    return -unit.score, unit.point_id


def _strategy(value: JsonValue | None) -> str:
    return (
        value
        if isinstance(value, str) and value in _SUPPORTED_STRATEGIES
        else "recursive"
    )


def _text(value: JsonValue | None) -> str:
    return value if isinstance(value, str) else ""


def _offset(value: JsonValue | None) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None
