from __future__ import annotations

import inspect
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import pytest
from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models as qmodels

from src.api.saas_sessions import WorkspaceRole
from src.api.saas_tenant_context import TrustedWorkspaceContext
from src.ingestion.embedder import make_document_doc_id
from src.vector_store import (
    DenseVector,
    TenantCacheScope,
    TenantRagStore,
    TenantVectorSearch,
    VectorRecord,
)
from src.vector_store.contracts import VectorStoreError
from src.vector_store.models import DocumentReplacement
from src.vector_store.pagination import CursorError
from src.vector_store.tenant_store import (
    TenantCacheScopeError,
    TenantVectorSearchError,
    semantic_cache_point_id,
)
from src.vector_store.workspace_collections import (
    ResolvedWorkspaceCollection,
    derive_workspace_collection_name,
)


def _dense(value: float) -> DenseVector:
    return DenseVector((value,) * 384)


async def _store(client: AsyncQdrantClient, workspace_id: UUID) -> TenantRagStore:
    name = derive_workspace_collection_name(workspace_id)
    await client.create_collection(
        collection_name=name,
        vectors_config={
            "dense": qmodels.VectorParams(size=384, distance=qmodels.Distance.COSINE)
        },
        sparse_vectors_config={
            "sparse": qmodels.SparseVectorParams(
                index=qmodels.SparseIndexParams(on_disk=False)
            )
        },
    )
    context = TrustedWorkspaceContext(uuid4(), workspace_id, WorkspaceRole.OWNER)
    return TenantRagStore(ResolvedWorkspaceCollection(context, client, name))


def _replacement(filename: str, text: str, count: int = 1) -> DocumentReplacement:
    doc_id = make_document_doc_id(filename)
    records = tuple(
        VectorRecord(
            point_id=str(uuid5(NAMESPACE_URL, f"{doc_id}:{text}:{index}")),
            dense=_dense(1.0),
            payload={
                "doc_id": doc_id,
                "source": filename,
                "text": f"{text}-{index}",
                "chunk_index": index,
                "total_chunks": count,
                "strategy": "recursive",
                "start_offset": index * 10,
                "end_offset": index * 10 + 9,
            },
        )
        for index in range(count)
    )
    return DocumentReplacement(
        doc_id=doc_id,
        filename=filename,
        records=records,
        chunk_size=512,
        chunk_overlap=64,
        created_at="2026-08-17T00:00:00Z",
    )


def _cache_scope(character: str) -> TenantCacheScope:
    return TenantCacheScope(f"cfg_{character * 64}")


def test_tenant_rag_surface_has_no_collection_selector() -> None:
    # Given: the bound tenant vector-store contract.
    parameters = inspect.signature(TenantRagStore.search_documents).parameters

    # When: application-controlled search arguments are inspected.
    argument_names = set(parameters)

    # Then: no caller-controlled collection selector exists.
    assert "collection_name" not in argument_names


def test_tenant_query_and_cache_scope_reject_invalid_bounds() -> None:
    # Given: invalid internal values at the tenant adapter boundary.
    # When/Then: both values fail before any Qdrant operation.
    with pytest.raises(TenantVectorSearchError):
        TenantVectorSearch(dense=_dense(1.0), limit=0)
    with pytest.raises(TenantCacheScopeError):
        TenantCacheScope("shared")


@pytest.mark.anyio
async def test_identical_document_lifecycle_and_citations_are_workspace_isolated() -> None:
    # Given: two workspaces ingest the same filename with distinct text.
    client = AsyncQdrantClient(location=":memory:")
    first = await _store(client, uuid4())
    second = await _store(client, uuid4())
    first_doc = _replacement("shared.txt", "first-private")
    second_doc = _replacement("shared.txt", "second-private")
    try:
        await first.replace_document(first_doc)
        await second.replace_document(second_doc)

        # When: both search, then only the first deletes and the second clears.
        first_hits = await first.search_documents(TenantVectorSearch(_dense(1.0)))
        second_hits = await second.search_documents(TenantVectorSearch(_dense(1.0)))
        await first.delete_document(first_doc.doc_id)
        first_after_delete = await first.search_documents(TenantVectorSearch(_dense(1.0)))
        second_after_delete = await second.search_documents(TenantVectorSearch(_dense(1.0)))
        await second.clear_documents()

        # Then: text, citations, deletion, and clear remain tenant-local.
        assert [hit.payload["text"] for hit in first_hits] == ["first-private-0"]
        assert [hit.payload["text"] for hit in second_hits] == ["second-private-0"]
        assert first_hits[0].payload["source"] == "shared.txt"
        assert second_hits[0].payload["source"] == "shared.txt"
        assert not first_after_delete
        assert [hit.payload["text"] for hit in second_after_delete] == ["second-private-0"]
        assert not await second.search_documents(TenantVectorSearch(_dense(1.0)))
    finally:
        await client.close()


