from __future__ import annotations

import pytest

from src.vector_store.pagination import (
    MAX_ACTIVE_SNAPSHOTS,
    MAX_RETAINED_SNAPSHOT_ITEMS,
    MAX_SCANNED_POINTS,
    CursorError,
    ListedPoint,
    ListingPage,
    QdrantListingPaginator,
)


def _items(label: str, count: int = MAX_SCANNED_POINTS) -> tuple[ListedPoint, ...]:
    return tuple(
        ListedPoint(
            point_id=f"{label}-{index:04d}",
            payload={"doc_id": "document-a", "chunk_index": index},
        )
        for index in range(count)
    )


def _start_page(paginator: QdrantListingPaginator, label: str) -> ListingPage:
    return paginator._start(
        "chunks", "document-a", "chunk_index,point_id", _items(label), False, 1_000
    )


def test_snapshot_retention_bounds_repeated_first_pages_and_rejects_oldest_cursor() -> (
    None
):
    # Given
    paginator = QdrantListingPaginator()
    cursors: list[str] = []
    for index in range(MAX_ACTIVE_SNAPSHOTS):
        page = _start_page(paginator, f"snapshot-{index}")
        assert page.next_cursor is not None
        cursors.append(page.next_cursor)

    # When
    _start_page(paginator, "snapshot-over-capacity")

    # Then
    assert len(paginator._snapshots) == MAX_ACTIVE_SNAPSHOTS
    assert (
        sum(len(snapshot.items) for snapshot in paginator._snapshots.values())
        == MAX_RETAINED_SNAPSHOT_ITEMS
    )
    with pytest.raises(CursorError, match="invalid_cursor"):
        paginator._continue(cursors[0], "chunks", "document-a")
    assert paginator._continue(cursors[-1], "chunks", "document-a").items


def test_snapshot_retention_keeps_recently_used_cursor_before_lru_eviction() -> None:
    # Given
    paginator = QdrantListingPaginator()
    cursors: list[str] = []
    for index in range(MAX_ACTIVE_SNAPSHOTS):
        page = _start_page(paginator, f"snapshot-{index}")
        assert page.next_cursor is not None
        cursors.append(page.next_cursor)

    # When
    recent_page = paginator._continue(cursors[0], "chunks", "document-a")
    _start_page(paginator, "snapshot-over-capacity")

    # Then
    assert recent_page.next_cursor is not None
    assert paginator._continue(recent_page.next_cursor, "chunks", "document-a").items
    with pytest.raises(CursorError, match="invalid_cursor"):
        paginator._continue(cursors[1], "chunks", "document-a")
