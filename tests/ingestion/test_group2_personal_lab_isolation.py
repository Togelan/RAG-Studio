from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from types import MappingProxyType
from uuid import uuid4

import httpx
import pytest
from qdrant_client import AsyncQdrantClient
from qdrant_client.http.exceptions import ResponseHandlingException

from src.api.personal_lab_scope import PersonalLabScope
from src.vector_store import pagination
from src.vector_store.contracts import VectorStoreError
from src.vector_store.models import (
    DenseVector,
    DocumentReplacement,
    PersonalVectorScope,
    SparseVector,
    VectorRecord,
)
from src.vector_store.pagination import CursorError
from src.vector_store.personal_store import PersonalRagStore, PersonalVectorSearch
from tests.api.test_group2_personal_lab_ingestion import _build_app


@pytest.mark.asyncio
async def test_overlapping_identical_uploads_publish_exactly_once(tmp_path) -> None:
    # Given: one identity and a delayed publish widen the overlap window.
    user_id = uuid4()
    app, qdrant = _build_app(
        tmp_path, {"a": user_id}, {user_id: uuid4()}, provider_delay=0.05
    )
    headers = {"X-CSRF-Token": "proof", "Origin": "https://testserver"}
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(
            transport=transport, base_url="https://testserver"
        ) as client:
            client.cookies.set("__Host-ragstudio-csrf", "proof")
            client.cookies.set("identity", "a")
            requests = tuple(
                client.post(
                    "/api/personal/knowledge/upload",
                    headers=headers,
                    files={"file": ("race.txt", b"one private source", "text/plain")},
                )
                for _ in range(2)
            )
            # When: both complete through the authenticated Personal boundary.
            responses = await asyncio.gather(*requests)
            listed = await client.get("/api/personal/knowledge/documents")
        # Then: exactly one complete document and opaque raw source are published.
        assert sorted(response.status_code for response in responses) == [201, 409]
        assert len(listed.json()["documents"]) == 1
        assert len(tuple(tmp_path.rglob("*.txt"))) == 1
    finally:
        await qdrant.close()


def _scope(tmp_path, scope_id) -> PersonalLabScope:
    namespace = f"pl_{scope_id.hex}"
    return PersonalLabScope(
        id=scope_id,
        namespace=namespace,
        data_root=tmp_path / namespace,
        collection_name=namespace,
    )


def _replacement(scope_id, text: str, *, revision: int = 1) -> DocumentReplacement:
    doc_id = str(uuid4())
    return DocumentReplacement(
        doc_id=doc_id,
        filename="same.txt",
        records=(
            VectorRecord(
                point_id=str(uuid4()),
                dense=DenseVector((float(revision), 0.0, 0.0)),
                sparse=SparseVector((revision,), (1.0,)),
                payload=MappingProxyType(
                    {
                        "text": text,
                        "source": "same.txt",
                        "chunk_index": 0,
                        "scope_marker": scope_id.hex,
                    }
                ),
            ),
        ),
        chunk_size=512,
        chunk_overlap=64,
        created_at=datetime.now(UTC).isoformat(),
        file_hash=f"hash-{revision}",
    )


async def _assert_isolated_searches(
    first: PersonalRagStore, second: PersonalRagStore
) -> None:
    first_hits = await first.search_documents(
        PersonalVectorSearch(DenseVector((1.0, 0.0, 0.0)), limit=5)
    )
    second_hits = await second.search_documents(
        PersonalVectorSearch(DenseVector((1.0, 0.0, 0.0)), limit=5)
    )
    assert {hit.payload["text"] for hit in first_hits} == {
        "first private text",
        "first extra text",
    }
    assert [hit.payload["text"] for hit in second_hits] == ["second private text"]


