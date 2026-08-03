from __future__ import annotations

from collections.abc import Sequence
from concurrent.futures import CancelledError, ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from threading import Barrier, Event, Lock
from unittest.mock import patch

import pytest

from src.ingestion.embedder import (
    generate_dense_embeddings,
    generate_sparse_embeddings,
)
from src.ingestion.embedding import (
    Embedder,
    EmbeddingError,
    EmbeddingErrorCode,
    FastEmbedder,
)
from src.vector_store.models import DenseVector, SparseVector


@dataclass(frozen=True, slots=True)
class _DenseArray:
    values: list[float]

    def tolist(self) -> list[float]:
        return self.values


@dataclass(frozen=True, slots=True)
class _SparseArray:
    indices: tuple[int, ...]
    values: tuple[float, ...]


class _PinnedDenseModel:
    def embed(self, texts: Sequence[str]) -> list[_DenseArray]:
        return [
            _DenseArray([float(index), *([1.0] * 383)]) for index, _ in enumerate(texts)
        ]


class _PinnedSparseModel:
    def embed(self, texts: Sequence[str]) -> list[_SparseArray]:
        return [_SparseArray((index,), (1.0,)) for index, _ in enumerate(texts)]


@dataclass(frozen=True, slots=True)
class _FakeEmbedder:
    dense: tuple[DenseVector, ...]
    sparse: tuple[SparseVector, ...]

    def __bool__(self) -> bool:
        return False

    def embed_dense(self, texts: Sequence[str]) -> tuple[DenseVector, ...]:
        return self.dense[: len(texts)]

    def embed_sparse(self, texts: Sequence[str]) -> tuple[SparseVector, ...]:
        return self.sparse[: len(texts)]


class _DenseModel:
    def embed(self, texts: Sequence[str]) -> list[_DenseArray]:
        return [_DenseArray([1.0] * 384) for _ in texts]


class _SparseModel:
    def embed(self, texts: Sequence[str]) -> list[_SparseArray]:
        return [_SparseArray((1, 3), (0.25, 0.75)) for _ in texts]


def test_compatibility_wrappers_preserve_current_output_shapes() -> None:
    # Given
    chunks = ["alpha", "beta"]

    # When
    with (
        patch("src.ingestion.embedder._default_embedder", None),
        patch(
            "src.ingestion.embedder._get_dense_model", return_value=_PinnedDenseModel()
        ),
        patch(
            "src.ingestion.embedder._get_sparse_model",
            return_value=_PinnedSparseModel(),
        ),
    ):
        dense = generate_dense_embeddings(chunks)
        sparse = generate_sparse_embeddings(chunks)

    # Then
    assert len(dense) == 2
    assert dense[0][:2] == [0.0, 1.0]
    assert dense[1][:2] == [1.0, 1.0]
    assert all(len(vector) == 384 for vector in dense)
    assert [item.indices for item in sparse] == [[0], [1]]
    assert [item.values for item in sparse] == [[1.0], [1.0]]


def test_fake_embedder_is_injectable_through_compatibility_wrappers() -> None:
    # Given
    fake = _FakeEmbedder(
        dense=(DenseVector((1.0,) * 384),),
        sparse=(SparseVector((7,), (0.5,)),),
    )

    # When
    with (
        patch(
            "src.ingestion.embedder._get_dense_model",
            side_effect=AssertionError("dense fallback used"),
        ),
        patch(
            "src.ingestion.embedder._get_sparse_model",
            side_effect=AssertionError("sparse fallback used"),
        ),
    ):
        dense = generate_dense_embeddings(["input only"], embedder=fake)
        sparse = generate_sparse_embeddings(["input only"], embedder=fake)

    # Then
    assert isinstance(fake, Embedder)
    assert dense == [[1.0] * 384]
    assert sparse[0].indices == [7]
    assert sparse[0].values == [0.5]


