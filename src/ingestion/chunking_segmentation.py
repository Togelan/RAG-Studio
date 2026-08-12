"""Deterministic source-range segmentation without a language model."""

from __future__ import annotations

import re
from typing import Final

from src.ingestion.chunking_models import TextRange

_PARAGRAPH_PATTERN: Final = re.compile(r"\S(?:.*?\S)?(?=\n\s*\n|\s*\Z)", re.DOTALL)
_ABBREVIATIONS: Final = frozenset(
    {
        "dr.",
        "e.g.",
        "etc.",
        "fig.",
        "i.e.",
        "jr.",
        "mr.",
        "mrs.",
        "ms.",
        "prof.",
        "sr.",
        "vs.",
    }
)
_CLOSING_PUNCTUATION: Final = frozenset("\"')]}\u2019\u201d")


def split_paragraphs(text: str) -> list[TextRange]:
    """Return non-blank paragraphs as half-open ranges in the source text."""
    return [
        TextRange(match.start(), match.end())
        for match in _PARAGRAPH_PATTERN.finditer(text)
    ]


def split_sentences(source: str, paragraph: TextRange) -> list[TextRange]:
    """Return deterministic sentence ranges that stay within one paragraph."""
    sentences: list[TextRange] = []
    sentence_start = paragraph.start
    index = paragraph.start
    while index < paragraph.end:
        sentence_end = _sentence_end(source, index, paragraph.end)
        if sentence_end is not None:
            sentences.append(TextRange(sentence_start, sentence_end))
            sentence_start = _skip_whitespace(source, sentence_end, paragraph.end)
            index = sentence_start
            continue
        index += 1
    if sentence_start < paragraph.end:
        sentences.append(TextRange(sentence_start, paragraph.end))
    return sentences


def _sentence_end(source: str, index: int, paragraph_end: int) -> int | None:
    character = source[index]
    if character not in ".?!":
        return None
    if character == "." and (
        _is_abbreviation(source, index) or _is_initial(source, index)
    ):
        return None
    end = index + 1
    while end < paragraph_end and source[end] in _CLOSING_PUNCTUATION:
        end += 1
    if end < paragraph_end and not source[end].isspace():
        return None
    return end


def _is_abbreviation(source: str, index: int) -> bool:
    token_start = index
    while token_start > 0 and not source[token_start - 1].isspace():
        token_start -= 1
    return source[token_start : index + 1].lower() in _ABBREVIATIONS


def _is_initial(source: str, index: int) -> bool:
    return (
        index > 0
        and source[index - 1].isalpha()
        and (index == 1 or not source[index - 2].isalpha())
    )


def _skip_whitespace(source: str, start: int, end: int) -> int:
    index = start
    while index < end and source[index].isspace():
        index += 1
    return index
