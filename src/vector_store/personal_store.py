"""Personal Lab-bound vector and semantic-cache capabilities."""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final

from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models as qmodels

from src.vector_store.contracts import VectorStoreError
from src.vector_store.document_replacement import (
    ReplacementCommit,
    replace_personal_document,
)
from src.vector_store.models import (
    DenseVector,
    DocumentMetadata,
    DocumentReplacement,
    JsonValue,
    PersonalVectorScope,
    SparseVector,
    VectorRecord,
    VectorSearchHit,
)
from src.vector_store.pagination import ListingPage, listing_paginator
from src.vector_store.qdrant_translation import (
    to_qdrant_point,
    to_qdrant_sparse,
    to_search_hit,
    translated_errors,
    unavailable_error,
)
from src.vector_store.strategy_payloads import document_metadata

if TYPE_CHECKING:
    from collections.abc import Sequence

_DENSE: Final = "dense"
_SPARSE: Final = "sparse"
_DOCUMENT: Final = "document_chunk"
_CACHE: Final = "semantic_cache"
_CACHE_THRESHOLD: Final = 0.92
_MAX_SEARCH_LIMIT: Final = 100
_CACHE_NAMESPACE: Final = uuid.UUID("30e0509c-81ae-4f79-985e-98f20ab9df0b")
_BACKEND_ERRORS: Final = (OSError, RuntimeError, ValueError)


class PersonalVectorSearchError(ValueError):
    """Reject unbounded Personal Lab search requests."""

    def __init__(self) -> None:
        super().__init__("personal_vector_search_invalid")


@dataclass(frozen=True, slots=True)
class PersonalVectorSearch:
    """Bounded query with no browser-selectable collection."""

    dense: DenseVector
    sparse: SparseVector | None = None
    limit: int = 10
    score_threshold: float | None = None

    def __post_init__(self) -> None:
        if self.limit < 1 or self.limit > _MAX_SEARCH_LIMIT:
            raise PersonalVectorSearchError


@dataclass(frozen=True, slots=True)
class PersonalCacheHit:
    """One semantic-cache answer from the caller's Personal Lab."""

    answer: str
    score: float


