from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

import anyio
import pytest
from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models as qmodels

from src.ingestion.embedder import COLLECTION_NAME
from src.vector_store import document_index
from src.vector_store.adapter import QdrantVectorStore
from src.vector_store.models import (
    DenseVector,
    DocumentMetadata,
    DocumentReplacement,
    JsonValue,
    VectorRecord,
)

_METADATA_BY_GENERATION: dict[str, tuple[str, int, str, dict[str, JsonValue]]] = {
    "old": (
        "parent_document",
        3,
        "old-fingerprint",
        {
            "schema_version": 3,
            "strategy": "parent_document",
            "chunk_size": 512,
            "chunk_overlap": 64,
            "parent_size": 2048,
            "window_sentences": None,
        },
    ),
    "new": (
        "static",
        7,
        "new-fingerprint",
        {
            "schema_version": 7,
            "strategy": "static",
            "chunk_size": 256,
            "chunk_overlap": 32,
            "parent_size": None,
            "window_sentences": 5,
        },
    ),
}


def _replacement(doc_id: str, generation: str, count: int) -> DocumentReplacement:
    strategy, schema_version, fingerprint, settings = _METADATA_BY_GENERATION[
        generation
    ]
    records = tuple(
        VectorRecord(
            point_id=str(uuid5(NAMESPACE_URL, f"{doc_id}:{generation}:{index}")),
            dense=DenseVector((float(index + 1) / 10,) * 384),
            payload={
                "doc_id": doc_id,
                "source": f"{doc_id}.txt",
                "text": f"{generation} chunk {index}",
                "generation": generation,
                "chunk_index": index,
                "total_chunks": count,
                "strategy": strategy,
                "schema_version": schema_version,
                "chunking_fingerprint": fingerprint,
                "chunking_settings": settings,
                "start_offset": index * 10,
                "end_offset": index * 10 + 9,
            },
        )
        for index in range(count)
    )
    return DocumentReplacement(
        doc_id=doc_id,
        filename=f"{doc_id}.txt",
        records=records,
        chunk_size=int(settings["chunk_size"]),
        chunk_overlap=int(settings["chunk_overlap"]),
        created_at=f"{generation}-created",
        strategy=strategy,
        schema_version=schema_version,
        file_hash=f"{generation}-hash",
        chunking_fingerprint=fingerprint,
        chunking_settings=settings,
    )


async def _generation_state(
    client: AsyncQdrantClient, doc_id: str
) -> tuple[tuple[Mapping[str, JsonValue], ...], Mapping[str, JsonValue]]:
    points, _ = await client.scroll(
        collection_name=COLLECTION_NAME,
        scroll_filter=document_index.qmodels.Filter(
            must=[
                document_index.qmodels.FieldCondition(
                    key="doc_id", match=document_index.qmodels.MatchValue(value=doc_id)
                )
            ]
        ),
        with_payload=True,
        with_vectors=False,
        limit=100,
    )
    indexed = await document_index.read_index_document(client, doc_id)
    assert indexed is not None
    return tuple(point.payload or {} for point in points), indexed.payload


async def _assert_generation_state(
    client: AsyncQdrantClient,
    doc_id: str,
    generation: str,
    count: int,
) -> None:
    point_payloads, index_payload = await _generation_state(client, doc_id)
    strategy, schema_version, fingerprint, settings = _METADATA_BY_GENERATION[
        generation
    ]
    assert len(point_payloads) == count
    for payload in point_payloads:
        assert payload["generation"] == generation
        assert payload["strategy"] == strategy
        assert payload["schema_version"] == schema_version
        assert payload["chunking_fingerprint"] == fingerprint
        assert payload["chunking_settings"] == settings
    assert index_payload["created_at"] == f"{generation}-created"
    assert index_payload["strategy"] == strategy
    assert index_payload["schema_version"] == schema_version
    assert index_payload["chunking_fingerprint"] == fingerprint
    assert index_payload["chunking_settings"] == settings


@pytest.mark.anyio
@pytest.mark.parametrize("failure_step", ["upsert", "delete", "index"])
async def test_failed_replacement_restores_old_complete_document(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_step: str,
) -> None:
    # Given
    client = AsyncQdrantClient(path=str(tmp_path / failure_step))
    store = QdrantVectorStore(client)
    await store.replace_document(_replacement("doc-a", "old", 3))
    original_upsert = store.upsert
    original_delete = client.delete
    original_index = document_index.index_document
    injected = False

    async def failing_upsert(
        collection_name: str, records: Sequence[VectorRecord]
    ) -> None:
        nonlocal injected
        await original_upsert(collection_name, records)
        if not injected:
            injected = True
            raise RuntimeError("injected_upsert_failure")

    async def failing_delete(
        collection_name: str,
        points_selector: qmodels.PointsSelector,
        wait: bool = True,
    ) -> None:
        nonlocal injected
        await original_delete(collection_name, points_selector, wait=wait)
        if not injected:
            injected = True
            raise RuntimeError("injected_delete_failure")

    async def failing_index(
        client: AsyncQdrantClient,
        doc_id: str,
        filename: str,
        chunks_count: int,
        chunk_size: int,
        chunk_overlap: int,
        created_at: str,
        *,
        metadata: DocumentMetadata | None = None,
    ) -> None:
        nonlocal injected
        await original_index(
            client,
            doc_id,
            filename,
            chunks_count,
            chunk_size,
            chunk_overlap,
            created_at,
            metadata=metadata,
        )
        if not injected:
            injected = True
            raise RuntimeError("injected_index_failure")

    match failure_step:
        case "upsert":
            monkeypatch.setattr(store, "upsert", failing_upsert)
        case "delete":
            monkeypatch.setattr(client, "delete", failing_delete)
        case "index":
            monkeypatch.setattr(document_index, "index_document", failing_index)
        case unreachable:
            raise AssertionError(unreachable)

    # When
    with pytest.raises(RuntimeError, match=f"injected_{failure_step}_failure"):
        await store.replace_document(_replacement("doc-a", "new", 2))

    # Then
    await _assert_generation_state(client, "doc-a", "old", 3)
    await client.close()


@pytest.mark.anyio
async def test_cancelled_replacement_restores_old_complete_document(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    client = AsyncQdrantClient(path=str(tmp_path / "cancel"))
    store = QdrantVectorStore(client)
    await store.replace_document(_replacement("doc-a", "old", 3))
    original_upsert = store.upsert
    upserted = anyio.Event()
    release = anyio.Event()

    async def paused_upsert(
        collection_name: str, records: Sequence[VectorRecord]
    ) -> None:
        await original_upsert(collection_name, records)
        upserted.set()
        await release.wait()

    monkeypatch.setattr(store, "upsert", paused_upsert)

    # When
    async with anyio.create_task_group() as task_group:
        task_group.start_soon(store.replace_document, _replacement("doc-a", "new", 2))
        await upserted.wait()
        task_group.cancel_scope.cancel()

    # Then
    await _assert_generation_state(client, "doc-a", "old", 3)
    await client.close()


@pytest.mark.anyio
async def test_successful_replacement_publishes_new_complete_document(
    tmp_path: Path,
) -> None:
    # Given
    client = AsyncQdrantClient(path=str(tmp_path / "success"))
    store = QdrantVectorStore(client)
    await store.replace_document(_replacement("doc-a", "old", 3))

    # When
    await store.replace_document(_replacement("doc-a", "new", 2))

    # Then
    await _assert_generation_state(client, "doc-a", "new", 2)
    await client.close()
