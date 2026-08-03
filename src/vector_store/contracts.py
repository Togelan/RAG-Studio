"""Application-facing vector-store capability contracts."""

from __future__ import annotations

from collections.abc import Sequence
from enum import StrEnum
from typing import Protocol

from src.vector_store.models import (
    DocumentMetadata,
    DocumentReplacement,
    VectorCollection,
    VectorRecord,
    VectorSearchHit,
    VectorSearchQuery,
)
from src.vector_store.pagination import ListingPage


class VectorStoreErrorCode(StrEnum):
    """Stable error codes safe to expose outside the adapter."""

    INVALID_REQUEST = "vector_store_invalid_request"
    UNAVAILABLE = "vector_store_unavailable"


class VectorStoreError(RuntimeError):
    """A sanitized typed failure from the vector-store boundary."""

    def __init__(self, code: VectorStoreErrorCode, *, retryable: bool) -> None:
        super().__init__(code.value)
        self.code = code
        self.retryable = retryable


class VectorSearcher(Protocol):
    """Capability for bounded dense or hybrid vector search."""

    async def search(self, query: VectorSearchQuery) -> tuple[VectorSearchHit, ...]:
        """Return ranked hits for one domain query."""
        ...


class VectorWriter(Protocol):
    """Capability for atomically submitting one vector batch."""

    async def upsert(
        self,
        collection_name: str,
        records: Sequence[VectorRecord],
    ) -> None:
        """Insert or replace all supplied records in one Qdrant request."""
        ...


class VectorCollectionManager(Protocol):
    """Capability for idempotently preparing a domain collection."""

    async def ensure_collection(self, collection: VectorCollection) -> None:
        """Create the collection when it does not already exist."""
        ...


class DocumentVectorStore(Protocol):
    """Narrow document ingestion and bounded listing capabilities."""

    async def find_document(self, filename: str) -> DocumentMetadata | None:
        """Return persisted metadata for a canonical filename when present."""
        ...

    async def replace_document(self, replacement: DocumentReplacement) -> int:
        """Commit one replacement batch before deleting stale chunks."""
        ...

    async def list_documents(self, cursor: str | None = None) -> ListingPage:
        """Return one bounded document listing page."""
        ...

    async def list_chunks(self, doc_id: str, cursor: str | None = None) -> ListingPage:
        """Return one bounded chunk listing page."""
        ...

    async def delete_document(self, doc_id: str) -> int:
        """Delete one document and its maintained index record."""
        ...

    async def clear_documents(self) -> int:
        """Clear document vectors and maintained index records."""
        ...


class VectorStore(
    VectorSearcher, VectorWriter, VectorCollectionManager, DocumentVectorStore, Protocol
):
    """The combined vector capabilities used by application consumers."""
