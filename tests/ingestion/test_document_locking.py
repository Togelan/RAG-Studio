"""Concurrency coverage for same-document vector replacement."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.mark.asyncio
async def test_same_document_ingestions_are_serialized(monkeypatch: pytest.MonkeyPatch) -> None:
    """Upload and re-ingest jobs for one filename never overlap their writes."""
    from src.ingestion import router

    active = 0
    max_active = 0
    completed: list[str] = []

    async def fake_ingest_locked(*, file_id: str, **_: object) -> None:
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0.01)
        completed.append(file_id)
        active -= 1

    monkeypatch.setattr(router, "_ingest_file_locked", fake_ingest_locked)

    await asyncio.gather(
        router._ingest_file("upload", "unused-a", "same.txt", None, AsyncMock()),
        router._ingest_file("reingest", "unused-b", "same.txt", None, AsyncMock()),
    )

    assert max_active == 1
    assert sorted(completed) == ["reingest", "upload"]
    assert router._document_locks == {}


@pytest.mark.asyncio
async def test_different_documents_do_not_share_a_lock() -> None:
    """Per-document locking retains concurrency for independent documents."""
    from src.ingestion import router

    both_entered = asyncio.Event()
    release = asyncio.Event()
    entered = 0

    async def operation(doc_id: str) -> None:
        nonlocal entered
        async with router.document_operation_lock(doc_id):
            entered += 1
            if entered == 2:
                both_entered.set()
            await release.wait()

    first = asyncio.create_task(operation("doc-a"))
    second = asyncio.create_task(operation("doc-b"))
    await asyncio.wait_for(both_entered.wait(), timeout=1)
    release.set()
    await asyncio.gather(first, second)

    assert router._document_locks == {}


@pytest.mark.asyncio
async def test_qdrant_delete_waits_before_replacement_upsert() -> None:
    """A replacement waits for delete completion before issuing its upsert."""
    from qdrant_client.http import models as qmodels

    from src.ingestion.embedder import upsert_chunks

    client = AsyncMock()
    client.count = AsyncMock(return_value=MagicMock(count=3))

    operations: list[str] = []

    async def delete(**_: object) -> None:
        operations.append("delete")

    async def upsert(**_: object) -> None:
        operations.append("upsert")

    client.delete = AsyncMock(side_effect=delete)
    client.upsert = AsyncMock(side_effect=upsert)

    inserted = await upsert_chunks(
        client=client,
        filename="same.txt",
        doc_id="doc-id",
        chunks=["replacement content"],
        dense_vectors=[[0.0] * 384],
        sparse_vectors=[qmodels.SparseVector(indices=[1], values=[1.0])],
    )

    assert inserted == 1
    assert operations == ["delete", "upsert"]
    assert client.delete.await_args.kwargs["wait"] is True
    assert client.upsert.await_args.kwargs["wait"] is True
