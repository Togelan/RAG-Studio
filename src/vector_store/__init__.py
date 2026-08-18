"""Vendor-neutral vector capabilities with a Qdrant production adapter."""

from src.vector_store.adapter import QdrantVectorStore, get_vector_store
from src.vector_store.contracts import (
    VectorSearcher,
    VectorStore,
    VectorStoreError,
    VectorStoreErrorCode,
    VectorWriter,
)
from src.vector_store.models import (
    DenseVector,
    SparseVector,
    VectorRecord,
    VectorSearchHit,
    VectorSearchQuery,
)
from src.vector_store.tenant_store import (
    TenantCacheScope,
    TenantRagStore,
    TenantVectorSearch,
)

__all__ = [
    "DenseVector",
    "QdrantVectorStore",
    "SparseVector",
    "TenantCacheScope",
    "TenantRagStore",
    "TenantVectorSearch",
    "VectorRecord",
    "VectorSearchHit",
    "VectorSearchQuery",
    "VectorSearcher",
    "VectorStore",
    "VectorStoreError",
    "VectorStoreErrorCode",
    "VectorWriter",
    "get_vector_store",
]