@dataclass(frozen=True, slots=True)
class PersonalRagStore:
    """Expose RAG operations bound to one trusted Personal Lab scope."""

    client: AsyncQdrantClient
    scope: PersonalVectorScope

    async def ensure_ready(self, *, dense_size: int = 384) -> None:
        """Create this scope's dense+sparse collection when absent."""
        try:
            async with translated_errors():
                if await self.client.collection_exists(self.scope.collection_name):
                    return
                await self.client.create_collection(
                    collection_name=self.scope.collection_name,
                    vectors_config={
                        _DENSE: qmodels.VectorParams(
                            size=dense_size, distance=qmodels.Distance.COSINE
                        )
                    },
                    sparse_vectors_config={
                        _SPARSE: qmodels.SparseVectorParams(
                            index=qmodels.SparseIndexParams(on_disk=False)
                        )
                    },
                )
        except VectorStoreError:
            raise
        except _BACKEND_ERRORS:
            raise unavailable_error() from None

    async def search_documents(
        self, query: PersonalVectorSearch
    ) -> tuple[VectorSearchHit, ...]:
        """Search document chunks only in the resolved Personal collection."""
        return await self._search(query, _filter(_DOCUMENT))

    async def find_document(self, filename: str) -> DocumentMetadata | None:
        """Find a filename only inside this Personal Lab."""
        points = await _scroll(self, _filter(_DOCUMENT, source=filename), limit=1)
        if not points:
            return None
        payload = points[0].payload or {}
        doc_id = str(payload.get("doc_id", ""))
        return document_metadata(payload, doc_id=doc_id, filename=filename)

    async def replace_document(
        self,
        replacement: DocumentReplacement,
        *,
        after_publish: ReplacementCommit | None = None,
    ) -> int:
        """Atomically replace one Personal document and invalidate its cache."""
        await _invalidate_cache(self)

        async def upsert(records: Sequence[VectorRecord]) -> None:
            await self._upsert(records)

        return await replace_personal_document(
            self.client,
            self.scope.collection_name,
            upsert,
            replacement,
            after_publish=after_publish,
        )

    async def list_documents(self, cursor: str | None = None) -> ListingPage:
        """List only documents in this collection-bound cursor scope."""
        return await listing_paginator.scoped_documents(
            self.client, self.scope.collection_name, cursor
        )

    async def list_chunks(self, doc_id: str, cursor: str | None = None) -> ListingPage:
        """List only chunks in this collection and document scope."""
        return await listing_paginator.scoped_chunks(
            self.client, self.scope.collection_name, doc_id, cursor
        )

    async def delete_document(self, doc_id: str) -> int:
        """Delete one Personal document and its dependent cache."""
        filters = _filter(_DOCUMENT, doc_id=doc_id)
        deleted = await _count(self, filters)
        await _delete(self, filters)
        await _invalidate_cache(self)
        listing_paginator.invalidate_scoped_document(self.scope.collection_name, doc_id)
        return deleted

    async def clear_documents(self) -> int:
        """Clear documents and cache without deleting the Personal collection."""
        filters = _filter(_DOCUMENT)
        deleted = await _count(self, filters)
        await _delete(self, filters)
        await _invalidate_cache(self)
        listing_paginator.clear_scope(self.scope.collection_name)
        return deleted

    async def save_cache(
        self, fingerprint: str, query: str, answer: str, dense: DenseVector
    ) -> None:
        """Save a semantic answer under scope and settings fingerprint."""
        query_hash = hashlib.sha256(query.strip().casefold().encode()).hexdigest()
        point_id = str(
            uuid.uuid5(
                _CACHE_NAMESPACE,
                f"{self.scope.scope_id.hex}:{fingerprint}:{query_hash}",
            )
        )
        await self._upsert(
            (
                VectorRecord(
                    point_id,
                    dense,
                    {
                        "record_type": _CACHE,
                        "config_fingerprint": fingerprint,
                        "answer": answer,
                        "timestamp": datetime.now(UTC).isoformat(),
                    },
                ),
            )
        )

    async def lookup_cache(
        self, fingerprint: str, dense: DenseVector
    ) -> PersonalCacheHit | None:
        """Read a semantic answer only from this scope and fingerprint."""
        hits = await self._search(
            PersonalVectorSearch(dense, limit=1, score_threshold=_CACHE_THRESHOLD),
            _filter(_CACHE, fingerprint=fingerprint),
        )
        if not hits:
            return None
        answer = hits[0].payload.get("answer")
        return (
            PersonalCacheHit(answer, hits[0].score) if isinstance(answer, str) else None
        )

    async def _search(
        self, query: PersonalVectorSearch, filters: qmodels.Filter
    ) -> tuple[VectorSearchHit, ...]:
        try:
            async with translated_errors():
                if query.sparse is None:
                    response = await self.client.query_points(
                        collection_name=self.scope.collection_name,
                        query=list(query.dense.values),
                        using=_DENSE,
                        query_filter=filters,
                        limit=query.limit,
                        with_payload=True,
                        score_threshold=query.score_threshold,
                    )
                else:
                    response = await self.client.query_points(
                        collection_name=self.scope.collection_name,
                        prefetch=[
                            qmodels.Prefetch(
                                query=list(query.dense.values),
                                using=_DENSE,
                                filter=filters,
                                limit=query.limit * 3,
                            ),
                            qmodels.Prefetch(
                                query=to_qdrant_sparse(query.sparse),
                                using=_SPARSE,
                                filter=filters,
                                limit=query.limit * 3,
                            ),
                        ],
                        query=qmodels.FusionQuery(fusion=qmodels.Fusion.RRF),
                        query_filter=filters,
                        limit=query.limit,
                        with_payload=True,
                        score_threshold=query.score_threshold,
                    )
        except VectorStoreError:
            raise
        except _BACKEND_ERRORS:
            raise unavailable_error() from None
        return tuple(to_search_hit(point) for point in response.points)

    async def _upsert(self, records: Sequence[VectorRecord]) -> None:
        try:
            await self.client.upsert(
                collection_name=self.scope.collection_name,
                points=[to_qdrant_point(record) for record in records],
                wait=True,
            )
        except _BACKEND_ERRORS:
            raise unavailable_error() from None


