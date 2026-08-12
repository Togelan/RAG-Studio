"""Pure translation between vector-store domain values and Qdrant SDK values."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import MappingProxyType

from pydantic import ValidationError
from qdrant_client.http import models as qmodels
from qdrant_client.http.exceptions import (
    ApiException,
    ResponseHandlingException,
    UnexpectedResponse,
)

from src.vector_store.contracts import VectorStoreError, VectorStoreErrorCode
from src.vector_store.models import SparseVector, VectorRecord, VectorSearchHit

_DENSE_VECTOR_NAME = "dense"
_SPARSE_VECTOR_NAME = "sparse"


@asynccontextmanager
async def translated_errors() -> AsyncIterator[None]:
    """Translate Qdrant boundary failures into stable vector-store errors."""
    try:
        yield
    except ValidationError:
        raise invalid_request_error() from None
    except UnexpectedResponse as error:
        raise response_error(error) from None
    except ApiException, ResponseHandlingException, TimeoutError:
        raise unavailable_error() from None


def to_qdrant_sparse(vector: SparseVector) -> qmodels.SparseVector:
    """Translate a domain sparse vector into the Qdrant representation."""
    return qmodels.SparseVector(
        indices=list(vector.indices),
        values=list(vector.values),
    )


def to_qdrant_point(record: VectorRecord) -> qmodels.PointStruct:
    """Translate one domain vector record into a Qdrant point."""
    vectors: dict[str, qmodels.Vector] = {_DENSE_VECTOR_NAME: list(record.dense.values)}
    if record.sparse is not None:
        vectors[_SPARSE_VECTOR_NAME] = to_qdrant_sparse(record.sparse)
    return qmodels.PointStruct(
        id=record.point_id,
        vector=vectors,
        payload=dict(record.payload),
    )


def to_search_hit(point: qmodels.ScoredPoint) -> VectorSearchHit:
    """Translate one scored Qdrant point into a domain search hit."""
    return VectorSearchHit(
        point_id=point.id,
        score=point.score,
        payload=MappingProxyType(dict(point.payload or {})),
    )


def response_error(error: UnexpectedResponse) -> VectorStoreError:
    """Map a Qdrant response to the stable vector-store error contract."""
    status = error.status_code
    if status is not None and 400 <= status < 500 and status != 429:
        return invalid_request_error()
    return unavailable_error()


def invalid_request_error() -> VectorStoreError:
    """Build the stable non-retryable invalid-request error."""
    return VectorStoreError(VectorStoreErrorCode.INVALID_REQUEST, retryable=False)


def unavailable_error() -> VectorStoreError:
    """Build the stable retryable unavailable error."""
    return VectorStoreError(VectorStoreErrorCode.UNAVAILABLE, retryable=True)
