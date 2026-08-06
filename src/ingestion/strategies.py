"""Deterministic builders for bounded ingestion search units."""

from __future__ import annotations

from typing import assert_never
from uuid import NAMESPACE_URL, uuid5

from src.ingestion.chunker import chunk_text
from src.ingestion.chunking_models import (
    MAX_CONTEXT_UNITS,
    ChunkingConfig,
    ChunkingConfigurationError,
    ChunkingLimitExceeded,
    ChunkingStrategy,
    ChunkUnit,
    TextRange,
)
from src.ingestion.chunking_segmentation import split_paragraphs, split_sentences


def chunk_text_with_strategy(text: str, config: ChunkingConfig) -> list[ChunkUnit]:
    """Create deterministic, source-backed search units for one text document."""
    if not text.strip():
        return []
    match config.strategy:
        case ChunkingStrategy.STATIC:
            units = _static_units(text, config)
        case ChunkingStrategy.RECURSIVE:
            units = _recursive_units(text, config)
        case ChunkingStrategy.PARENT_DOCUMENT:
            units = _parent_document_units(text, config)
        case ChunkingStrategy.SENTENCE_WINDOW:
            units = _sentence_window_units(text, config)
        case ChunkingStrategy.CSV_ROW:
            raise ChunkingConfigurationError("csv_row_is_not_a_text_strategy")
        case unreachable:
            assert_never(unreachable)
    return units


def chunk_csv_rows_with_strategy(
    row_texts: list[str], source_id: str = "document", max_units: int = MAX_CONTEXT_UNITS
) -> list[ChunkUnit]:
    """Preserve each non-blank CSV row as one atomic metadata-bearing unit."""
    _validate_unit_limit(max_units)
    if not source_id:
        raise ChunkingConfigurationError("source_id_must_not_be_empty")
    units: list[ChunkUnit] = []
    for row_index, text in enumerate(row_texts):
        if not text.strip():
            continue
        text_range = TextRange(0, len(text))
        unit = ChunkUnit(
            unit_id=str(
                uuid5(
                    NAMESPACE_URL,
                    f"{source_id}:csv_row:{row_index}:0:{len(text)}",
                )
            ),
            text=text,
            strategy=ChunkingStrategy.CSV_ROW,
            text_range=text_range,
            sentence_index=row_index,
            is_atomic=True,
        )
        _append_bounded(units, unit, max_units)
    return units


def _static_units(text: str, config: ChunkingConfig) -> list[ChunkUnit]:
    units: list[ChunkUnit] = []
    source_range = TextRange(0, len(text))
    for text_range in _bounded_ranges(
        source_range, config.chunk_size, config.chunk_overlap
    ):
        _append_bounded(units, _plain_unit(text, config, text_range), config.max_units)
    return units


def _recursive_units(text: str, config: ChunkingConfig) -> list[ChunkUnit]:
    chunks = chunk_text(text, config.chunk_size, config.chunk_overlap)
    if not chunks:
        return _static_units(text, config)
    units: list[ChunkUnit] = []
    search_start = 0
    for chunk in chunks:
        start = text.find(chunk, search_start)
        if start < 0:
            start = text.find(chunk)
        if start < 0:
            raise ChunkingConfigurationError("recursive_chunk_has_no_source_range")
        text_range = TextRange(start, start + len(chunk))
        _append_bounded(units, _plain_unit(text, config, text_range), config.max_units)
        search_start = start + 1
    return units


def _parent_document_units(text: str, config: ChunkingConfig) -> list[ChunkUnit]:
    units: list[ChunkUnit] = []
    for paragraph_index, paragraph_range in enumerate(split_paragraphs(text)):
        parent_ranges = _parent_ranges(text, paragraph_range, config.parent_size)
        for parent_range in parent_ranges:
            identity = (
                f"{config.source_id}:{config.strategy.value}:"
                f"{parent_range.start}:{parent_range.end}:parent"
            )
            parent_id = str(uuid5(NAMESPACE_URL, identity))
            for child_range in _child_ranges(text, parent_range, config):
                unit = ChunkUnit(
                    unit_id=_unit_identifier(config, child_range),
                    text=child_range.text(text),
                    strategy=config.strategy,
                    text_range=child_range,
                    paragraph_index=paragraph_index,
                    paragraph_range=paragraph_range,
                    parent_id=parent_id,
                    parent_range=parent_range,
                )
                _append_bounded(units, unit, config.max_units)
    return units