@pytest.mark.asyncio
async def test_two_personal_scopes_isolate_documents_search_and_cursors(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given: two Personal Lab stores backed by one real in-memory Qdrant engine.
    client = AsyncQdrantClient(location=":memory:")
    first_scope = _scope(tmp_path, uuid4())
    second_scope = _scope(tmp_path, uuid4())
    first = PersonalRagStore(
        client, PersonalVectorScope(first_scope.id, first_scope.collection_name)
    )
    second = PersonalRagStore(
        client, PersonalVectorScope(second_scope.id, second_scope.collection_name)
    )
    try:
        await first.ensure_ready(dense_size=3)
        await second.ensure_ready(dense_size=3)
        first_doc = _replacement(first_scope.id, "first private text")
        first_extra = replace(
            _replacement(first_scope.id, "first extra text"),
            filename="extra.txt",
        )
        second_doc = _replacement(second_scope.id, "second private text")
        await first.replace_document(first_doc)
        await first.replace_document(first_extra)
        await second.replace_document(second_doc)
        monkeypatch.setattr(pagination, "PAGE_SIZE", 1)

        # When: both identities list and search, then B replays A's cursor.
        first_page = await first.list_documents()
        second_page = await second.list_documents()
        await _assert_isolated_searches(first, second)

        # Then: every observable is collection-bound and no Legacy collection exists.
        assert len(first_page.items) == 1
        assert {item.payload["doc_id"] for item in second_page.items} == {
            second_doc.doc_id
        }
        assert not await client.collection_exists("rag_studio_docs")

        foreign_cursor = first_page.next_cursor
        assert foreign_cursor is not None
        with pytest.raises(CursorError):
            await second.list_documents(foreign_cursor)
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_interrupted_reindex_restores_previous_personal_document(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given: one published Personal document in a real in-memory Qdrant collection.
    client = AsyncQdrantClient(location=":memory:")
    scope = _scope(tmp_path, uuid4())
    store = PersonalRagStore(
        client, PersonalVectorScope(scope.id, scope.collection_name)
    )
    try:
        await store.ensure_ready(dense_size=3)
        previous = _replacement(scope.id, "previous index", revision=1)
        await store.replace_document(previous)
        replacement = replace(
            _replacement(scope.id, "partial index", revision=2),
            doc_id=previous.doc_id,
            filename=previous.filename,
        )
        original_delete = client.delete
        failed = False

        async def fail_publish_delete(*args, **kwargs):
            nonlocal failed
            if not failed:
                failed = True
                raise RuntimeError("private-path-provider-detail")
            return await original_delete(*args, **kwargs)

        monkeypatch.setattr(client, "delete", fail_publish_delete)

        # When: stale-point deletion fails after the new batch was upserted.
        with pytest.raises(VectorStoreError) as captured:
            await store.replace_document(replacement)
        retained = await store.search_documents(
            PersonalVectorSearch(DenseVector((1.0, 0.0, 0.0)), limit=5)
        )

        # Then: compensating rollback leaves only the prior usable index.
        assert "private-path-provider-detail" not in str(captured.value)
        assert [hit.payload["text"] for hit in retained] == ["previous index"]
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_qdrant_outage_is_sanitized_before_leaving_personal_store(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given: a resolved Personal scope whose backend fails with private details.
    client = AsyncQdrantClient(location=":memory:")
    scope = _scope(tmp_path, uuid4())
    store = PersonalRagStore(
        client, PersonalVectorScope(scope.id, scope.collection_name)
    )

    async def fail_readiness(*args, **kwargs):
        del args, kwargs
        raise ResponseHandlingException(TimeoutError("qdrant-url-and-private-path"))

    monkeypatch.setattr(client, "collection_exists", fail_readiness)
    try:
        # When: collection readiness reaches the failing provider boundary.
        with pytest.raises(VectorStoreError) as captured:
            await store.ensure_ready(dense_size=3)

        # Then: only the stable domain error leaves the adapter.
        assert str(captured.value) == "vector_store_unavailable"
        assert "qdrant-url-and-private-path" not in str(captured.value)
    finally:
        await client.close()
