"""Regression tests for the per-document chunk cap."""

import tempfile
import uuid
from importlib import import_module
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.mark.asyncio
async def test_oversized_document_stops_before_embedding(monkeypatch: pytest.MonkeyPatch) -> None:
    router = import_module("src.ingestion.router")

    file_id = str(uuid.uuid4())
    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as temp_file:
        path = Path(temp_file.name)
    chunks = ["x" * 20] * (router.MAX_CHUNKS_PER_DOCUMENT + 1)
    dense_embeddings = MagicMock()
    sparse_embeddings = MagicMock()
    upsert = AsyncMock()
    monkeypatch.setattr(router, "ensure_collection_exists", AsyncMock())
    monkeypatch.setattr(router, "detect_file_type", lambda *_: ".txt")
    monkeypatch.setattr(router, "detect_and_parse", lambda *_: ("content", {}))
    monkeypatch.setattr(router, "chunk_text", lambda *_args, **_kwargs: chunks)
    monkeypatch.setattr(router, "generate_dense_embeddings", dense_embeddings)
    monkeypatch.setattr(router, "generate_sparse_embeddings", sparse_embeddings)
    monkeypatch.setattr(router, "upsert_chunks", upsert)

    await router._ingest_file(file_id, str(path), "oversized.txt", "text/plain", AsyncMock())

    progress = await router._get_progress(file_id)
    assert progress and progress["status"] == "error"
    assert f"maximum of {router.MAX_CHUNKS_PER_DOCUMENT:,}" in str(progress["message"])
    dense_embeddings.assert_not_called()
    sparse_embeddings.assert_not_called()
    upsert.assert_not_awaited()


@pytest.mark.asyncio
async def test_document_at_chunk_limit_is_ingested(monkeypatch: pytest.MonkeyPatch) -> None:
    router = import_module("src.ingestion.router")

    file_id = str(uuid.uuid4())
    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as temp_file:
        path = Path(temp_file.name)
    chunks = ["x" * 20] * router.MAX_CHUNKS_PER_DOCUMENT
    upsert = AsyncMock()
    monkeypatch.setattr(router, "ensure_collection_exists", AsyncMock())
    monkeypatch.setattr(router, "detect_file_type", lambda *_: ".txt")
    monkeypatch.setattr(router, "detect_and_parse", lambda *_: ("content", {}))
    monkeypatch.setattr(router, "chunk_text", lambda *_args, **_kwargs: chunks)
    monkeypatch.setattr(router, "generate_dense_embeddings", lambda _: ["dense"] * len(chunks))
    monkeypatch.setattr(router, "generate_sparse_embeddings", lambda _: ["sparse"] * len(chunks))
    monkeypatch.setattr(router, "upsert_chunks", upsert)

    await router._ingest_file(file_id, str(path), "at-limit.txt", "text/plain", AsyncMock())

    progress = await router._get_progress(file_id)
    assert progress and progress["status"] == "done"
    assert progress["chunks_count"] == router.MAX_CHUNKS_PER_DOCUMENT
    upsert.assert_awaited_once()
