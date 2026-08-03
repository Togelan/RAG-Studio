"""Vendor-neutral embedding contracts and validated model adapter."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from enum import StrEnum
from threading import Lock
from typing import Protocol, runtime_checkable

from src.vector_store.models import DenseVector, SparseVector, SparseVectorShapeError

DENSE_EMBEDDING_SIZE = 384


class DenseEmbeddingOutput(Protocol):
    """Dense model output convertible to Python floats."""

    def tolist(self) -> list[float]:
        """Return the dense values."""
        ...


class SparseEmbeddingOutput(Protocol):
    """Sparse model output with aligned indices and values."""

    @property
    def indices(self) -> Sequence[int]:
        """Return token indices."""
        ...

    @property
    def values(self) -> Sequence[float]:
        """Return token weights."""
        ...


class DenseEmbeddingModel(Protocol):
    """Raw dense model capability used by the production adapter."""

    def embed(self, texts: Sequence[str]) -> Iterable[DenseEmbeddingOutput]:
        """Generate raw dense outputs."""
        ...


class SparseEmbeddingModel(Protocol):
    """Raw sparse model capability used by the production adapter."""

    def embed(self, texts: Sequence[str]) -> Iterable[SparseEmbeddingOutput]:
        """Generate raw sparse outputs."""
        ...


@runtime_checkable
class Embedder(Protocol):
    """Application-facing dense and sparse embedding capability."""

    def embed_dense(self, texts: Sequence[str]) -> tuple[DenseVector, ...]:
        """Return validated dense embeddings."""
        ...

    def embed_sparse(self, texts: Sequence[str]) -> tuple[SparseVector, ...]:
        """Return validated sparse embeddings."""
        ...


class EmbeddingErrorCode(StrEnum):
    """Stable embedding failure codes safe for application boundaries."""

    INVALID_SHAPE = "embedding_invalid_shape"
    MODEL_FAILURE = "embedding_model_failure"


class EmbeddingError(RuntimeError):
    """A sanitized typed failure from an embedding model boundary."""

    def __init__(self, code: EmbeddingErrorCode, *, retryable: bool) -> None:
        super().__init__(code.value)
        self.code = code
        self.retryable = retryable


class FastEmbedder:
    """Lock-protected lazy adapter for FastEmbed-compatible model factories."""

    def __init__(
        self,
        dense_factory: Callable[[], DenseEmbeddingModel],
        sparse_factory: Callable[[], SparseEmbeddingModel],
    ) -> None:
        self._dense_factory = dense_factory
        self._sparse_factory = sparse_factory
        self._dense_model: DenseEmbeddingModel | None = None
        self._sparse_model: SparseEmbeddingModel | None = None
        self._dense_lock = Lock()
        self._sparse_lock = Lock()

    def embed_dense(self, texts: Sequence[str]) -> tuple[DenseVector, ...]:
        """Return one validated 384-dimensional vector per text."""
        try:
            outputs = tuple(self._dense().embed(texts))
        except (OSError, RuntimeError) as error:
            raise EmbeddingError(
                EmbeddingErrorCode.MODEL_FAILURE,
                retryable=True,
            ) from error
        if len(outputs) != len(texts):
            raise EmbeddingError(
                EmbeddingErrorCode.INVALID_SHAPE,
                retryable=False,
            )
        try:
            vectors = tuple(
                DenseVector(tuple(float(value) for value in output.tolist()))
                for output in outputs
            )
        except (TypeError, ValueError) as error:
            raise EmbeddingError(
                EmbeddingErrorCode.INVALID_SHAPE,
                retryable=False,
            ) from error
        if any(len(vector.values) != DENSE_EMBEDDING_SIZE for vector in vectors):
            raise EmbeddingError(
                EmbeddingErrorCode.INVALID_SHAPE,
                retryable=False,
            )
        return vectors

    def embed_sparse(self, texts: Sequence[str]) -> tuple[SparseVector, ...]:
        """Return one validated sparse vector per text."""
        try:
            outputs = tuple(self._sparse().embed(texts))
        except (OSError, RuntimeError) as error:
            raise EmbeddingError(
                EmbeddingErrorCode.MODEL_FAILURE,
                retryable=True,
            ) from error
        if len(outputs) != len(texts):
            raise EmbeddingError(
                EmbeddingErrorCode.INVALID_SHAPE,
                retryable=False,
            )
        try:
            return tuple(
                SparseVector(
                    tuple(int(index) for index in output.indices),
                    tuple(float(value) for value in output.values),
                )
                for output in outputs
            )
        except (AttributeError, TypeError, ValueError, SparseVectorShapeError) as error:
            raise EmbeddingError(
                EmbeddingErrorCode.INVALID_SHAPE,
                retryable=False,
            ) from error

    def _dense(self) -> DenseEmbeddingModel:
        with self._dense_lock:
            if self._dense_model is None:
                try:
                    model = self._dense_factory()
                except (OSError, RuntimeError) as error:
                    raise EmbeddingError(
                        EmbeddingErrorCode.MODEL_FAILURE,
                        retryable=True,
                    ) from error
                self._dense_model = model
            return self._dense_model

    def _sparse(self) -> SparseEmbeddingModel:
        with self._sparse_lock:
            if self._sparse_model is None:
                try:
                    model = self._sparse_factory()
                except (OSError, RuntimeError) as error:
                    raise EmbeddingError(
                        EmbeddingErrorCode.MODEL_FAILURE,
                        retryable=True,
                    ) from error
                self._sparse_model = model
            return self._sparse_model
