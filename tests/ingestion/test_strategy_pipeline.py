from __future__ import annotations

from collections.abc import Sequence
from importlib import import_module
from pathlib import Path

import pytest
from qdrant_client import AsyncQdrantClient

from src.api.chunking_settings import ChunkingSettings
from src.ingestion.embedder import COLLECTION_NAME
from src.ingestion.router import _ingest_file, _progress_store, stored_files
from src.vector_store.adapter import QdrantVectorStore
from src.vector_store.models import DenseVector, SparseVector

ingestion_router = import_module("src.ingestion.router")


class _FakeEmbedder:
    def embed_dense(self, texts: Sequence[str]) -> tuple[DenseVector, ...]:
        return tuple(DenseVector((0.0,) * 384) for _ in texts)

    def embed_sparse(self, texts: Sequence[str]) -> tuple[SparseVector, ...]:
        return tuple(SparseVector((0,), (1.0,)) for _ in texts)


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("strategy", "suffix", "content", "expected_strategy"),
    [
        ("static", ".txt", "Alpha sentence. Beta sentence.", "static"),
        ("recursive", ".txt", "Alpha sentence.\n\nBeta sentence.", "recursive"),
        (
            "parent_document",
            ".txt",
            "Alpha sentence. Beta sentence. Gamma sentence.",
            "parent_document",
        ),
        (
            "sentence_window",
            ".txt",
            "Alpha sentence. Beta sentence. Gamma sentence.",
            "sentence_window",
        ),
        ("recursive", ".csv", "name,value\nalpha,1\nbeta,2\n", "csv_row"),
    ],
)
async def test_pipeline_persists_strategy_units_and_replacement_metadata(
    strategy: str,
    suffix: str,
    content: str,
    expected_strategy: str,
    tmp_path: Path,
) -> None:
    source = tmp_path / f"source{suffix}"
    source.write_text(content, encoding="utf-8")
    settings = ChunkingSettings(
        strategy=strategy,
        chunk_size=256,
        chunk_overlap=32,
        parent_size=512 if strategy == "parent_document" else None,
        window_sentences=1 if strategy == "sentence_window" else None,
    )
    client = AsyncQdrantClient(path=str(tmp_path / "qdrant"))
    store = QdrantVectorStore(client)
    stored_files.clear()
    _progress_store.clear()

    await _ingest_file(
        "pipeline-job",
        str(source),
        f"pipeline{suffix}",
        "text/csv" if suffix == ".csv" else "text/plain",
        store,
        chunking_settings=settings,
        file_hash="pipeline-hash",
        embedder=_FakeEmbedder(),
    )
    points, _ = await client.scroll(
        collection_name=COLLECTION_NAME,
        with_payload=True,
        with_vectors=False,
        limit=100,
    )
    metadata = await store.find_document(f"pipeline{suffix}")

    assert points
    payloads = [point.payload or {} for point in points]
    assert {payload["strategy"] for payload in payloads} == {expected_strategy}
    assert all(payload["schema_version"] == 1 for payload in payloads)
    assert all(
        payload["chunking_fingerprint"] == settings.fingerprint for payload in payloads
    )
    assert all(
        payload["chunking_settings"]["strategy"] == strategy for payload in payloads
    )
    assert all(payload["start_offset"] <= payload["end_offset"] for payload in payloads)
    assert metadata is not None
    assert metadata.strategy == expected_strategy
    assert metadata.schema_version == 1
    assert metadata.chunking_fingerprint == settings.fingerprint
    assert dict(metadata.chunking_settings)["strategy"] == strategy
    if expected_strategy != "csv_row":
        assert all(
            content[payload["start_offset"] : payload["end_offset"]] == payload["text"]
            for payload in payloads
        )
    if expected_strategy == "parent_document":
        assert all(
            "parent_id" in payload and "parent_text" in payload for payload in payloads
        )
        assert all(
            content[payload["parent_start_offset"] : payload["parent_end_offset"]]
            == payload["parent_text"]
            for payload in payloads
        )
    if expected_strategy == "sentence_window":
        assert all("window_text" in payload for payload in payloads)
        assert all(
            content[payload["window_start_offset"] : payload["window_end_offset"]]
            == payload["window_text"]
            for payload in payloads
        )
    if expected_strategy == "csv_row":
        assert all(payload["is_atomic"] is True for payload in payloads)
    await client.close()


@pytest.mark.anyio
async def test_csv_metadata_cannot_override_ingestion_identity(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "reserved.csv"
    source.write_text("placeholder\nrow\n", encoding="utf-8")
    settings = ChunkingSettings(strategy="recursive")
    row_data = {
        "strategy": "attacker",
        "schema_version": "999",
        "chunking_fingerprint": "forged",
    }
    monkeypatch.setattr(
        ingestion_router,
        "parse_csv_as_rows",
        lambda _path: (
            ["strategy: attacker | schema_version: 999"],
            [row_data | {"csv_row_data": row_data, "row_index": 0}],
        ),
    )
    client = AsyncQdrantClient(path=str(tmp_path / "reserved-qdrant"))
    store = QdrantVectorStore(client)

    await _ingest_file(
        "reserved-job",
        str(source),
        "reserved.csv",
        "text/csv",
        store,
        chunking_settings=settings,
        file_hash="reserved-hash",
        embedder=_FakeEmbedder(),
    )
    points, _ = await client.scroll(
        collection_name=COLLECTION_NAME,
        with_payload=True,
        with_vectors=False,
        limit=10,
    )

    payload = points[0].payload or {}
    assert payload["strategy"] == "csv_row"
    assert payload["schema_version"] == 1
    assert payload["chunking_fingerprint"] == settings.fingerprint
    assert payload["csv_row_data"] == row_data
    await client.close()
