from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from src.api.dependencies import get_qdrant_client
from src.api.main import create_app


@dataclass(slots=True)
class FakePoint:
    id: str
    payload: dict[str, object]


class FakeQdrant:
    def __init__(self, points: list[FakePoint]) -> None:
        self.collections = {
            "rag_studio_docs": sorted(points, key=lambda point: point.id)
        }
        self.scroll_calls: list[dict[str, Any]] = []

    async def collection_exists(self, collection_name: str) -> bool:
        return collection_name in self.collections

    async def create_collection(self, collection_name: str, **kwargs: Any) -> None:
        self.collections[collection_name] = []

    async def retrieve(
        self, collection_name: str, ids: list[str], **kwargs: Any
    ) -> list[FakePoint]:
        return [point for point in self.collections[collection_name] if point.id in ids]

    async def upsert(
        self, collection_name: str, points: list[Any], **kwargs: Any
    ) -> None:
        existing = {point.id: point for point in self.collections[collection_name]}
        for point in points:
            existing[str(point.id)] = FakePoint(
                str(point.id), dict(point.payload or {})
            )
        self.collections[collection_name] = sorted(
            existing.values(), key=lambda point: point.id
        )

    async def delete(
        self, collection_name: str, points_selector: Any, **kwargs: Any
    ) -> None:
        deleted = {str(point_id) for point_id in points_selector.points}
        self.collections[collection_name] = [
            point
            for point in self.collections[collection_name]
            if point.id not in deleted
        ]

    async def delete_collection(self, collection_name: str) -> None:
        del self.collections[collection_name]

    async def scroll(self, **kwargs: Any) -> tuple[list[FakePoint], str | None]:
        self.scroll_calls.append(kwargs)
        selected = self.collections[kwargs["collection_name"]]
        scroll_filter = kwargs.get("scroll_filter")
        if scroll_filter is not None:
            condition = scroll_filter.must[0]
            selected = [
                point
                for point in selected
                if point.payload.get(condition.key) == condition.match.value
            ]
        offset = kwargs.get("offset")
        start = 0
        if offset is not None:
            start = next(
                (
                    index + 1
                    for index, point in enumerate(selected)
                    if point.id == offset
                ),
                len(selected),
            )
        limit = int(kwargs["limit"])
        page = selected[start : start + limit]
        next_offset = page[-1].id if start + limit < len(selected) and page else None
        return page, next_offset


def _document_points(count: int) -> list[FakePoint]:
    return [
        FakePoint(
            id=f"point-{index:04d}",
            payload={
                "doc_id": f"doc-{index:04d}",
                "source": f"file-{count - index:04d}.txt",
                "total_chunks": 1,
                "chunk_size": 512,
                "chunk_overlap": 64,
                "created_at": "2026-08-01T00:00:00+00:00",
            },
        )
        for index in range(count)
    ]


def _chunk_points(count: int, doc_id: str = "doc-a") -> list[FakePoint]:
    return [
        FakePoint(
            id=f"point-{count - index:04d}",
            payload={
                "doc_id": doc_id,
                "chunk_index": index // 2,
                "text": f"chunk {index}",
                "token_count": 2,
                "page": 1,
            },
        )
        for index in range(count)
    ]


@contextmanager
def _client(fake: FakeQdrant) -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[get_qdrant_client] = lambda: fake
    with (
        patch(
            "src.api.main.wait_for_qdrant_ready",
            new_callable=AsyncMock,
            return_value=True,
        ),
        patch(
            "src.api.main.close_qdrant_client",
            new_callable=AsyncMock,
            return_value=None,
        ),
        TestClient(app) as client,
    ):
        yield client


