"""Concurrency tests for lazily initialized local ML models."""

from __future__ import annotations

import sys
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from types import ModuleType
from typing import Any
from unittest.mock import patch

from src.ingestion import embedder
from src.retrieve import orchestrator


def _concurrently_call(factory: Any, workers: int = 8) -> list[Any]:
    """Call a synchronous model factory from several threads at once."""
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(lambda _: factory(), range(workers)))


def test_dense_model_is_loaded_once_for_concurrent_first_requests() -> None:
    """Concurrent first users share one dense model instance."""
    calls = 0
    calls_lock = Lock()

    class FakeTextEmbedding:
        def __init__(self, **_: Any) -> None:
            nonlocal calls
            with calls_lock:
                calls += 1
            time.sleep(0.02)

    fake_fastembed = ModuleType("fastembed")
    fake_fastembed.TextEmbedding = FakeTextEmbedding  # type: ignore[attr-defined]
    original_model = embedder._dense_model  # pyright: ignore[reportPrivateUsage]
    try:
        with embedder._dense_model_lock:  # pyright: ignore[reportPrivateUsage]
            embedder._dense_model = None  # pyright: ignore[reportPrivateUsage]
        with patch.dict(sys.modules, {"fastembed": fake_fastembed}):
            models = _concurrently_call(embedder._get_dense_model)  # pyright: ignore[reportPrivateUsage]
        assert calls == 1
        assert all(model is models[0] for model in models)
    finally:
        with embedder._dense_model_lock:  # pyright: ignore[reportPrivateUsage]
            embedder._dense_model = original_model  # pyright: ignore[reportPrivateUsage]


def test_sparse_model_is_loaded_once_for_concurrent_first_requests() -> None:
    """Concurrent first users share one sparse model instance."""
    calls = 0
    calls_lock = Lock()

    class FakeSparseTextEmbedding:
        def __init__(self, **_: Any) -> None:
            nonlocal calls
            with calls_lock:
                calls += 1
            time.sleep(0.02)

    fake_fastembed = ModuleType("fastembed")
    fake_fastembed.SparseTextEmbedding = FakeSparseTextEmbedding  # type: ignore[attr-defined]
    original_model = embedder._sparse_model  # pyright: ignore[reportPrivateUsage]
    try:
        with embedder._sparse_model_lock:  # pyright: ignore[reportPrivateUsage]
            embedder._sparse_model = None  # pyright: ignore[reportPrivateUsage]
        with patch.dict(sys.modules, {"fastembed": fake_fastembed}):
            models = _concurrently_call(embedder._get_sparse_model)  # pyright: ignore[reportPrivateUsage]
        assert calls == 1
        assert all(model is models[0] for model in models)
    finally:
        with embedder._sparse_model_lock:  # pyright: ignore[reportPrivateUsage]
            embedder._sparse_model = original_model  # pyright: ignore[reportPrivateUsage]


def test_reranker_is_loaded_once_for_concurrent_first_requests() -> None:
    """Concurrent first users share one reranker instance."""
    calls = 0
    calls_lock = Lock()

    class FakeRanker:
        def __init__(self, **_: Any) -> None:
            nonlocal calls
            with calls_lock:
                calls += 1
            time.sleep(0.02)

    fake_flashrank = ModuleType("flashrank")
    fake_flashrank.Ranker = FakeRanker  # type: ignore[attr-defined]
    try:
        orchestrator.reset_reranker()
        with patch.dict(sys.modules, {"flashrank": fake_flashrank}):
            rerankers = _concurrently_call(orchestrator._get_reranker)  # pyright: ignore[reportPrivateUsage]
        assert calls == 1
        assert all(reranker is rerankers[0] for reranker in rerankers)
    finally:
        orchestrator.reset_reranker()
