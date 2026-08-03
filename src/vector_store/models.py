"""Vendor-neutral domain values for vector storage and search."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from uuid import UUID

type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]
type PointId = str | int | UUID
type Payload = Mapping[str, JsonValue]


@dataclass(frozen=True, slots=True)
class DenseVector:
    """An ordered dense embedding."""

    values: tuple[float, ...]


@dataclass(frozen=True, slots=True)
class SparseVector:
    """A sparse embedding represented by aligned indices and values."""

    indices: tuple[int, ...]
    values: tuple[float, ...]

    def __post_init__(self) -> None:
        if len(self.indices) != len(self.values):
            raise SparseVectorShapeError(len(self.indices), len(self.values))


@dataclass(frozen=True, slots=True)
class SparseVectorShapeError(ValueError):
    """Raised when sparse indices and values have different lengths."""

    index_count: int
    value_count: int

    def __str__(self) -> str:
        return "sparse_vector_shape_mismatch"


@dataclass(frozen=True, slots=True)
class VectorRecord:
    """One domain record to insert or replace in a collection."""

    point_id: PointId
    dense: DenseVector
    payload: Payload = field(default_factory=lambda: MappingProxyType({}))
    sparse: SparseVector | None = None


@dataclass(frozen=True, slots=True)
class VectorSearchQuery:
    """A bounded dense or hybrid search request."""

    collection_name: str
    dense: DenseVector
    sparse: SparseVector | None = None
    limit: int = 10
    score_threshold: float | None = None

    def __post_init__(self) -> None:
        if not self.collection_name or self.limit < 1:
            raise VectorSearchQueryError


@dataclass(frozen=True, slots=True)
class VectorCollection:
    """A vendor-neutral named-vector collection specification."""

    name: str
    dense_size: int
    sparse: bool = False

    def __post_init__(self) -> None:
        if not self.name or self.dense_size < 1:
            raise VectorCollectionError


class VectorCollectionError(ValueError):
    """Raised when a vector collection specification is invalid."""

    def __init__(self) -> None:
        super().__init__("vector_collection_invalid")


class VectorSearchQueryError(ValueError):
    """Raised when a vector search query has invalid bounds."""

    def __init__(self) -> None:
        super().__init__("vector_search_query_invalid")


@dataclass(frozen=True, slots=True)
class VectorSearchHit:
    """A vendor-neutral scored search result."""

    point_id: PointId
    score: float
    payload: Payload = field(default_factory=lambda: MappingProxyType({}))


@dataclass(frozen=True, slots=True)
class DocumentMetadata:
    """Persisted metadata for one logical document."""

    doc_id: str
    filename: str
    file_hash: str
    chunk_count: int
    chunk_size: int
    chunk_overlap: int


@dataclass(frozen=True, slots=True)
class DocumentReplacement:
    """One complete replacement batch and its maintained index metadata."""

    doc_id: str
    filename: str
    records: tuple[VectorRecord, ...]
    chunk_size: int
    chunk_overlap: int
    created_at: str
