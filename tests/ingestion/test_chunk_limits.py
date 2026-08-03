"""Exact chunk-size boundary regressions."""

from __future__ import annotations

from src.ingestion.chunker import chunk_text


def test_exact_limit_text_remains_one_maximum_sized_chunk() -> None:
    chunks = chunk_text("x" * 512, chunk_size=512, chunk_overlap=64)

    assert [len(chunk) for chunk in chunks] == [512]


def test_oversize_text_never_emits_a_chunk_above_the_limit() -> None:
    chunks = chunk_text("x" * 513, chunk_size=512, chunk_overlap=64)

    assert len(chunks) == 2
    assert max(map(len, chunks)) == 512
    assert all(len(chunk) <= 512 for chunk in chunks)