def test_fastembedder_initializes_dense_model_once_for_ten_concurrent_calls() -> None:
    # Given
    calls = 0
    calls_lock = Lock()
    workers_ready = Barrier(11)
    release_initialization = Event()

    def dense_factory() -> _DenseModel:
        nonlocal calls
        with calls_lock:
            calls += 1
        assert release_initialization.wait(timeout=2)
        return _DenseModel()

    def embed_once(_: int) -> tuple[DenseVector, ...]:
        workers_ready.wait(timeout=2)
        return adapter.embed_dense(["text"])

    adapter = FastEmbedder(
        dense_factory=dense_factory,
        sparse_factory=_SparseModel,
    )

    # When
    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = [pool.submit(embed_once, index) for index in range(10)]
        workers_ready.wait(timeout=2)
        release_initialization.set()
        results = [future.result(timeout=2) for future in futures]

    # Then
    assert calls == 1
    assert len(results) == 10
    assert all(len(result[0].values) == 384 for result in results)


def test_fastembedder_rejects_malformed_dense_shape_with_safe_typed_error() -> None:
    # Given
    class MalformedDenseModel:
        def embed(self, texts: Sequence[str]) -> list[_DenseArray]:
            return [_DenseArray([1.0, 2.0]) for _ in texts]

    adapter = FastEmbedder(
        dense_factory=MalformedDenseModel,
        sparse_factory=_SparseModel,
    )

    # When
    with pytest.raises(EmbeddingError) as caught:
        adapter.embed_dense(["sensitive-input"])

    # Then
    assert caught.value.code is EmbeddingErrorCode.INVALID_SHAPE
    assert str(caught.value) == "embedding_invalid_shape"
    assert "sensitive-input" not in str(caught.value)


def test_fastembedder_rejects_malformed_sparse_shape_before_mutation() -> None:
    # Given
    class MalformedSparseModel:
        def embed(self, texts: Sequence[str]) -> list[_SparseArray]:
            return [_SparseArray((1, 2), (0.5,)) for _ in texts]

    mutation_calls = 0
    adapter = FastEmbedder(
        dense_factory=_DenseModel,
        sparse_factory=MalformedSparseModel,
    )

    # When
    with pytest.raises(EmbeddingError) as caught:
        adapter.embed_sparse(["text"])

    # Then
    assert caught.value.code is EmbeddingErrorCode.INVALID_SHAPE
    assert mutation_calls == 0


def test_fastembedder_maps_model_failure_without_leaking_raw_error() -> None:
    # Given
    class FailingDenseModel:
        def embed(self, texts: Sequence[str]) -> list[_DenseArray]:
            raise RuntimeError("provider-secret=do-not-leak")

    adapter = FastEmbedder(
        dense_factory=FailingDenseModel,
        sparse_factory=_SparseModel,
    )

    # When
    with pytest.raises(EmbeddingError) as caught:
        adapter.embed_dense(["text"])

    # Then
    assert caught.value.code is EmbeddingErrorCode.MODEL_FAILURE
    assert caught.value.retryable is True
    assert str(caught.value) == "embedding_model_failure"
    assert "provider-secret" not in str(caught.value)


@pytest.mark.parametrize("_attempt", range(3))
def test_fastembedder_propagates_repeated_cancellation(_attempt: int) -> None:
    # Given
    class CancelledDenseModel:
        def embed(self, texts: Sequence[str]) -> list[_DenseArray]:
            raise CancelledError

    adapter = FastEmbedder(
        dense_factory=CancelledDenseModel,
        sparse_factory=_SparseModel,
    )

    # When / Then
    with pytest.raises(CancelledError):
        adapter.embed_dense(["text"])


def test_failed_initialization_does_not_poison_adapter_cache() -> None:
    # Given
    attempts = 0

    def dense_factory() -> _DenseModel:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("temporary-secret")
        return _DenseModel()

    adapter = FastEmbedder(
        dense_factory=dense_factory,
        sparse_factory=_SparseModel,
    )

    # When
    with pytest.raises(EmbeddingError):
        adapter.embed_dense(["first"])
    result = adapter.embed_dense(["second"])

    # Then
    assert attempts == 2
    assert len(result[0].values) == 384


def test_consumers_do_not_import_fastembed_directly() -> None:
    # Given
    consumer_sources = [
        path
        for path in Path("src").rglob("*.py")
        if path != Path("src/ingestion/embedder.py")
    ]

    # When
    direct_imports = [
        path
        for path in consumer_sources
        if "import fastembed" in path.read_text(encoding="utf-8")
        or "from fastembed" in path.read_text(encoding="utf-8")
    ]

    # Then
    assert direct_imports == []
