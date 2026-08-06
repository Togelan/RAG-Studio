from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Final

import anyio
from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models as qmodels

from src.vector_store.models import DocumentMetadata, JsonValue
from src.vector_store.strategy_payloads import (
    document_payload,
    json_payload,
    metadata_payload,
)

DOCUMENT_INDEX_COLLECTION: Final = "rag_studio_document_index"
_INDEX_NAMESPACE: Final = uuid.UUID("4daf3bd4-66a5-4e32-9d11-a2ad0d35822c")
_STATE_POINT_ID: Final = str(uuid.uuid5(_INDEX_NAMESPACE, "backfill-state"))
_SOURCE_PAGE_SIZE: Final = 100
_MAX_SOURCE_PAGES: Final = 10
_INDEX_CREATION_LOCK: Final = anyio.Lock()


@dataclass(frozen=True, slots=True)
class IndexedDocument:
    point_id: str
    payload: dict[str, JsonValue]


@dataclass(frozen=True, slots=True)
class IndexPreparation:
    complete: bool
    already_complete: bool
    resumed: bool
    documents: tuple[IndexedDocument, ...]
    scanned_points: int


async def prepare_document_index(
    client: AsyncQdrantClient,
    source_collection: str,
) -> IndexPreparation:
    """Advance legacy backfill by one bounded segment."""
    await _ensure_index(client)
    state = await _read_state(client)
    if state.complete:
        return IndexPreparation(True, True, False, (), 0)

    offset = state.offset
    resumed = offset is not None
    documents: dict[str, IndexedDocument] = {}
    scanned = 0
    next_offset: int | str | None = offset
    for _ in range(_MAX_SOURCE_PAGES):
        points, raw_next = await client.scroll(
            collection_name=source_collection,
            limit=_SOURCE_PAGE_SIZE,
            with_payload=[
                "doc_id",
                "source",
                "created_at",
                "total_chunks",
                "chunk_size",
                "chunk_overlap",
                "file_hash",
                "strategy",
                "schema_version",
                "chunking_strategy",
                "chunking_schema_version",
                "chunking_fingerprint",
                "chunking_settings",
                "parent_size",
                "window_sentences",
            ],
            with_vectors=False,
            offset=next_offset,
        )
        remaining = _SOURCE_PAGE_SIZE * _MAX_SOURCE_PAGES - scanned
        accepted_points = points[:remaining]
        response_exceeded_cap = len(points) > len(accepted_points)
        scanned += len(accepted_points)
        for point in accepted_points:
            payload = document_payload(point.payload or {})
            doc_id = str(payload.get("doc_id", ""))
            if doc_id and doc_id not in documents:
                documents[doc_id] = IndexedDocument(_index_id(doc_id), payload)
        next_offset = _offset(raw_next)
        if response_exceeded_cap and accepted_points:
            next_offset = _offset(accepted_points[-1].id)
        if next_offset is None:
            break
        if scanned >= _SOURCE_PAGE_SIZE * _MAX_SOURCE_PAGES:
            break

    complete = next_offset is None
    records = [_point(document) for document in documents.values()]
    records.append(_state_point(complete, next_offset))
    await client.upsert(
        collection_name=DOCUMENT_INDEX_COLLECTION,
        points=records,
        wait=True,
    )
    return IndexPreparation(
        complete=complete,
        already_complete=False,
        resumed=resumed,
        documents=tuple(documents.values()),
        scanned_points=scanned,
    )


async def index_document(
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
    """Insert or replace one maintained document metadata record."""
    await _ensure_index(client)
    persisted = metadata or DocumentMetadata(
        doc_id=doc_id,
        filename=filename,
        file_hash="",
        chunk_count=chunks_count,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )
    document = IndexedDocument(
        point_id=_index_id(doc_id),
        payload=metadata_payload(persisted, created_at),
    )
    await client.upsert(
        collection_name=DOCUMENT_INDEX_COLLECTION,
        points=[_point(document)],
        wait=True,
    )


async def delete_index_document(client: AsyncQdrantClient, doc_id: str) -> None:
    """Delete one maintained document metadata record if the index exists."""
    if not await client.collection_exists(DOCUMENT_INDEX_COLLECTION):
        return
    await client.delete(
        collection_name=DOCUMENT_INDEX_COLLECTION,
        points_selector=qmodels.PointIdsList(points=[_index_id(doc_id)]),
        wait=True,
    )


async def clear_document_index(client: AsyncQdrantClient) -> None:
    """Remove only the document index collection during application clear."""
    if await client.collection_exists(DOCUMENT_INDEX_COLLECTION):
        await client.delete_collection(collection_name=DOCUMENT_INDEX_COLLECTION)


async def read_index_document(
    client: AsyncQdrantClient, doc_id: str
) -> IndexedDocument | None:
    """Read one raw index record for replacement compensation."""
    if not await client.collection_exists(DOCUMENT_INDEX_COLLECTION):
        return None
    points = await client.retrieve(
        collection_name=DOCUMENT_INDEX_COLLECTION,
        ids=[_index_id(doc_id)],
        with_payload=True,
        with_vectors=False,
    )
    if not points:
        return None
    return IndexedDocument(_index_id(doc_id), json_payload(points[0].payload or {}))


async def restore_index_document(
    client: AsyncQdrantClient,
    doc_id: str,
    previous: IndexedDocument | None,
) -> None:
    """Restore an index snapshot after an interrupted replacement."""
    if previous is None:
        await delete_index_document(client, doc_id)
        return
    await _ensure_index(client)
    await client.upsert(
        collection_name=DOCUMENT_INDEX_COLLECTION,
        points=[_point(previous)],
        wait=True,
    )


async def _ensure_index(client: AsyncQdrantClient) -> None:
    async with _INDEX_CREATION_LOCK:
        if await client.collection_exists(DOCUMENT_INDEX_COLLECTION):
            return
        await client.create_collection(
            collection_name=DOCUMENT_INDEX_COLLECTION,
            vectors_config={},
        )


@dataclass(frozen=True, slots=True)
class _IndexState:
    complete: bool
    offset: int | str | None


async def _read_state(client: AsyncQdrantClient) -> _IndexState:
    points = await client.retrieve(
        collection_name=DOCUMENT_INDEX_COLLECTION,
        ids=[_STATE_POINT_ID],
        with_payload=True,
        with_vectors=False,
    )
    if not points:
        return _IndexState(False, None)
    payload = points[0].payload or {}
    return _IndexState(
        complete=payload.get("complete") is True,
        offset=_offset(payload.get("offset")),
    )


def _state_point(complete: bool, offset: int | str | None) -> qmodels.PointStruct:
    return qmodels.PointStruct(
        id=_STATE_POINT_ID,
        vector={},
        payload={
            "record_type": "backfill_state",
            "complete": complete,
            "offset": offset,
        },
    )


def _point(document: IndexedDocument) -> qmodels.PointStruct:
    return qmodels.PointStruct(
        id=document.point_id,
        vector={},
        payload=document.payload,
    )


def _index_id(doc_id: str) -> str:
    return str(uuid.uuid5(_INDEX_NAMESPACE, doc_id))


def _offset(value: object) -> int | str | None:
    if value is None or isinstance(value, (int, str)):
        return value
    return str(value)
