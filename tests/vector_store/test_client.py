"""Contract tests for the application-facing vector-store adapter."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import anyio
import pytest
from qdrant_client.http import models as qmodels
from qdrant_client.http.exceptions import ResponseHandlingException

from src.vector_store.adapter import QdrantVectorStore, get_vector_store
from src.vector_store.client import get_qdrant_client
from src.vector_store.contracts import VectorStoreError, VectorStoreErrorCode
from src.vector_store.models import (
    DenseVector,
    SparseVector,
    VectorRecord,
    VectorSearchQuery,
)

if TYPE_CHECKING:
    from collections.abc import Sequence


@dataclass(slots=True)
class FakeQdrantClient:
    """Deterministic SDK-level fake that records adapter translations."""

    query_response: qmodels.QueryResponse = field(
        default_factory=lambda: qmodels.QueryResponse(points=[])
    )
    query_error: BaseException | None = None
    upsert_error: BaseException | None = None
    query_calls: list[dict[str, object]] = field(default_factory=list)
    upsert_calls: list[dict[str, object]] = field(default_factory=list)

    async def query_points(self, **kwargs: object) -> qmodels.QueryResponse:
        """Record one query or raise the configured deterministic failure."""
        self.query_calls.append(dict(kwargs))
        if self.query_error is not None:
            raise self.query_error
        return self.query_response

    async def upsert(self, **kwargs: object) -> qmodels.UpdateResult:
        """Record one upsert or raise the configured deterministic failure."""
        self.upsert_calls.append(dict(kwargs))
        if self.upsert_error is not None:
            raise self.upsert_error
        return qmodels.UpdateResult(
            operation_id=1, status=qmodels.UpdateStatus.COMPLETED
        )


@pytest.mark.asyncio
async def test_search_translates_domain_query_and_result() -> None:
    """Given domain DTOs, when searched, then only the adapter uses SDK models."""
    fake = FakeQdrantClient(
        query_response=qmodels.QueryResponse(
            points=[
                qmodels.ScoredPoint(
                    id=7,
                    version=1,
                    score=0.75,
                    payload={"text": "safe result"},
                )
            ]
        )
    )
    store = QdrantVectorStore(fake)

    results = await store.search(
        VectorSearchQuery(
            collection_name="documents",
            dense=DenseVector((0.1, 0.2)),
            sparse=SparseVector(indices=(3, 9), values=(0.4, 0.6)),
            limit=4,
        )
    )

    call = fake.query_calls[0]
    assert call["collection_name"] == "documents"
    assert call["limit"] == 4
    assert isinstance(call["query"], qmodels.FusionQuery)
    assert all(isinstance(item, qmodels.Prefetch) for item in call["prefetch"])
    assert results[0].point_id == 7
    assert results[0].payload["text"] == "safe result"


@pytest.mark.asyncio
async def test_upsert_translates_all_records_before_mutation() -> None:
    """Given records, when upserted, then one translated batch is committed."""
    fake = FakeQdrantClient()
    store = QdrantVectorStore(fake)
    records: Sequence[VectorRecord] = (
        VectorRecord(
            point_id=1,
            dense=DenseVector((0.2, 0.8)),
            sparse=SparseVector(indices=(2,), values=(1.0,)),
            payload={"text": "first"},
        ),
        VectorRecord(
            point_id=2,
            dense=DenseVector((0.3, 0.7)),
            payload={"text": "second"},
        ),
    )

    await store.upsert("documents", records)

    call = fake.upsert_calls[0]
    points = call["points"]
    assert isinstance(points, list)
    assert [point.id for point in points] == [1, 2]
    assert points[0].vector["sparse"].indices == [2]
    assert points[1].vector == {"dense": [0.3, 0.7]}


@pytest.mark.asyncio
async def test_factory_uses_injected_raw_client_factory() -> None:
    """Given an injected factory, when resolved, then its client backs the adapter."""
    fake = FakeQdrantClient()
    factory_calls = 0

    async def client_factory() -> FakeQdrantClient:
        nonlocal factory_calls
        factory_calls += 1
        return fake

    store = await get_vector_store(client_factory)
    await store.search(VectorSearchQuery("documents", DenseVector((1.0,)), limit=1))

    assert factory_calls == 1
    assert len(fake.query_calls) == 1


@pytest.mark.asyncio
async def test_qdrant_failure_is_sanitized_and_typed() -> None:
    """Given a transport failure, when searched, then secrets are not exposed."""
    fake = FakeQdrantClient(
        query_error=ResponseHandlingException(TimeoutError("token=super-secret"))
    )
    store = QdrantVectorStore(fake)

    with pytest.raises(VectorStoreError) as caught:
        await store.search(VectorSearchQuery("documents", DenseVector((1.0,)), limit=1))

    assert caught.value.code is VectorStoreErrorCode.UNAVAILABLE
    assert caught.value.retryable is True
    assert str(caught.value) == "vector_store_unavailable"
    assert "secret" not in str(caught.value)


@pytest.mark.asyncio
async def test_invalid_point_is_rejected_before_qdrant_mutation() -> None:
    """Given an invalid SDK point ID, when stored, then no Qdrant call occurs."""
    fake = FakeQdrantClient()
    store = QdrantVectorStore(fake)

    with pytest.raises(VectorStoreError) as caught:
        await store.upsert(
            "documents",
            (
                VectorRecord(
                    point_id=1.5,
                    dense=DenseVector((1.0,)),
                    payload={"token": "super-secret"},
                ),
            ),
        )

    assert caught.value.code is VectorStoreErrorCode.INVALID_REQUEST
    assert str(caught.value) == "vector_store_invalid_request"
    assert fake.upsert_calls == []


@pytest.mark.asyncio
async def test_cancellation_propagates_without_error_mapping() -> None:
    """Given cancellation, when Qdrant is awaiting, then cancellation escapes once."""
    started = anyio.Event()

    @dataclass(slots=True)
    class BlockingFake(FakeQdrantClient):
        cancellations: int = 0

        async def query_points(self, **kwargs: object) -> qmodels.QueryResponse:
            started.set()
            try:
                await anyio.sleep_forever()
            finally:
                self.cancellations += 1

    fake = BlockingFake()
    store = QdrantVectorStore(fake)

    async with anyio.create_task_group() as task_group:
        task_group.start_soon(
            store.search,
            VectorSearchQuery("documents", DenseVector((1.0,)), limit=1),
        )
        await started.wait()
        task_group.cancel_scope.cancel()

    assert fake.cancellations == 1


@pytest.mark.asyncio
async def test_ten_concurrent_queries_keep_request_state_isolated() -> None:
    """Given ten calls, when concurrent, then each translation retains its vector."""
    fake = FakeQdrantClient()
    store = QdrantVectorStore(fake)

    async with anyio.create_task_group() as task_group:
        for index in range(10):
            task_group.start_soon(
                store.search,
                VectorSearchQuery(
                    "documents",
                    DenseVector((float(index),)),
                    limit=1,
                ),
            )

    translated = sorted(call["query"][0] for call in fake.query_calls)
    assert translated == [float(index) for index in range(10)]


@pytest.mark.asyncio
async def test_raw_client_dependency_remains_compatible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Given the legacy dependency, when resolved, then it returns the raw client."""
    sentinel = FakeQdrantClient()

    async def fake_get_client() -> FakeQdrantClient:
        return sentinel

    monkeypatch.setattr(
        "src.vector_store.client._qdrant_manager.get_client", fake_get_client
    )

    assert await get_qdrant_client() is sentinel