@pytest.mark.anyio
async def test_cache_key_filter_and_invalidation_block_cross_tenant_poisoning() -> None:
    # Given: matching questions in two workspaces and two chatbot configurations.
    client = AsyncQdrantClient(location=":memory:")
    first_workspace = uuid4()
    second_workspace = uuid4()
    first = await _store(client, first_workspace)
    second = await _store(client, second_workspace)
    active = _cache_scope("a")
    changed = _cache_scope("b")
    query = "same question"
    try:
        await first.save_cache(active, query, "first answer", _dense(1.0))
        await second.save_cache(active, query, "second answer", _dense(1.0))

        # When: lookup varies workspace/config and a document replacement invalidates.
        first_hit = await first.lookup_cache(active, _dense(1.0))
        second_hit = await second.lookup_cache(active, _dense(1.0))
        wrong_config = await first.lookup_cache(changed, _dense(1.0))
        first_id = semantic_cache_point_id(first_workspace, active, query)
        second_id = semantic_cache_point_id(second_workspace, active, query)
        changed_id = semantic_cache_point_id(first_workspace, changed, query)
        await first.replace_document(_replacement("changed.txt", "new"))

        # Then: cache answers/IDs never cross scope and mutations clear stale answers.
        assert first_hit is not None and first_hit.answer == "first answer"
        assert second_hit is not None and second_hit.answer == "second answer"
        assert wrong_config is None
        assert len({first_id, second_id, changed_id}) == 3
        assert str(first_workspace) not in first_id
        assert query not in first_id
        assert await first.lookup_cache(active, _dense(1.0)) is None
        second_after = await second.lookup_cache(active, _dense(1.0))
        assert second_after is not None and second_after.answer == "second answer"
    finally:
        await client.close()


@pytest.mark.anyio
async def test_listing_cursor_cannot_be_replayed_in_another_workspace() -> None:
    # Given: identical document IDs with enough chunks for a signed continuation.
    client = AsyncQdrantClient(location=":memory:")
    first = await _store(client, uuid4())
    second = await _store(client, uuid4())
    first_doc = _replacement("same.txt", "first", 101)
    second_doc = _replacement("same.txt", "second", 1)
    try:
        await first.replace_document(first_doc)
        await second.replace_document(second_doc)
        first_page = await first.list_chunks(first_doc.doc_id)
        assert first_page.next_cursor is not None

        # When/Then: replaying the first cursor against the second scope is rejected.
        with pytest.raises(CursorError):
            await second.list_chunks(second_doc.doc_id, first_page.next_cursor)
        second_page = await second.list_chunks(second_doc.doc_id)
        assert second_page.matched_items == 1
    finally:
        await client.close()


@pytest.mark.anyio
async def test_absent_tenant_collection_is_sanitized_and_not_ready() -> None:
    # Given: an authorized capability whose provisioned collection disappears.
    client = AsyncQdrantClient(location=":memory:")
    workspace_id = uuid4()
    store = await _store(client, workspace_id)
    name = derive_workspace_collection_name(workspace_id)
    await client.delete_collection(name)
    try:
        # When: readiness and search observe the missing backend collection.
        ready = await store.is_ready()
        with pytest.raises(VectorStoreError) as captured:
            await store.search_documents(TenantVectorSearch(_dense(1.0)))

        # Then: failure is bounded and provider identifiers remain hidden.
        assert ready is False
        assert name not in str(captured.value)
        assert str(workspace_id) not in str(captured.value)
    finally:
        await client.close()
