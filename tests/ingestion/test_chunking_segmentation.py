"""Segmentation regressions for deterministic paragraph and sentence boundaries."""

from __future__ import annotations

from src.ingestion.chunking_segmentation import split_paragraphs, split_sentences


def test_sentence_segmentation_preserves_abbreviations_and_decimal_values() -> None:
    # Given: punctuation that is not a sentence boundary.
    text = "Dr. Ada measured 3.14 units. It worked!"
    paragraph = split_paragraphs(text)[0]

    # When: sentence spans are derived.
    sentences = split_sentences(text, paragraph)

    # Then: abbreviations and decimals remain inside their sentences.
    assert [sentence.text(text) for sentence in sentences] == [
        "Dr. Ada measured 3.14 units.",
        "It worked!",
    ]


def test_blank_paragraphs_are_ignored_without_changing_source_offsets() -> None:
    # Given: leading, repeated, and trailing blank paragraph separators.
    text = "\n\nAlpha paragraph.\n\n\n\nBeta paragraph.\n"

    # When: paragraph spans are derived.
    paragraphs = split_paragraphs(text)

    # Then: non-empty paragraphs keep their original source locations.
    assert [paragraph.text(text) for paragraph in paragraphs] == [
        "Alpha paragraph.",
        "Beta paragraph.",
    ]
    assert [(paragraph.start, paragraph.end) for paragraph in paragraphs] == [(2, 18), (22, 37)]


def test_sentence_segmentation_handles_initials_ellipsis_and_closing_quotes() -> None:
    # Given: punctuation where only the ellipsis and quoted question end sentences.
    text = 'A. Smith paused... Then asked, "Ready?" Yes.'
    paragraph = split_paragraphs(text)[0]

    # When: sentence spans are derived.
    sentences = split_sentences(text, paragraph)

    # Then: initials stay attached and closing punctuation remains in each range.
    assert [sentence.text(text) for sentence in sentences] == [
        "A. Smith paused...",
        'Then asked, "Ready?"',
        "Yes.",
    ]


def test_single_newlines_do_not_create_blank_paragraph_boundaries() -> None:
    # Given: wrapped prose plus a whitespace-only blank line.
    text = "Wrapped first line.\nStill same paragraph.\n \t\nNext paragraph."

    # When: paragraphs are segmented.
    paragraphs = split_paragraphs(text)

    # Then: only the blank line separates paragraphs.
    assert [paragraph.text(text) for paragraph in paragraphs] == [
        "Wrapped first line.\nStill same paragraph.",
        "Next paragraph.",
    ]
