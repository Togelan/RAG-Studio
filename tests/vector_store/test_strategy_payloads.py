from __future__ import annotations

from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

import pytest
from qdrant_client import AsyncQdrantClient

from src.ingestion.embedder import COLLECTION_NAME
from src.vector_store.adapter import QdrantVectorStore
from src.vector_store.document_index import DOCUMENT_INDEX_COLLECTION
from src.vector_store.models import (
    DenseVector,
    DocumentReplacement,
    VectorRecord,
)
from src.vector_store.strategy_payloads import document_payload


def _record(point_id: str, doc_id: str, strategy: str) -> VectorRecord:
    return VectorRecord(
        point_id=str(uuid5(NAMESPACE_URL, point_id)),
        dense=DenseVector((0.1,) * 384),
        payload={
            "doc_id": doc_id,
            "source": f"{doc_id}.txt",
            "text": "bounded text",
            "chunk_index": 0,
            "total_chunks": 1,
            "strategy": strategy,
            "schema_version": 1,
            "start_offset": 4,
            "end_offset": 16,
        },
    )


@pytest.mark.parametrize(
    ("raw_strategy", "expected"),
    [
        ("missing", "recursive"),
        (None, "recursive"),
        (42, "recursive"),
        ("future_strategy", "recursive"),
        ("", "recursive"),
        ("static", "static"),
        ("recursive", "recursive"),
        ("parent_document", "parent_document"),
        ("sentence_window", "sentence_window"),
    ],
)
def test_document_payload_normalizes_persisted_strategy(
    raw_strategy: object, expected: str
) -> None:
    # Given
    raw: dict[str, object] = {
        "doc_id": "persisted-doc",
        "source": "persisted.txt",
    }
    if raw_strategy != "missing":
        raw["strategy"] = raw_strategy

    # When
    payload = document_payload(raw)

    # Then
    assert payload["strategy"] == expected
    assert payload["chunking_strategy"] == expected


@pytest.mark.anyio
async def test_mixed_strategies_share_one_searchable_collection(
    tmp_path: Path,
) -> None:
    # Given
    client = AsyncQdrantClient(path=str(tmp_path / "qdrant"))
    store = QdrantVectorStore(client)

    # When
    for doc_id, strategy in (("doc-recursive", "recursive"), ("doc-static", "static")):
        await store.replace_document(
            DocumentReplacement(
                doc_id=doc_id,
                filename=f"{doc_id}.txt",
                records=(_record(f"{doc_id}-point", doc_id, strategy),),
                chunk_size=512,
                chunk_overlap=64,
                created_at="2026-08-06T00:00:00+00:00",
                strategy=strategy,
                schema_version=1,
            )
        )

    # Then
    collections = await client.get_collections()
    assert {item.name for item in collections.collections} == {
        COLLECTION_NAME,
        DOCUMENT_INDEX_COLLECTION,
    }
    index = await client.get_collection(DOCUMENT_INDEX_COLLECTION)
    assert index.config.params.vectors == {}
    points, _ = await client.scroll(
        collection_name=COLLECTION_NAME,
        with_payload=True,
        with_vectors=False,
        limit=10,
    )
    assert {(point.payload or {}).get("strategy") for point in points} == {
        "recursive",
        "static",
    }
    assert all((point.payload or {}).get("start_offset") == 4 for point in points)
    await client.close()


@pytest.mark.anyio
async def test_document_metadata_round_trip_preserves_strategy(
    tmp_path: Path,
) -> None:
    # Given
    qdrant_path = tmp_path / "round-trip"
    client = AsyncQdrantClient(path=str(qdrant_path))
    store = QdrantVectorStore(client)
    settings = {
        "schema_version": 1,
        "strategy": "parent_document",
        "chunk_size": 512,
        "chunk_overlap": 64,
        "parent_size": 2048,
        "window_sentences": None,
    }
    record = _record("round-trip-point", "round-trip-doc", "parent_document")
    record_payload = dict(record.payload)
    record_payload.update(
        {
            "search_unit_type": "child",
            "parent_id": "parent-0",
            "parent_text": "bounded parent text",
        }
    )

    # When
    await store.replace_document(
        DocumentReplacement(
            doc_id="round-trip-doc",
            filename="round-trip.txt",
            records=(
                VectorRecord(
                    point_id=record.point_id,
                    dense=record.dense,
                    payload=record_payload,
                ),
            ),
            chunk_size=512,
            chunk_overlap=64,
            created_at="2026-08-06T00:00:00+00:00",
            strategy="parent_document",
            schema_version=1,
            file_hash="sha256-round-trip",
            chunking_fingerprint="fingerprint-round-trip",
            chunking_settings=settings,
        )
    )
    await client.close()
    fresh_client = AsyncQdrantClient(path=str(qdrant_path))
    fresh_store = QdrantVectorStore(fresh_client)
    metadata = await fresh_store.find_document("round-trip.txt")
    page = await fresh_store.list_documents()
    points, _ = await fresh_client.scroll(
        collection_name=COLLECTION_NAME,
        with_payload=True,
        with_vectors=False,
        limit=10,
    )

    # Then
    assert metadata is not None
    assert metadata.strategy == "parent_document"
    assert metadata.schema_version == 1
    assert metadata.file_hash == "sha256-round-trip"
    assert metadata.chunking_fingerprint == "fingerprint-round-trip"
    assert dict(metadata.chunking_settings) == settings
    assert page.items[0].payload["chunking_settings"] == settings
    point_payload = points[0].payload or {}
    assert point_payload["strategy"] == "parent_document"
    assert point_payload["chunking_fingerprint"] == "fingerprint-round-trip"
    assert point_payload["chunking_settings"] == settings
    assert point_payload["search_unit_type"] == "child"
    assert point_payload["parent_id"] == "parent-0"
    assert point_payload["parent_text"] == "bounded parent text"
    await fresh_client.close()


@pytest.mark.anyio
async def test_legacy_strategy_defaults_are_written_to_document_index(
    tmp_path: Path,
) -> None:
    # Given
    client = AsyncQdrantClient(path=str(tmp_path / "legacy"))
    store = QdrantVectorStore(client)

    # When
    await store.replace_document(
        DocumentReplacement(
            doc_id="legacy-doc",
            filename="legacy.txt",
            records=(_record("legacy-point", "legacy-doc", "recursive"),),
            chunk_size=512,
            chunk_overlap=64,
            created_at="2026-08-06T00:00:00+00:00",
        )
    )
    page = await store.list_documents()

    # Then
    assert page.items[0].payload["strategy"] == "recursive"
    assert page.items[0].payload["schema_version"] == 1
    assert page.items[0].payload["chunking_strategy"] == "recursive"
    assert page.items[0].payload["chunking_schema_version"] == 1
    assert "chunking_fingerprint" not in page.items[0].payload
    metadata = await store.find_document("legacy.txt")
    assert metadata is not None
    assert metadata.strategy == "recursive"
    assert metadata.schema_version == 1
    assert metadata.chunking_fingerprint is None
    await client.close()
