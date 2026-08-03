"""Regression tests for the per-document chunk cap."""

from importlib import import_module
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.vector_store.models import DenseVector, SparseVector


@pytest.mark.asyncio
async def test_oversized_document_stops_before_embedding(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    router = import_module("src.ingestion.router")
    path = tmp_path / "oversized.txt"
    path.write_text("content", encoding="utf-8")
    chunks = ["x" * 20] * (router.MAX_CHUNKS_PER_DOCUMENT + 1)
    embedder = MagicMock()
    store = AsyncMock()
    monkeypatch.setattr(router, "detect_file_type", lambda *_: ".txt")
    monkeypatch.setattr(router, "detect_and_parse", lambda *_: ("content", {}))
    monkeypatch.setattr(router, "chunk_text", lambda *_args, **_kwargs: chunks)

    await router._ingest_file(
        "job-oversized",
        str(path),
        "oversized.txt",
        "text/plain",
        store,
        embedder=embedder,
    )

    progress = await router._get_progress("job-oversized")
    assert progress and progress["status"] == "error"
    assert f"maximum of {router.MAX_CHUNKS_PER_DOCUMENT:,}" in str(progress["message"])
    embedder.embed_dense.assert_not_called()
    embedder.embed_sparse.assert_not_called()
    store.replace_document.assert_not_awaited()


@pytest.mark.asyncio
async def test_document_at_chunk_limit_is_ingested(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    router = import_module("src.ingestion.router")
    path = tmp_path / "at-limit.txt"
    path.write_text("content", encoding="utf-8")
    chunks = ["x" * 20] * router.MAX_CHUNKS_PER_DOCUMENT
    embedder = MagicMock()
    embedder.embed_dense.return_value = (DenseVector((0.0,)),) * len(chunks)
    embedder.embed_sparse.return_value = (SparseVector((1,), (1.0,)),) * len(chunks)
    store = AsyncMock()
    monkeypatch.setattr(router, "detect_file_type", lambda *_: ".txt")
    monkeypatch.setattr(router, "detect_and_parse", lambda *_: ("content", {}))
    monkeypatch.setattr(router, "chunk_text", lambda *_args, **_kwargs: chunks)

    await router._ingest_file(
        "job-limit",
        str(path),
        "at-limit.txt",
        "text/plain",
        store,
        embedder=embedder,
    )

    progress = await router._get_progress("job-limit")
    assert progress and progress["status"] == "done"
    assert progress["chunks_count"] == router.MAX_CHUNKS_PER_DOCUMENT
    store.replace_document.assert_awaited_once()
