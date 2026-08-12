"""Qdrant translation boundary for vector-store capabilities."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from typing import Final

from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models as qmodels

from src.vector_store.contracts import VectorStore
from src.vector_store.models import (
    DocumentMetadata,
    DocumentReplacement,
    VectorCollection,
    VectorRecord,
    VectorSearchHit,
    VectorSearchQuery,
)
from src.vector_store.pagination import MAX_SCANNED_POINTS, ListingPage
from src.vector_store.qdrant_translation import (
    to_qdrant_point,
    to_qdrant_sparse,
    to_search_hit,
    translated_errors,
)
from src.vector_store.strategy_payloads import document_metadata

_DENSE_VECTOR_NAME: Final = "dense"
_SPARSE_VECTOR_NAME: Final = "sparse"
_PREFETCH_MULTIPLIER: Final = 3
RawClientFactory = Callable[[], Awaitable[AsyncQdrantClient]]


class QdrantVectorStore:
    """Translate vendor-neutral capabilities to one injected Qdrant client."""

    def __init__(self, client: AsyncQdrantClient) -> None:
        self._client = client

    async def search(self, query: VectorSearchQuery) -> tuple[VectorSearchHit, ...]:
        """Execute a dense or hybrid query and return domain hits."""
        async with translated_errors():
            response = await self._query_points(query)
        return tuple(to_search_hit(point) for point in response.points)

    async def upsert(
        self,
        collection_name: str,
        records: Sequence[VectorRecord],
    ) -> None:
        """Translate every record before submitting one atomic Qdrant request."""
        async with translated_errors():
            points = [to_qdrant_point(record) for record in records]
            await self._client.upsert(
                collection_name=collection_name,
                points=points,
                wait=True,
            )

    async def ensure_collection(self, collection: VectorCollection) -> None:
        """Create a named-vector collection through the adapter boundary."""
        async with translated_errors():
            if await self._client.collection_exists(collection.name):
                return
            sparse_config = (
                {
                    _SPARSE_VECTOR_NAME: qmodels.SparseVectorParams(
                        index=qmodels.SparseIndexParams(on_disk=False)
                    )
                }
                if collection.sparse
                else None
            )
            await self._client.create_collection(
                collection_name=collection.name,
                vectors_config={
                    _DENSE_VECTOR_NAME: qmodels.VectorParams(
                        size=collection.dense_size,
                        distance=qmodels.Distance.COSINE,
                    )
                },
                sparse_vectors_config=sparse_config,
            )

    async def find_document(self, filename: str) -> DocumentMetadata | None:
        """Read one document metadata record without exposing SDK values."""
        from src.ingestion.embedder import COLLECTION_NAME, make_document_doc_id

        await self.ensure_collection(
            VectorCollection(COLLECTION_NAME, 384, sparse=True)
        )
        doc_id = make_document_doc_id(filename)
        points, _ = await self._client.scroll(
            collection_name=COLLECTION_NAME,
            scroll_filter=qmodels.Filter(
                must=[
                    qmodels.FieldCondition(
                        key="doc_id", match=qmodels.MatchValue(value=doc_id)
                    )
                ]
            ),
            limit=1,
            with_payload=True,
            with_vectors=False,
        )
        if not points:
            points, _ = await self._client.scroll(
                collection_name=COLLECTION_NAME,
                scroll_filter=qmodels.Filter(
                    must=[
                        qmodels.FieldCondition(
                            key="source", match=qmodels.MatchValue(value=filename)
                        )
                    ]
                ),
                limit=1,
                with_payload=True,
                with_vectors=False,
            )
        if not points:
            return None
        return document_metadata(
            points[0].payload or {}, doc_id=doc_id, filename=filename
        )

    async def replace_document(self, replacement: DocumentReplacement) -> int:
        """Upsert the complete batch before deleting any stale chunk IDs."""
        from src.vector_store.document_replacement import replace_document

        return await replace_document(
            self._client, self.ensure_collection, self.upsert, replacement
        )

    async def list_documents(self, cursor: str | None = None) -> ListingPage:
        """Return one bounded document page through the existing paginator."""
        from src.ingestion.embedder import COLLECTION_NAME
        from src.vector_store.pagination import listing_paginator

        await self.ensure_collection(
            VectorCollection(COLLECTION_NAME, 384, sparse=True)
        )
        page = await listing_paginator.documents(self._client, COLLECTION_NAME, cursor)
        if (
            page.items
            or cursor is not None
            or page.scanned_points >= MAX_SCANNED_POINTS
        ):
            return page
        raw_points, raw_next = await self._client.scroll(
            collection_name=COLLECTION_NAME,
            limit=100,
            with_payload=True,
            with_vectors=False,
        )
        if raw_next is not None:
            return page
        from src.vector_store.pagination import ListedPoint, ListingPage

        documents: dict[str, ListedPoint] = {}
        for point in raw_points:
            payload = dict(point.payload or {})
            doc_id = str(payload.get("doc_id", ""))
            if doc_id and doc_id not in documents:
                documents[doc_id] = ListedPoint(str(point.id), payload)
        items = tuple(
            sorted(
                documents.values(),
                key=lambda item: (
                    str(item.payload.get("source", "")).casefold(),
                    str(item.payload.get("doc_id", "")),
                ),
            )
        )
        return ListingPage(items, None, False, len(raw_points), len(items))

    async def list_chunks(self, doc_id: str, cursor: str | None = None) -> ListingPage:
        """Return one bounded chunk page through the existing paginator."""
        from src.ingestion.embedder import COLLECTION_NAME
        from src.vector_store.pagination import listing_paginator

        await self.ensure_collection(
            VectorCollection(COLLECTION_NAME, 384, sparse=True)
        )
        return await listing_paginator.chunks(
            self._client, COLLECTION_NAME, doc_id, cursor
        )

    async def delete_document(self, doc_id: str) -> int:
        """Delete document vectors and its maintained index entry."""
        from src.ingestion.embedder import delete_document_points
        from src.vector_store.document_index import delete_index_document
        from src.vector_store.pagination import listing_paginator

        deleted = await delete_document_points(self._client, doc_id)
        await delete_index_document(self._client, doc_id)
        listing_paginator.invalidate_document(doc_id)
        return deleted

    async def clear_documents(self) -> int:
        """Clear document vectors and index, returning the prior point count."""
        from src.ingestion.embedder import COLLECTION_NAME
        from src.vector_store.document_index import clear_document_index
        from src.vector_store.pagination import listing_paginator

        await self.ensure_collection(
            VectorCollection(COLLECTION_NAME, 384, sparse=True)
        )
        count = await self._client.count(collection_name=COLLECTION_NAME)
        await self._client.delete_collection(collection_name=COLLECTION_NAME)
        await clear_document_index(self._client)
        await self.ensure_collection(
            VectorCollection(COLLECTION_NAME, 384, sparse=True)
        )
        listing_paginator.clear()
        return count.count or 0

    async def _query_points(self, query: VectorSearchQuery) -> qmodels.QueryResponse:
        dense = list(query.dense.values)
        if query.sparse is None:
            return await self._client.query_points(
                collection_name=query.collection_name,
                query=dense,
                using=_DENSE_VECTOR_NAME,
                limit=query.limit,
                with_payload=True,
                score_threshold=query.score_threshold,
            )
        prefetch = [
            qmodels.Prefetch(
                query=dense,
                using=_DENSE_VECTOR_NAME,
                limit=query.limit * _PREFETCH_MULTIPLIER,
            ),
            qmodels.Prefetch(
                query=to_qdrant_sparse(query.sparse),
                using=_SPARSE_VECTOR_NAME,
                limit=query.limit * _PREFETCH_MULTIPLIER,
            ),
        ]
        return await self._client.query_points(
            collection_name=query.collection_name,
            prefetch=prefetch,
            query=qmodels.FusionQuery(fusion=qmodels.Fusion.RRF),
            limit=query.limit,
            with_payload=True,
            score_threshold=query.score_threshold,
        )


async def get_vector_store(
    client_factory: RawClientFactory | None = None,
) -> VectorStore:
    """Build an application vector store from an injectable raw-client factory."""
    if client_factory is None:
        from src.vector_store.client import get_qdrant_client

        client_factory = get_qdrant_client
    return QdrantVectorStore(await client_factory())