def _parent_ranges(
    text: str, paragraph_range: TextRange, parent_size: int
) -> list[TextRange]:
    parents: list[TextRange] = []
    pending: TextRange | None = None
    for sentence in split_sentences(text, paragraph_range):
        if sentence.end - sentence.start > parent_size:
            if pending is not None:
                parents.append(pending)
                pending = None
            parents.extend(_bounded_ranges(sentence, parent_size, 0))
        elif pending is None:
            pending = sentence
        elif sentence.end - pending.start <= parent_size:
            pending = TextRange(pending.start, sentence.end)
        else:
            parents.append(pending)
            pending = sentence
    if pending is not None:
        parents.append(pending)
    return parents


def _child_ranges(
    text: str, parent_range: TextRange, config: ChunkingConfig
) -> list[TextRange]:
    children: list[TextRange] = []
    pending: TextRange | None = None
    for sentence in split_sentences(text, parent_range):
        if sentence.end - sentence.start > config.chunk_size:
            if pending is not None:
                children.append(pending)
                pending = None
            children.extend(
                _bounded_ranges(sentence, config.chunk_size, config.chunk_overlap)
            )
        elif pending is None:
            pending = sentence
        elif sentence.end - pending.start <= config.chunk_size:
            pending = TextRange(pending.start, sentence.end)
        else:
            children.append(pending)
            pending = sentence
    if pending is not None:
        children.append(pending)
    return children


def _sentence_window_units(text: str, config: ChunkingConfig) -> list[ChunkUnit]:
    units: list[ChunkUnit] = []
    for paragraph_index, paragraph_range in enumerate(split_paragraphs(text)):
        sentences = split_sentences(text, paragraph_range)
        for sentence_index, sentence in enumerate(sentences):
            fragments = _bounded_ranges(
                sentence, config.chunk_size, config.chunk_overlap
            )
            oversized = len(fragments) > 1
            for fragment in fragments:
                window_range = fragment if oversized else _window_range(
                    sentences, sentence_index, config.window_sentences
                )
                unit = ChunkUnit(
                    unit_id=_unit_identifier(config, fragment),
                    text=fragment.text(text),
                    strategy=config.strategy,
                    text_range=fragment,
                    paragraph_index=paragraph_index,
                    paragraph_range=paragraph_range,
                    sentence_index=sentence_index,
                    window_range=window_range,
                )
                _append_bounded(units, unit, config.max_units)
    return units


def _window_range(
    sentences: list[TextRange], sentence_index: int, window_sentences: int
) -> TextRange:
    first = max(0, sentence_index - window_sentences)
    last = min(len(sentences) - 1, sentence_index + window_sentences)
    return TextRange(sentences[first].start, sentences[last].end)


def _bounded_ranges(
    source_range: TextRange, chunk_size: int, chunk_overlap: int
) -> list[TextRange]:
    ranges: list[TextRange] = []
    step = chunk_size - chunk_overlap
    start = source_range.start
    while start < source_range.end:
        end = min(start + chunk_size, source_range.end)
        ranges.append(TextRange(start, end))
        if end == source_range.end:
            break
        start += step
    return ranges


def _plain_unit(text: str, config: ChunkingConfig, text_range: TextRange) -> ChunkUnit:
    return ChunkUnit(
        unit_id=_unit_identifier(config, text_range),
        text=text_range.text(text),
        strategy=config.strategy,
        text_range=text_range,
    )


def _unit_identifier(config: ChunkingConfig, text_range: TextRange) -> str:
    identity = (
        f"{config.source_id}:{config.strategy.value}:"
        f"{text_range.start}:{text_range.end}:unit"
    )
    return str(uuid5(NAMESPACE_URL, identity))


def _append_bounded(
    units: list[ChunkUnit], unit: ChunkUnit, max_units: int
) -> None:
    if len(units) >= max_units:
        raise ChunkingLimitExceeded(max_units)
    units.append(unit)


def _validate_unit_limit(max_units: int) -> None:
    if max_units <= 0 or max_units > MAX_CONTEXT_UNITS:
        raise ChunkingConfigurationError("max_units_must_be_between_one_and_hard_cap")
