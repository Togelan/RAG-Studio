from __future__ import annotations

import math
from typing import Any

import anyio
import pytest

import src.vector_store.pagination as pagination_module
from src.vector_store.pagination import (
    CursorError,
    PayloadError,
    QdrantListingPaginator,
)


class FakePoint:
    def __init__(self, point_id: str, index: int) -> None:
        self.id = point_id
        self.payload = {
            "doc_id": f"doc-{index:04d}",
            "source": f"file-{index:04d}.txt",
            "total_chunks": 1,
        }


class AsyncFakeQdrant:
    def __init__(self, count: int) -> None:
        self.collections = {
            "documents": [
                FakePoint(f"point-{index:04d}", index) for index in range(count)
            ]
        }
        self.calls = 0

    async def collection_exists(self, collection_name: str) -> bool:
        return collection_name in self.collections

    async def create_collection(self, collection_name: str, **kwargs: Any) -> None:
        self.collections[collection_name] = []

    async def retrieve(
        self, collection_name: str, ids: list[str], **kwargs: Any
    ) -> list[Any]:
        return [
            point for point in self.collections[collection_name] if str(point.id) in ids
        ]

    async def upsert(
        self, collection_name: str, points: list[Any], **kwargs: Any
    ) -> None:
        existing = {str(point.id): point for point in self.collections[collection_name]}
        for point in points:
            stored = type("StoredPoint", (), {})()
            stored.id = str(point.id)
            stored.payload = dict(point.payload or {})
            existing[stored.id] = stored
        self.collections[collection_name] = list(existing.values())

    async def scroll(self, **kwargs: Any) -> tuple[list[FakePoint], str | None]:
        self.calls += 1
        offset = kwargs.get("offset")
        points = sorted(
            self.collections[kwargs["collection_name"]], key=lambda point: str(point.id)
        )
        start = 0
        if offset is not None:
            start = next(
                (
                    index + 1
                    for index, point in enumerate(points)
                    if str(point.id) == str(offset)
                ),
                len(points),
            )
        limit = int(kwargs["limit"])
        page = points[start : start + limit]
        next_offset = page[-1].id if start + limit < len(points) else None
        return page, next_offset


class SinglePayloadQdrant:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    async def scroll(self, **kwargs: Any) -> tuple[list[Any], None]:
        point = type("Point", (), {})()
        point.id = "point-payload"
        point.payload = self.payload
        return [point], None


def test_payload_preserves_json_shape_and_rejects_non_json_values() -> None:
    # Given
    nested_payload = {
        "metadata": {
            "tags": ["trusted", "<ignore previous instructions>"],
            "attributes": {"rank": 2, "active": True, "note": None},
        }
    }

    # When
    preserved = pagination_module._payload(nested_payload)

    # Then
    assert preserved == nested_payload
    with pytest.raises(PayloadError, match="invalid_payload"):
        pagination_module._payload({"vendor_value": object()})


@pytest.mark.anyio
async def test_paginator_preserves_prompt_like_json_payload_without_coercion() -> None:
    # Given
    payload = {
        "doc_id": "doc-prompt-like",
        "text": "<ignore previous instructions>",
        "metadata": {"labels": ["trusted", "assistant"]},
    }

    # When
    page = await QdrantListingPaginator().chunks(
        SinglePayloadQdrant(payload), "documents", "doc-prompt-like", None
    )

    # Then
    assert len(page.items) == 1
    assert page.items[0].payload == payload


@pytest.mark.anyio
async def test_paginator_rejects_over_depth_payload_at_public_boundary() -> None:
    # Given
    nested: dict[str, Any] = {"leaf": "value"}
    for _ in range(64):
        nested = {"nested": nested}

    # When / Then
    with pytest.raises(PayloadError, match="invalid_payload"):
        await QdrantListingPaginator().chunks(
            SinglePayloadQdrant({"doc_id": "doc-depth", "metadata": nested}),
            "documents",
            "doc-depth",
            None,
        )


@pytest.mark.anyio
async def test_paginator_rejects_over_budget_payload_at_public_boundary() -> None:
    # Given
    values = list(range(20_000))

    # When / Then
    with pytest.raises(PayloadError, match="invalid_payload"):
        await QdrantListingPaginator().chunks(
            SinglePayloadQdrant({"doc_id": "doc-budget", "values": values}),
            "documents",
            "doc-budget",
            None,
        )


