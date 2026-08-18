"""Workspace-bound vector capabilities for SaaS RAG operations."""

from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final
from uuid import UUID

from qdrant_client.http import models as qmodels

from src.vector_store.contracts import VectorStoreError
from src.vector_store.models import (
    DenseVector,
    DocumentMetadata,
    DocumentReplacement,
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

    from src.vector_store.workspace_collections import ResolvedWorkspaceCollection

_DENSE_VECTOR_NAME: Final = "dense"
_SPARSE_VECTOR_NAME: Final = "sparse"
_DOCUMENT_RECORD: Final = "document_chunk"
_CACHE_RECORD: Final = "semantic_cache"
_CACHE_THRESHOLD: Final = 0.92
_PREFETCH_MULTIPLIER: Final = 3
_MAX_SEARCH_LIMIT: Final = 100
_CACHE_NAMESPACE: Final = uuid.UUID("d1305f7d-a807-43b0-b59f-c339320dd63a")
_CONFIG_FINGERPRINT: Final = re.compile(r"cfg_[0-9a-f]{64}\Z")
_BACKEND_ERRORS: Final = (OSError, RuntimeError, ValueError)


class TenantVectorSearchError(ValueError):
    """Signal invalid tenant search bounds."""

    def __init__(self) -> None:
        super().__init__("tenant_vector_search_invalid")


class TenantCacheScopeError(ValueError):
    """Signal an invalid chatbot configuration fingerprint."""

    def __init__(self) -> None:
        super().__init__("tenant_cache_scope_invalid")


@dataclass(frozen=True, slots=True)
class TenantVectorSearch:
    """A bounded tenant search with no caller-selectable collection."""

    dense: DenseVector
    sparse: SparseVector | None = None
    limit: int = 10
    score_threshold: float | None = None

    def __post_init__(self) -> None:
        if self.limit < 1 or self.limit > _MAX_SEARCH_LIMIT:
            raise TenantVectorSearchError


@dataclass(frozen=True, slots=True)
class TenantCacheScope:
    """One validated chatbot configuration cache namespace."""

    config_fingerprint: str

    def __post_init__(self) -> None:
        if _CONFIG_FINGERPRINT.fullmatch(self.config_fingerprint) is None:
            raise TenantCacheScopeError


@dataclass(frozen=True, slots=True)
class SemanticCacheHit:
    """A tenant-scoped semantic-cache answer."""

    answer: str
    score: float


def semantic_cache_point_id(
    workspace_id: UUID, scope: TenantCacheScope, query: str
) -> str:
    """Derive an opaque cache point ID from every required scope dimension."""
    query_digest = hashlib.sha256(query.strip().casefold().encode()).hexdigest()
    material = f"{workspace_id.hex}:{scope.config_fingerprint}:{query_digest}"
    return str(uuid.uuid5(_CACHE_NAMESPACE, material))


@dataclass(frozen=True, slots=True)
class TenantRagStore:
    """Expose RAG operations already bound to one authorized workspace."""

    resolved: ResolvedWorkspaceCollection

    async def search_documents(
        self, query: TenantVectorSearch
    ) -> tuple[VectorSearchHit, ...]:
        """Search only document chunks in the trusted workspace collection."""
        return await self._search(query, _record_filter(_DOCUMENT_RECORD))

    async def find_document(self, filename: str) -> DocumentMetadata | None:
        """Find one canonical filename only inside the trusted workspace."""
        filters = _record_filter(_DOCUMENT_RECORD, source=filename)
        points = await self._scroll(filters, limit=1)
        if not points:
            return None
        payload = points[0].payload or {}
        doc_id = str(payload.get("doc_id", ""))
        return document_metadata(payload, doc_id=doc_id, filename=filename)

    async def replace_document(self, replacement: DocumentReplacement) -> int:
        """Replace one complete document inside the bound workspace."""
        from src.vector_store.document_replacement import replace_tenant_document

        await self._invalidate_cache()

        async def upsert(records: Sequence[VectorRecord]) -> None:
            await self._upsert(records)

        return await replace_tenant_document(self.resolved, upsert, replacement)

    async def list_documents(self, cursor: str | None = None) -> ListingPage:
        """List documents through collection-bound signed snapshots."""
        return await listing_paginator.scoped_documents(
            self.resolved.client, self.resolved.name, cursor
        )

    async def list_chunks(
        self, doc_id: str, cursor: str | None = None
    ) -> ListingPage:
        """List chunks through collection-bound signed snapshots."""
        return await listing_paginator.scoped_chunks(
            self.resolved.client, self.resolved.name, doc_id, cursor
        )

    async def delete_document(self, doc_id: str) -> int:
        """Delete one document and dependent cache inside the bound workspace."""
        filters = _record_filter(_DOCUMENT_RECORD, doc_id=doc_id)
        deleted = await self._count(filters)
        await self._delete(filters)
        await self._invalidate_cache()
        listing_paginator.invalidate_scoped_document(self.resolved.name, doc_id)
        return deleted

    async def clear_documents(self) -> int:
        """Clear document and cache records without deleting tenant storage."""
        document_filter = _record_filter(_DOCUMENT_RECORD)
        deleted = await self._count(document_filter)
        await self._delete(document_filter)
        await self._invalidate_cache()
        listing_paginator.clear_scope(self.resolved.name)
        return deleted

    async def save_cache(
        self,
        scope: TenantCacheScope,
        query: str,
        answer: str,
        dense: DenseVector,
    ) -> None:
        """Persist an answer inside the bound workspace and chatbot config."""
        point_id = semantic_cache_point_id(
            self.resolved.context.workspace_id, scope, query
        )
        record = VectorRecord(
            point_id=point_id,
            dense=dense,
            payload={
                "record_type": _CACHE_RECORD,
                "config_fingerprint": scope.config_fingerprint,
                "answer": answer,
                "timestamp": datetime.now(UTC).isoformat(),
            },
        )
        await self._upsert((record,))

    async def lookup_cache(
        self, scope: TenantCacheScope, dense: DenseVector
    ) -> SemanticCacheHit | None:
        """Find a cache answer only inside the bound workspace and config."""
        filters = _record_filter(
            _CACHE_RECORD, config_fingerprint=scope.config_fingerprint
        )
        hits = await self._search(
            TenantVectorSearch(dense, limit=1, score_threshold=_CACHE_THRESHOLD),
            filters,
        )
        if not hits:
            return None
        answer = hits[0].payload.get("answer")
        if not isinstance(answer, str):
            return None
        return SemanticCacheHit(answer, hits[0].score)

    async def is_ready(self) -> bool:
        """Probe the bound collection without exposing its identifier."""
        try:
            if not await self.resolved.client.collection_exists(self.resolved.name):
                return False
            await self.resolved.client.get_collection(self.resolved.name)
        except (*_BACKEND_ERRORS, VectorStoreError):
            return False
        return True

    async def _search(
        self, query: TenantVectorSearch, filters: qmodels.Filter
    ) -> tuple[VectorSearchHit, ...]:
        try:
            async with translated_errors():
                response = await self._query_points(query, filters)
        except VectorStoreError:
            raise
        except _BACKEND_ERRORS:
            raise unavailable_error() from None
        return tuple(to_search_hit(point) for point in response.points)

    async def _query_points(
        self, query: TenantVectorSearch, filters: qmodels.Filter
    ) -> qmodels.QueryResponse:
        if query.sparse is None:
            return await self.resolved.client.query_points(
                collection_name=self.resolved.name,
                query=list(query.dense.values),
                using=_DENSE_VECTOR_NAME,
                query_filter=filters,
                limit=query.limit,
                with_payload=True,
                score_threshold=query.score_threshold,
            )
        prefetch = [
            qmodels.Prefetch(
                query=list(query.dense.values),
                using=_DENSE_VECTOR_NAME,
                filter=filters,
                limit=query.limit * _PREFETCH_MULTIPLIER,
            ),
            qmodels.Prefetch(
                query=to_qdrant_sparse(query.sparse),
                using=_SPARSE_VECTOR_NAME,
                filter=filters,
                limit=query.limit * _PREFETCH_MULTIPLIER,
            ),
        ]
        return await self.resolved.client.query_points(
            collection_name=self.resolved.name,
            prefetch=prefetch,
            query=qmodels.FusionQuery(fusion=qmodels.Fusion.RRF),
            query_filter=filters,
            limit=query.limit,
            with_payload=True,
            score_threshold=query.score_threshold,
        )

    async def _scroll(
        self, filters: qmodels.Filter, *, limit: int
    ) -> list[qmodels.Record]:
        try:
            points, _ = await self.resolved.client.scroll(
                collection_name=self.resolved.name,
                scroll_filter=filters,
                limit=limit,
                with_payload=True,
                with_vectors=False,
            )
        except _BACKEND_ERRORS:
            raise unavailable_error() from None
        return [qmodels.Record.model_validate(point) for point in points]

    async def _upsert(self, records: Sequence[VectorRecord]) -> None:
        try:
            await self.resolved.client.upsert(
                collection_name=self.resolved.name,
                points=[to_qdrant_point(record) for record in records],
                wait=True,
            )
        except _BACKEND_ERRORS:
            raise unavailable_error() from None

    async def _count(self, filters: qmodels.Filter) -> int:
        try:
            result = await self.resolved.client.count(
                collection_name=self.resolved.name,
                count_filter=filters,
                exact=True,
            )
        except _BACKEND_ERRORS:
            raise unavailable_error() from None
        return int(result.count)

    async def _delete(self, filters: qmodels.Filter) -> None:
        try:
            await self.resolved.client.delete(
                collection_name=self.resolved.name,
                points_selector=qmodels.FilterSelector(filter=filters),
                wait=True,
            )
        except _BACKEND_ERRORS:
            raise unavailable_error() from None

    async def _invalidate_cache(self) -> None:
        await self._delete(_record_filter(_CACHE_RECORD))


def _record_filter(
    record_type: str,
    *,
    doc_id: str | None = None,
    source: str | None = None,
    config_fingerprint: str | None = None,
) -> qmodels.Filter:
    conditions: list[qmodels.Condition] = [
        qmodels.FieldCondition(
            key="record_type", match=qmodels.MatchValue(value=record_type)
        )
    ]
    for key, value in (
        ("doc_id", doc_id),
        ("source", source),
        ("config_fingerprint", config_fingerprint),
    ):
        if value is not None:
            conditions.append(
                qmodels.FieldCondition(key=key, match=qmodels.MatchValue(value=value))
            )
    return qmodels.Filter(must=conditions)
