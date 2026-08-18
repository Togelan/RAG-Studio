"""Compensating document replacement and metadata enrichment."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from types import MappingProxyType
from typing import Final

import anyio
from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models as qmodels

from src.vector_store import document_index
from src.vector_store.contracts import VectorStoreError, VectorStoreErrorCode
from src.vector_store.models import (
    DocumentMetadata,
    DocumentReplacement,
    PointId,
    VectorCollection,
    VectorRecord,
)
from src.vector_store.strategy_payloads import (
    chunking_settings,
    optional_text,
    schema_version,
    strategy,
)
from src.vector_store.workspace_collections import ResolvedWorkspaceCollection

_MAX_DOCUMENT_POINTS: Final = 10_000
EnsureCollection = Callable[[VectorCollection], Awaitable[None]]
UpsertRecords = Callable[[str, Sequence[VectorRecord]], Awaitable[None]]
TenantUpsertRecords = Callable[[Sequence[VectorRecord]], Awaitable[None]]


async def replace_document(
    client: AsyncQdrantClient,
    ensure_collection: EnsureCollection,
    upsert: UpsertRecords,
    replacement: DocumentReplacement,
) -> int:
    """Replace one complete document with compensating rollback on interruption."""
    from src.ingestion.embedder import COLLECTION_NAME

    await ensure_collection(VectorCollection(COLLECTION_NAME, 384, sparse=True))
    return await _replace_in_collection(
        client,
        COLLECTION_NAME,
        lambda records: upsert(COLLECTION_NAME, records),
        replacement,
        maintain_legacy_index=True,
    )


async def replace_tenant_document(
    resolved: ResolvedWorkspaceCollection,
    upsert: TenantUpsertRecords,
    replacement: DocumentReplacement,
) -> int:
    """Replace a document through an already authorized workspace capability."""
    return await _replace_in_collection(
        resolved.client,
        resolved.name,
        upsert,
        replacement,
        maintain_legacy_index=False,
    )


async def _replace_in_collection(
    client: AsyncQdrantClient,
    collection_name: str,
    upsert: TenantUpsertRecords,
    replacement: DocumentReplacement,
    *,
    maintain_legacy_index: bool,
) -> int:
    previous_points = await _snapshot_document_points(
        client, collection_name, replacement.doc_id
    )
    previous_index = (
        await document_index.read_index_document(client, replacement.doc_id)
        if maintain_legacy_index
        else None
    )
    metadata = _replacement_metadata(replacement)
    records = _records_with_metadata(
        replacement,
        metadata,
        record_type=None if maintain_legacy_index else "document_chunk",
    )
    completed = False
    try:
        await _publish_replacement(
            client,
            collection_name,
            upsert,
            replacement,
            records,
            metadata,
            maintain_legacy_index=maintain_legacy_index,
        )
        completed = True
    finally:
        if not completed:
            with anyio.CancelScope(shield=True):
                await _restore_document_points(
                    client, collection_name, replacement.doc_id, previous_points
                )
                if maintain_legacy_index:
                    await document_index.restore_index_document(
                        client, replacement.doc_id, previous_index
                    )
    return len(replacement.records)


async def _publish_replacement(
    client: AsyncQdrantClient,
    collection_name: str,
    upsert: TenantUpsertRecords,
    replacement: DocumentReplacement,
    records: tuple[VectorRecord, ...],
    metadata: DocumentMetadata,
    *,
    maintain_legacy_index: bool,
) -> None:
    await upsert(records)
    await client.delete(
        collection_name=collection_name,
        points_selector=qmodels.FilterSelector(
            filter=qmodels.Filter(
                must=[
                    qmodels.FieldCondition(
                        key="doc_id", match=qmodels.MatchValue(value=replacement.doc_id)
                    )
                ],
                must_not=[
                    qmodels.HasIdCondition(
                        has_id=[record.point_id for record in records]
                    )
                ],
            )
        ),
        wait=True,
    )
    if maintain_legacy_index:
        await document_index.index_document(
            client,
            replacement.doc_id,
            replacement.filename,
            len(records),
            replacement.chunk_size,
            replacement.chunk_overlap,
            replacement.created_at,
            metadata=metadata,
        )


async def _snapshot_document_points(
    client: AsyncQdrantClient, collection_name: str, doc_id: str
) -> tuple[qmodels.PointStruct, ...]:
    points: list[qmodels.PointStruct] = []
    offset: PointId | None = None
    while True:
        page, offset = await client.scroll(
            collection_name=collection_name,
            scroll_filter=_document_filter(doc_id),
            limit=1_000,
            offset=offset,
            with_payload=True,
            with_vectors=True,
        )
        points.extend(
            qmodels.PointStruct.model_validate(
                {"id": point.id, "vector": point.vector, "payload": point.payload}
            )
            for point in page
        )
        if len(points) > _MAX_DOCUMENT_POINTS:
            raise VectorStoreError(
                VectorStoreErrorCode.INVALID_REQUEST, retryable=False
            )
        if offset is None:
            return tuple(points)


async def _restore_document_points(
    client: AsyncQdrantClient,
    collection_name: str,
    doc_id: str,
    points: tuple[qmodels.PointStruct, ...],
) -> None:
    await client.delete(
        collection_name=collection_name,
        points_selector=qmodels.FilterSelector(filter=_document_filter(doc_id)),
        wait=True,
    )
    if points:
        await client.upsert(
            collection_name=collection_name,
            points=list(points),
            wait=True,
        )


def _replacement_metadata(replacement: DocumentReplacement) -> DocumentMetadata:
    payload = dict(replacement.records[0].payload) if replacement.records else {}
    fingerprint = replacement.chunking_fingerprint or optional_text(
        payload.get("chunking_fingerprint")
    )
    settings = dict(replacement.chunking_settings) or chunking_settings(
        payload.get("chunking_settings", payload.get("chunking"))
    )
    return DocumentMetadata(
        doc_id=replacement.doc_id,
        filename=replacement.filename,
        file_hash=replacement.file_hash or str(payload.get("file_hash", "")),
        chunk_count=len(replacement.records),
        chunk_size=replacement.chunk_size,
        chunk_overlap=replacement.chunk_overlap,
        strategy=strategy(payload, replacement.strategy),
        schema_version=schema_version(payload, replacement.schema_version),
        chunking_fingerprint=fingerprint,
        chunking_settings=MappingProxyType(settings),
    )


def _records_with_metadata(
    replacement: DocumentReplacement,
    metadata: DocumentMetadata,
    *,
    record_type: str | None,
) -> tuple[VectorRecord, ...]:
    records: list[VectorRecord] = []
    for record in replacement.records:
        payload = dict(record.payload)
        payload.update(
            {
                "doc_id": replacement.doc_id,
                "source": replacement.filename,
                "total_chunks": len(replacement.records),
                "chunk_size": replacement.chunk_size,
                "chunk_overlap": replacement.chunk_overlap,
                "created_at": replacement.created_at,
                "file_hash": metadata.file_hash,
                "strategy": metadata.strategy,
                "schema_version": metadata.schema_version,
                "chunking_strategy": metadata.strategy,
                "chunking_schema_version": metadata.schema_version,
            }
        )
        if metadata.chunking_fingerprint is not None:
            payload["chunking_fingerprint"] = metadata.chunking_fingerprint
        if metadata.chunking_settings:
            payload["chunking_settings"] = dict(metadata.chunking_settings)
        if record_type is not None:
            payload["record_type"] = record_type
        records.append(
            VectorRecord(
                point_id=record.point_id,
                dense=record.dense,
                payload=MappingProxyType(payload),
                sparse=record.sparse,
            )
        )
    return tuple(records)


def _document_filter(doc_id: str) -> qmodels.Filter:
    return qmodels.Filter(
        must=[
            qmodels.FieldCondition(key="doc_id", match=qmodels.MatchValue(value=doc_id))
        ]
    )
