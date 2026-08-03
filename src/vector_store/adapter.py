"""Qdrant translation boundary for vector-store capabilities."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from types import MappingProxyType
from typing import Final

from pydantic import ValidationError
from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models as qmodels
from qdrant_client.http.exceptions import (
    ApiException,
    ResponseHandlingException,
    UnexpectedResponse,
)

from src.vector_store.contracts import (
    VectorStore,
    VectorStoreError,
    VectorStoreErrorCode,
)
from src.vector_store.models import (
    DocumentMetadata,
    DocumentReplacement,
    SparseVector,
    VectorCollection,
    VectorRecord,
    VectorSearchHit,
    VectorSearchQuery,
)
from src.vector_store.pagination import MAX_SCANNED_POINTS, ListingPage

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
        try:
            response = await self._query_points(query)
        except ValidationError:
            raise _invalid_request_error() from None
        except UnexpectedResponse as error:
            raise _response_error(error) from None
        except ResponseHandlingException:
            raise _unavailable_error() from None
        except TimeoutError:
            raise _unavailable_error() from None
        except ApiException:
            raise _unavailable_error() from None
        return tuple(_to_search_hit(point) for point in response.points)

    async def upsert(
        self,
        collection_name: str,
        records: Sequence[VectorRecord],
    ) -> None:
        """Translate every record before submitting one atomic Qdrant request."""
        try:
            points = [_to_qdrant_point(record) for record in records]
            await self._client.upsert(
                collection_name=collection_name,
                points=points,
                wait=True,
            )
        except ValidationError:
            raise _invalid_request_error() from None
        except UnexpectedResponse as error:
            raise _response_error(error) from None
        except ResponseHandlingException:
            raise _unavailable_error() from None
        except TimeoutError:
            raise _unavailable_error() from None
        except ApiException:
            raise _unavailable_error() from None

    async def ensure_collection(self, collection: VectorCollection) -> None:
        """Create a named-vector collection through the adapter boundary."""
        try:
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
        except ValidationError:
            raise _invalid_request_error() from None
        except UnexpectedResponse as error:
            raise _response_error(error) from None
        except ResponseHandlingException:
            raise _unavailable_error() from None
        except TimeoutError:
            raise _unavailable_error() from None
        except ApiException:
            raise _unavailable_error() from None

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
            return None
        payload = points[0].payload or {}
        return DocumentMetadata(
            doc_id=str(payload.get("doc_id", doc_id)),
            filename=str(payload.get("source", filename)),
            file_hash=str(payload.get("file_hash", "")),
            chunk_count=int(str(payload.get("total_chunks", 0))),
            chunk_size=int(str(payload.get("chunk_size", 0))),
            chunk_overlap=int(str(payload.get("chunk_overlap", 0))),
        )

    async def replace_document(self, replacement: DocumentReplacement) -> int:
        """Upsert the complete batch before deleting any stale chunk IDs."""
        from src.ingestion.embedder import COLLECTION_NAME
        from src.vector_store.document_index import index_document

        await self.ensure_collection(
            VectorCollection(COLLECTION_NAME, 384, sparse=True)
        )
        await self.upsert(COLLECTION_NAME, replacement.records)
        keep_ids = [record.point_id for record in replacement.records]
        await self._client.delete(
            collection_name=COLLECTION_NAME,
            points_selector=qmodels.FilterSelector(
                filter=qmodels.Filter(
                    must=[
                        qmodels.FieldCondition(
                            key="doc_id",
                            match=qmodels.MatchValue(value=replacement.doc_id),
                        )
                    ],
                    must_not=[qmodels.HasIdCondition(has_id=keep_ids)],
                )
            ),
            wait=True,
        )
        await index_document(
            self._client,
            replacement.doc_id,
            replacement.filename,
            len(replacement.records),
            replacement.chunk_size,
            replacement.chunk_overlap,
            replacement.created_at,
        )
        return len(replacement.records)

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
                query=_to_qdrant_sparse(query.sparse),
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


def _to_qdrant_sparse(vector: SparseVector) -> qmodels.SparseVector:
    return qmodels.SparseVector(
        indices=list(vector.indices),
        values=list(vector.values),
    )


def _to_qdrant_point(record: VectorRecord) -> qmodels.PointStruct:
    vectors: dict[str, qmodels.Vector] = {_DENSE_VECTOR_NAME: list(record.dense.values)}
    if record.sparse is not None:
        vectors[_SPARSE_VECTOR_NAME] = _to_qdrant_sparse(record.sparse)
    return qmodels.PointStruct(
        id=record.point_id,
        vector=vectors,
        payload=dict(record.payload),
    )


def _to_search_hit(point: qmodels.ScoredPoint) -> VectorSearchHit:
    return VectorSearchHit(
        point_id=point.id,
        score=point.score,
        payload=MappingProxyType(dict(point.payload or {})),
    )


def _response_error(error: UnexpectedResponse) -> VectorStoreError:
    status = error.status_code
    if status is not None and 400 <= status < 500 and status != 429:
        return _invalid_request_error()
    return _unavailable_error()


def _invalid_request_error() -> VectorStoreError:
    return VectorStoreError(VectorStoreErrorCode.INVALID_REQUEST, retryable=False)


def _unavailable_error() -> VectorStoreError:
    return VectorStoreError(VectorStoreErrorCode.UNAVAILABLE, retryable=True)