def _filter(
    record_type: str,
    *,
    doc_id: str | None = None,
    source: str | None = None,
    fingerprint: str | None = None,
) -> qmodels.Filter:
    conditions: list[qmodels.Condition] = [
        qmodels.FieldCondition(
            key="record_type", match=qmodels.MatchValue(value=record_type)
        )
    ]
    for key, value in (
        ("doc_id", doc_id),
        ("source", source),
        ("config_fingerprint", fingerprint),
    ):
        if value is not None:
            conditions.append(
                qmodels.FieldCondition(key=key, match=qmodels.MatchValue(value=value))
            )
    return qmodels.Filter(must=conditions)


async def _scroll(
    store: PersonalRagStore, filters: qmodels.Filter, *, limit: int
) -> list[qmodels.Record]:
    try:
        points, _ = await store.client.scroll(
            collection_name=store.scope.collection_name,
            scroll_filter=filters,
            limit=limit,
            with_payload=True,
            with_vectors=False,
        )
    except _BACKEND_ERRORS:
        raise unavailable_error() from None
    return [qmodels.Record.model_validate(point) for point in points]


async def _count(store: PersonalRagStore, filters: qmodels.Filter) -> int:
    try:
        result = await store.client.count(
            collection_name=store.scope.collection_name,
            count_filter=filters,
            exact=True,
        )
    except _BACKEND_ERRORS:
        raise unavailable_error() from None
    return int(result.count)


async def _delete(store: PersonalRagStore, filters: qmodels.Filter) -> None:
    try:
        await store.client.delete(
            collection_name=store.scope.collection_name,
            points_selector=qmodels.FilterSelector(filter=filters),
            wait=True,
        )
    except _BACKEND_ERRORS:
        raise unavailable_error() from None


async def _invalidate_cache(store: PersonalRagStore) -> None:
    await _delete(store, _filter(_CACHE))


def personal_documents_response(page: ListingPage) -> dict[str, object]:
    """Serialize one bounded Personal document page for the HTTP adapter."""
    return {
        "documents": tuple(
            {
                "doc_id": str(item.payload.get("doc_id", "")),
                "filename": str(item.payload.get("source", "")),
                "chunk_count": _payload_int(item.payload.get("total_chunks")),
                "strategy": str(item.payload.get("strategy", "recursive")),
            }
            for item in page.items
        ),
        "next_cursor": page.next_cursor,
        "truncated": page.truncated,
    }


def personal_chunks_response(page: ListingPage) -> dict[str, object]:
    """Serialize one bounded Personal chunk page for the HTTP adapter."""
    return {
        "chunks": tuple(
            {
                "point_id": item.point_id,
                "text": str(item.payload.get("text", "")),
                "chunk_index": _payload_int(item.payload.get("chunk_index")),
                "strategy": str(item.payload.get("strategy", "recursive")),
                "csv_row": (
                    _payload_int(item.payload["csv_row"])
                    if "csv_row" in item.payload
                    else None
                ),
            }
            for item in page.items
        ),
        "next_cursor": page.next_cursor,
        "truncated": page.truncated,
    }


def _payload_int(value: JsonValue | None) -> int:
    match value:
        case bool():
            return int(value)
        case int():
            return value
        case float():
            return int(value)
        case str():
            try:
                return int(value)
            except ValueError:
                return 0
        case None | list() | dict():
            return 0