def test_documents_continue_in_global_order_when_more_than_page_limit() -> None:
    # Given
    fake = FakeQdrant(_document_points(150))

    # When
    with _client(fake) as client:
        first = client.get("/api/ingest/documents")
        second = client.get(
            "/api/ingest/documents", params={"cursor": first.json()["next_cursor"]}
        )

    # Then
    assert first.status_code == 200
    assert second.status_code == 200
    first_data = first.json()
    second_data = second.json()
    filenames = [item["filename"] for item in first_data["documents"]]
    filenames += [item["filename"] for item in second_data["documents"]]
    assert len(first_data["documents"]) == 100
    assert len(second_data["documents"]) == 50
    assert first_data["total"] == second_data["total"] == 150
    assert filenames == sorted(filenames)
    assert len(filenames) == len(set(filenames)) == 150
    assert second_data["next_cursor"] is None


def test_chunk_cursor_orders_by_chunk_index_then_point_id() -> None:
    # Given
    fake = FakeQdrant(_chunk_points(205))

    # When
    pages: list[dict[str, Any]] = []
    with _client(fake) as client:
        cursor: str | None = None
        while True:
            response = client.get(
                "/api/ingest/documents/doc-a/chunks",
                params={"cursor": cursor} if cursor else None,
            )
            assert response.status_code == 200
            page = response.json()
            pages.append(page)
            cursor = page["next_cursor"]
            if cursor is None:
                break

    # Then
    chunks = [chunk for page in pages for chunk in page["chunks"]]
    keys = [(chunk["chunk_index"], chunk["point_id"]) for chunk in chunks]
    assert [len(page["chunks"]) for page in pages] == [100, 100, 5]
    assert keys == sorted(keys)
    assert len(keys) == len(set(keys)) == 205


def test_invalid_and_foreign_cursor_are_safe_validation_errors() -> None:
    # Given
    fake = FakeQdrant(_document_points(101) + _chunk_points(2))

    # When
    with _client(fake) as client:
        malformed = client.get(
            "/api/ingest/documents", params={"cursor": "not-a-cursor"}
        )
        first = client.get("/api/ingest/documents")
        foreign = client.get(
            "/api/ingest/documents/doc-a/chunks",
            params={"cursor": first.json()["next_cursor"]},
        )

    # Then
    assert malformed.status_code == 422
    assert foreign.status_code == 422
    assert "cursor" in malformed.json()["detail"].lower()
    assert "not-a-cursor" not in malformed.text


def test_scan_cap_is_explicit_and_never_exceeds_qdrant_bounds() -> None:
    # Given
    fake = FakeQdrant(_document_points(1_050))

    # When
    with _client(fake) as client:
        first = client.get("/api/ingest/documents")
        first_call_count = len(fake.scroll_calls)
        second = client.get(
            "/api/ingest/documents", params={"cursor": first.json()["next_cursor"]}
        )
        second_call_count = len(fake.scroll_calls) - first_call_count
        third = client.get(
            "/api/ingest/documents", params={"cursor": second.json()["next_cursor"]}
        )
        third_call_count = len(fake.scroll_calls) - first_call_count - second_call_count

    # Then
    assert first.status_code == second.status_code == third.status_code == 200
    assert first.json()["documents"] == second.json()["documents"] == []
    assert first.json()["truncated"] is second.json()["truncated"] is True
    assert first.json()["total"] is second.json()["total"] is None
    assert len(third.json()["documents"]) == 100
    raw_calls = [
        call
        for call in fake.scroll_calls
        if call["collection_name"] == "rag_studio_docs"
    ]
    assert len(raw_calls) == 11
    assert max(first_call_count, second_call_count, third_call_count) == 10
    assert all(call["limit"] == 100 for call in fake.scroll_calls)
    assert "rag_studio_document_index" in fake.collections


def test_static_ui_consumes_document_and_chunk_continuations() -> None:
    # Given / When
    with _client(FakeQdrant([])) as client:
        source = client.get("/static/js/app.js").text

    # Then
    assert "data.next_cursor" in source
    assert "data.chunks" in source
    assert "cursor=" in source
