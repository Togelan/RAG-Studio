from __future__ import annotations

import pytest

from src.vector_store.document_index import (
    DOCUMENT_INDEX_COLLECTION,
    clear_document_index,
    delete_index_document,
    index_document,
)
from tests.api.test_pagination_api import FakePoint, FakeQdrant, _client


def test_legacy_backfill_finds_documents_after_one_thousand_chunks() -> None:
    # Given
    points = [
        FakePoint(
            id=f"point-{index:04d}",
            payload={
                "doc_id": "doc-z",
                "source": "z.txt",
                "total_chunks": 1_001,
                "chunk_index": index,
            },
        )
        for index in range(1_001)
    ]
    points.extend(
        [
            FakePoint("point-1001", {"doc_id": "doc-a", "source": "a.txt"}),
            FakePoint("point-1002", {"doc_id": "doc-m", "source": "m.txt"}),
        ]
    )
    fake = FakeQdrant(points)

    # When
    with _client(fake) as client:
        first = client.get("/api/ingest/documents")
        second = client.get(
            "/api/ingest/documents", params={"cursor": first.json()["next_cursor"]}
        )
        third = client.get(
            "/api/ingest/documents", params={"cursor": second.json()["next_cursor"]}
        )

    # Then
    assert first.json()["documents"] == second.json()["documents"] == []
    assert first.json()["truncated"] is second.json()["truncated"] is True
    assert [item["filename"] for item in third.json()["documents"]] == [
        "a.txt",
        "m.txt",
        "z.txt",
    ]


@pytest.mark.anyio
async def test_document_index_lifecycle_is_maintained() -> None:
    # Given
    fake = FakeQdrant([])

    # When / Then
    await index_document(fake, "doc-a", "a.txt", 2, 512, 64, "created")
    records = fake.collections[DOCUMENT_INDEX_COLLECTION]
    assert [point.payload["doc_id"] for point in records] == ["doc-a"]

    await delete_index_document(fake, "doc-a")
    assert fake.collections[DOCUMENT_INDEX_COLLECTION] == []

    await index_document(fake, "doc-a", "a.txt", 2, 512, 64, "created")
    await clear_document_index(fake)
    assert DOCUMENT_INDEX_COLLECTION not in fake.collections