@pytest.mark.anyio
@pytest.mark.parametrize(
    "non_finite",
    [math.nan, math.inf, -math.inf],
    ids=["nan", "positive-infinity", "negative-infinity"],
)
async def test_paginator_rejects_non_finite_float_at_public_boundary(
    non_finite: float,
) -> None:
    # Given
    payload = {"doc_id": "doc-non-finite", "score": non_finite}

    # When / Then
    with pytest.raises(PayloadError, match="invalid_payload"):
        await QdrantListingPaginator().chunks(
            SinglePayloadQdrant(payload), "documents", "doc-non-finite", None
        )


@pytest.mark.anyio
async def test_cursor_is_invalid_after_paginator_restart() -> None:
    # Given
    fake = AsyncFakeQdrant(101)
    first_process = QdrantListingPaginator()
    first = await first_process.documents(fake, "documents", None)

    # When / Then
    with pytest.raises(CursorError):
        await QdrantListingPaginator().documents(fake, "documents", first.next_cursor)


@pytest.mark.anyio
async def test_expired_cursor_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    # Given
    fake = AsyncFakeQdrant(101)
    paginator = QdrantListingPaginator()
    first = await paginator.documents(fake, "documents", None)
    monkeypatch.setattr(pagination_module.time, "time", lambda: 9_999_999_999)

    # When / Then
    with pytest.raises(CursorError):
        await paginator.documents(fake, "documents", first.next_cursor)


@pytest.mark.anyio
async def test_ten_concurrent_snapshots_have_unique_cursors_and_finite_calls() -> None:
    # Given
    fake = AsyncFakeQdrant(101)
    paginator = QdrantListingPaginator()
    cursors: list[str] = []

    async def request_page() -> None:
        page = await paginator.documents(fake, "documents", None)
        assert page.next_cursor is not None
        cursors.append(page.next_cursor)

    # When
    async with anyio.create_task_group() as tasks:
        for _ in range(10):
            tasks.start_soon(request_page)

    # Then
    assert len(cursors) == len(set(cursors)) == 10
    assert fake.calls == 20


@pytest.mark.anyio
async def test_cancellation_escapes_blocked_scroll_without_retry() -> None:
    # Given
    started = anyio.Event()

    class BlockingQdrant(AsyncFakeQdrant):
        def __init__(self) -> None:
            super().__init__(0)
            self.calls = 0

        async def scroll(self, **kwargs: Any) -> tuple[list[FakePoint], str | None]:
            self.calls += 1
            started.set()
            await anyio.sleep_forever()

    fake = BlockingQdrant()
    paginator = QdrantListingPaginator()

    # When
    async with anyio.create_task_group() as tasks:
        tasks.start_soon(paginator.documents, fake, "documents", None)
        await started.wait()
        tasks.cancel_scope.cancel()

    # Then
    assert fake.calls == 1
    assert paginator._snapshots == {}


@pytest.mark.anyio
async def test_snapshot_excludes_additions_and_deleted_window_is_not_replaced() -> None:
    # Given
    fake = AsyncFakeQdrant(101)
    paginator = QdrantListingPaginator()
    first = await paginator.documents(fake, "documents", None)
    fake.collections["documents"].append(FakePoint("point-9999", 9999))
    paginator.invalidate_document("doc-0100")

    # When
    second = await paginator.documents(fake, "documents", first.next_cursor)

    # Then
    assert second.items == ()
    assert second.next_cursor is None
    assert fake.calls == 2


@pytest.mark.anyio
async def test_over_returning_scroll_is_sliced_to_scan_cap() -> None:
    # Given
    class OverReturningQdrant:
        async def scroll(self, **kwargs: Any) -> tuple[list[Any], None]:
            points = []
            for index in range(1_500):
                point = type("Point", (), {})()
                point.id = f"point-{index:04d}"
                point.payload = {
                    "doc_id": "doc-a",
                    "chunk_index": index,
                    "text": str(index),
                }
                points.append(point)
            return points, None

    # When
    page = await QdrantListingPaginator().chunks(
        OverReturningQdrant(), "documents", "doc-a", None
    )

    # Then
    assert page.scanned_points == page.matched_items == 1_000
    assert page.truncated is True
