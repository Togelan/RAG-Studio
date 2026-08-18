from __future__ import annotations

from collections.abc import Mapping
from uuid import uuid4

import anyio
import pytest
from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models as qmodels

from src.vector_store.contracts import VectorStoreError
from src.vector_store.models import JsonValue
from src.vector_store.tenant_store import TenantRagStore
from tests.vector_store.test_tenant_rag_store import _replacement, _store


async def _payloads(
    client: AsyncQdrantClient, store: TenantRagStore, doc_id: str
) -> tuple[Mapping[str, JsonValue], ...]:
    points, _ = await client.scroll(
        collection_name=store.resolved.name,
        scroll_filter=qmodels.Filter(
            must=[
                qmodels.FieldCondition(
                    key="record_type", match=qmodels.MatchValue(value="document_chunk")
                ),
                qmodels.FieldCondition(key="doc_id", match=qmodels.MatchValue(value=doc_id)),
            ]
        ),
        limit=100,
        with_payload=True,
        with_vectors=False,
    )
    return tuple(point.payload or {} for point in points)


async def _assert_old_generation(
    client: AsyncQdrantClient, store: TenantRagStore, doc_id: str
) -> None:
    payloads = await _payloads(client, store, doc_id)
    assert len(payloads) == 3
    assert {payload["text"] for payload in payloads} == {"old-0", "old-1", "old-2"}


@pytest.mark.anyio
async def test_failed_tenant_replacement_restores_prior_complete_document(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a complete old generation and a failure after the new upsert lands.
    client = AsyncQdrantClient(location=":memory:")
    store = await _store(client, uuid4())
    old = _replacement("replace.txt", "old", 3)
    new = _replacement("replace.txt", "new", 2)
    await store.replace_document(old)
    original_upsert = client.upsert
    injected = False

    async def failing_upsert(*args: object, **kwargs: object) -> qmodels.UpdateResult:
        nonlocal injected
        result = await original_upsert(*args, **kwargs)
        if not injected:
            injected = True
            raise RuntimeError("injected_after_upsert")
        return result

    monkeypatch.setattr(client, "upsert", failing_upsert)
    try:
        # When: replacement fails after publishing its candidate batch.
        with pytest.raises(VectorStoreError):
            await store.replace_document(new)

        # Then: compensation restores only the old complete tenant generation.
        await _assert_old_generation(client, store, old.doc_id)
    finally:
        await client.close()


@pytest.mark.anyio
async def test_cancelled_tenant_replacement_restores_prior_complete_document(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a complete old generation and a paused new-generation upsert.
    client = AsyncQdrantClient(location=":memory:")
    store = await _store(client, uuid4())
    old = _replacement("cancel.txt", "old", 3)
    new = _replacement("cancel.txt", "new", 2)
    await store.replace_document(old)
    original_upsert = client.upsert
    upserted = anyio.Event()
    release = anyio.Event()
    paused = False

    async def paused_upsert(*args: object, **kwargs: object) -> qmodels.UpdateResult:
        nonlocal paused
        result = await original_upsert(*args, **kwargs)
        if not paused:
            paused = True
            upserted.set()
            await release.wait()
        return result

    monkeypatch.setattr(client, "upsert", paused_upsert)
    try:
        # When: cancellation arrives after the candidate batch is written.
        async with anyio.create_task_group() as task_group:
            task_group.start_soon(store.replace_document, new)
            await upserted.wait()
            task_group.cancel_scope.cancel()

        # Then: shielded compensation restores the old complete tenant generation.
        await _assert_old_generation(client, store, old.doc_id)
    finally:
        await client.close()
