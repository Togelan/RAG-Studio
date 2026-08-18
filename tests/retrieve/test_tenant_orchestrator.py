from __future__ import annotations

import inspect

import pytest

from src.retrieve import orchestrator
from src.vector_store.contracts import VectorStoreError, VectorStoreErrorCode
from src.vector_store.models import VectorSearchHit
from src.vector_store.tenant_store import TenantVectorSearch


class FakeTenantSearcher:
    def __init__(self, hits: tuple[VectorSearchHit, ...]) -> None:
        self.hits = hits
        self.query: TenantVectorSearch | None = None

    async def search_documents(
        self, query: TenantVectorSearch
    ) -> tuple[VectorSearchHit, ...]:
        self.query = query
        return self.hits


class FailingTenantSearcher:
    async def search_documents(
        self, query: TenantVectorSearch
    ) -> tuple[VectorSearchHit, ...]:
        del query
        raise VectorStoreError(VectorStoreErrorCode.UNAVAILABLE, retryable=True)


def test_tenant_retrieval_surface_has_no_collection_selector() -> None:
    # Given: the tenant retrieval entry point.
    tenant_search = getattr(orchestrator, "tenant_hybrid_search", None)

    # When: its application-controlled parameters are inspected.
    assert tenant_search is not None
    parameter_names = set(inspect.signature(tenant_search).parameters)

    # Then: a collection name cannot be supplied by the caller.
    assert "collection_name" not in parameter_names


@pytest.mark.anyio
async def test_tenant_retrieval_preserves_only_bound_citation_metadata() -> None:
    # Given: one bound search result with citation-ready metadata.
    searcher = FakeTenantSearcher(
        (
            VectorSearchHit(
                point_id="point-a",
                score=0.9,
                payload={
                    "text": "tenant-private",
                    "source": "source.txt",
                    "doc_id": "doc-a",
                    "strategy": "recursive",
                    "start_offset": 1,
                    "end_offset": 8,
                },
            ),
        )
    )

    # When: tenant retrieval expands and ranks without a reranker.
    results = await orchestrator.tenant_hybrid_search(
        query="private",
        dense_vector=[1.0] * 384,
        sparse_indices=[1],
        sparse_values=[1.0],
        tenant_searcher=searcher,
        top_k=5,
        use_reranker=False,
    )

    # Then: the citation and text originate only from the bound capability.
    assert searcher.query is not None
    assert [result["text"] for result in results] == ["tenant-private"]
    assert results[0]["metadata"]["source"] == "source.txt"
    assert results[0]["metadata"]["start_offset"] == 1
    assert results[0]["metadata"]["end_offset"] == 8


@pytest.mark.anyio
async def test_tenant_retrieval_failure_is_empty_and_redacted(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Given: a bound storage failure and hostile text absent from typed errors.
    hostile = "ws_secret-collection/provider-detail"

    # When: tenant retrieval maps the failure to its bounded empty outcome.
    results = await orchestrator.tenant_hybrid_search(
        query=hostile,
        dense_vector=[1.0] * 384,
        sparse_indices=[1],
        sparse_values=[1.0],
        tenant_searcher=FailingTenantSearcher(),
        use_reranker=False,
    )

    # Then: neither caller data nor provider identifiers are logged or returned.
    assert results == []
    assert hostile not in caplog.text
