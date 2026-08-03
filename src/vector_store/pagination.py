from __future__ import annotations

import base64
import hashlib
import hmac
import json
import math
import secrets
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Final, Literal, TypedDict

import anyio
from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models as qmodels

from src.vector_store.document_index import (
    DOCUMENT_INDEX_COLLECTION,
    prepare_document_index,
)
from src.vector_store.models import JsonValue

PAGE_SIZE: Final = 100
MAX_SCANNED_POINTS: Final = 1_000
MAX_QDRANT_PAGES: Final = 10
MAX_PAYLOAD_DEPTH: Final = 16
MAX_PAYLOAD_VALUES: Final = 10_000
CURSOR_VERSION: Final = 1
CURSOR_TTL_SECONDS: Final = 900
MAX_ACTIVE_SNAPSHOTS: Final = 10
MAX_RETAINED_SNAPSHOT_ITEMS: Final = MAX_ACTIVE_SNAPSHOTS * MAX_SCANNED_POINTS
_SORT_DOCUMENTS: Final = "filename,doc_id"
_SORT_CHUNKS: Final = "chunk_index,point_id"
_SORT_BACKFILL: Final = "document_index_backfill"
_SORT_INDEX_READY: Final = "document_index_ready"
_SIGNING_KEY: Final = secrets.token_bytes(32)
_CURSOR_PARSE_ERRORS: Final = (
    KeyError,
    TypeError,
    ValueError,
    json.JSONDecodeError,
    UnicodeDecodeError,
)

type ListingKind = Literal["documents", "chunks"]


class CursorPayload(TypedDict):
    v: int
    k: ListingKind
    f: str
    s: str
    w: int
    n: int
    sid: str
    pos: int
    exp: int


@dataclass(frozen=True, slots=True)
class ListedPoint:
    point_id: str
    payload: dict[str, JsonValue]


@dataclass(frozen=True, slots=True)
class ListingPage:
    items: tuple[ListedPoint, ...]
    next_cursor: str | None
    truncated: bool
    scanned_points: int
    matched_items: int


@dataclass(slots=True)
class _Snapshot:
    kind: ListingKind
    filter_value: str
    sort: str
    watermark: int
    scanned_points: int
    truncated: bool
    expires_at: int
    items: tuple[ListedPoint, ...]
    deleted_document_ids: set[str] = field(default_factory=set)


@dataclass(frozen=True, slots=True)
class CursorError(ValueError):
    reason: str = "invalid_cursor"

    def __str__(self) -> str:
        return self.reason


@dataclass(frozen=True, slots=True)
class PayloadError(ValueError):
    """Signal a vendor payload cannot be represented as bounded JSON data."""

    reason: str = "invalid_payload"

    def __str__(self) -> str:
        return self.reason


class QdrantListingPaginator:
    """Provide bounded, signed snapshot pagination over Qdrant scroll."""

    def __init__(self) -> None:
        self._snapshots: OrderedDict[str, _Snapshot] = OrderedDict()
        self._lock = threading.Lock()
        self._index_lock = anyio.Lock()

    async def documents(
        self,
        client: AsyncQdrantClient,
        collection_name: str,
        cursor: str | None,
    ) -> ListingPage:
        """Return one globally sorted bounded document page."""
        if cursor is not None:
            payload = _decode_cursor(cursor)
            if payload["s"] in (_SORT_BACKFILL, _SORT_INDEX_READY):
                _validate_transition(payload)
                async with self._index_lock:
                    return await self._document_start(client, collection_name)
            return self._continue(cursor, "documents", "")
        async with self._index_lock:
            return await self._document_start(client, collection_name)

    async def _document_start(
        self,
        client: AsyncQdrantClient,
        collection_name: str,
    ) -> ListingPage:
        preparation = await prepare_document_index(client, collection_name)
        if not preparation.complete:
            return _transition_page(_SORT_BACKFILL, preparation.scanned_points)
        if preparation.resumed:
            return _transition_page(_SORT_INDEX_READY, preparation.scanned_points)
        if preparation.already_complete:
            index_filter = qmodels.Filter(
                must=[
                    qmodels.FieldCondition(
                        key="record_type",
                        match=qmodels.MatchValue(value="document"),
                    )
                ]
            )
            points, truncated, scanned = await _scan_points(
                client, DOCUMENT_INDEX_COLLECTION, index_filter
            )
        else:
            points = tuple(
                ListedPoint(point.point_id, point.payload)
                for point in preparation.documents
            )
            truncated = False
            scanned = preparation.scanned_points
        documents: dict[str, ListedPoint] = {}
        for point in points:
            doc_id = str(point.payload.get("doc_id", ""))
            if doc_id and doc_id not in documents:
                documents[doc_id] = point
        ordered = tuple(sorted(documents.values(), key=_document_key))
        return self._start(
            "documents", "", _SORT_DOCUMENTS, ordered, truncated, scanned
        )

    async def chunks(
        self,
        client: AsyncQdrantClient,
        collection_name: str,
        doc_id: str,
        cursor: str | None,
    ) -> ListingPage:
        """Return one bounded chunk page ordered by index and point ID."""
        if cursor is not None:
            return self._continue(cursor, "chunks", doc_id)
        scroll_filter = qmodels.Filter(
            must=[
                qmodels.FieldCondition(
                    key="doc_id",
                    match=qmodels.MatchValue(value=doc_id),
                )
            ]
        )
        points, truncated, scanned = await _scan_points(
            client, collection_name, scroll_filter
        )
        ordered = tuple(sorted(points, key=_chunk_key))
        return self._start("chunks", doc_id, _SORT_CHUNKS, ordered, truncated, scanned)

    def invalidate_document(self, doc_id: str) -> None:
        """Mark a deleted document absent in all active snapshots."""
        with self._lock:
            for snapshot in self._snapshots.values():
                snapshot.deleted_document_ids.add(doc_id)

    def clear(self) -> None:
        """Invalidate all active snapshots after collection replacement."""
        with self._lock:
            self._snapshots.clear()

    def _start(
        self,
        kind: ListingKind,
        filter_value: str,
        sort: str,
        items: tuple[ListedPoint, ...],
        truncated: bool,
        scanned_points: int,
    ) -> ListingPage:
        now = int(time.time())
        snapshot_id = secrets.token_urlsafe(18)
        snapshot = _Snapshot(
            kind=kind,
            filter_value=filter_value,
            sort=sort,
            watermark=time.time_ns(),
            scanned_points=scanned_points,
            truncated=truncated,
            expires_at=now + CURSOR_TTL_SECONDS,
            items=items,
        )
        with self._lock:
            self._purge_expired(now)
            self._evict_for_snapshot(len(items))
            self._snapshots[snapshot_id] = snapshot
        return self._page(snapshot_id, snapshot, 0)

    def _continue(
        self, cursor: str, kind: ListingKind, filter_value: str
    ) -> ListingPage:
        payload = _decode_cursor(cursor)
        expected_sort = _SORT_DOCUMENTS if kind == "documents" else _SORT_CHUNKS
        if (
            payload["k"] != kind
            or payload["f"] != filter_value
            or payload["s"] != expected_sort
        ):
            raise CursorError
        now = int(time.time())
        with self._lock:
            self._purge_expired(now)
            snapshot = self._snapshots.get(payload["sid"])
            if snapshot is not None:
                self._snapshots.move_to_end(payload["sid"])
        if snapshot is None or payload["exp"] < now:
            raise CursorError
        if (
            snapshot.kind != payload["k"]
            or snapshot.filter_value != payload["f"]
            or snapshot.sort != payload["s"]
            or snapshot.watermark != payload["w"]
            or snapshot.scanned_points != payload["n"]
            or snapshot.expires_at != payload["exp"]
            or payload["pos"] < 1
            or payload["pos"] >= len(snapshot.items)
        ):
            raise CursorError
        return self._page(payload["sid"], snapshot, payload["pos"])

    def _page(
        self, snapshot_id: str, snapshot: _Snapshot, position: int
    ) -> ListingPage:
        window = snapshot.items[position : position + PAGE_SIZE]
        visible = tuple(
            point
            for point in window
            if str(point.payload.get("doc_id", "")) not in snapshot.deleted_document_ids
        )
        next_position = position + len(window)
        has_more = next_position < len(snapshot.items)
        next_cursor = (
            _encode_cursor(snapshot_id, snapshot, next_position) if has_more else None
        )
        return ListingPage(
            items=visible,
            next_cursor=next_cursor,
            truncated=snapshot.truncated,
            scanned_points=snapshot.scanned_points,
            matched_items=len(snapshot.items),
        )

    def _purge_expired(self, now: int) -> None:
        expired = [
            snapshot_id
            for snapshot_id, snapshot in self._snapshots.items()
            if snapshot.expires_at < now
        ]
        for snapshot_id in expired:
            del self._snapshots[snapshot_id]

    def _evict_for_snapshot(self, incoming_items: int) -> None:
        while self._snapshots and (
            len(self._snapshots) >= MAX_ACTIVE_SNAPSHOTS
            or self._retained_snapshot_items() + incoming_items
            > MAX_RETAINED_SNAPSHOT_ITEMS
        ):
            self._snapshots.popitem(last=False)

    def _retained_snapshot_items(self) -> int:
        return sum(len(snapshot.items) for snapshot in self._snapshots.values())


async def _scan_points(
    client: AsyncQdrantClient,
    collection_name: str,
    scroll_filter: qmodels.Filter | None,
) -> tuple[tuple[ListedPoint, ...], bool, int]:
    points: list[ListedPoint] = []
    offset: int | str | None = None
    next_offset: int | str | None = None
    response_exceeded_cap = False
    for _ in range(MAX_QDRANT_PAGES):
        raw_points, raw_next_offset = await client.scroll(
            collection_name=collection_name,
            scroll_filter=scroll_filter,
            limit=PAGE_SIZE,
            with_payload=True,
            with_vectors=False,
            offset=offset,
        )
        remaining = MAX_SCANNED_POINTS - len(points)
        accepted_points = raw_points[:remaining]
        response_exceeded_cap = len(raw_points) > len(accepted_points)
        for point in accepted_points:
            points.append(
                ListedPoint(
                    point_id=str(point.id),
                    payload=_payload(point.payload or {}),
                )
            )
        next_offset = _offset(raw_next_offset)
        if (
            response_exceeded_cap
            or next_offset is None
            or len(points) >= MAX_SCANNED_POINTS
        ):
            break
        offset = next_offset
    return tuple(points), response_exceeded_cap or next_offset is not None, len(points)


def _payload(raw: dict[str, object]) -> dict[str, JsonValue]:
    """Copy a bounded JSON-native payload without coercing vendor values."""
    payload: dict[str, JsonValue] = {}
    remaining = MAX_PAYLOAD_VALUES
    for key, value in raw.items():
        if not isinstance(key, str):
            raise PayloadError
        normalized, remaining = _json_value(value, 1, remaining)
        payload[key] = normalized
    return payload


def _json_value(value: object, depth: int, remaining: int) -> tuple[JsonValue, int]:
    """Return a recursively copied JSON value within fixed traversal bounds."""
    if depth > MAX_PAYLOAD_DEPTH or remaining < 1:
        raise PayloadError
    remaining -= 1
    match value:
        case None | bool() | int() | str():
            return value, remaining
        case float():
            if not math.isfinite(value):
                raise PayloadError
            return value, remaining
        case list():
            normalized_list: list[JsonValue] = []
            for item in value:
                normalized, remaining = _json_value(item, depth + 1, remaining)
                normalized_list.append(normalized)
            return normalized_list, remaining
        case dict():
            normalized_dict: dict[str, JsonValue] = {}
            for key, item in value.items():
                if not isinstance(key, str):
                    raise PayloadError
                normalized, remaining = _json_value(item, depth + 1, remaining)
                normalized_dict[key] = normalized
            return normalized_dict, remaining
        case _:
            raise PayloadError


def _offset(raw: object) -> int | str | None:
    if raw is None or isinstance(raw, (int, str)):
        return raw
    return str(raw)


def _document_key(point: ListedPoint) -> tuple[str, str]:
    return (
        str(point.payload.get("source", "")).casefold(),
        str(point.payload.get("doc_id", "")),
    )


def _chunk_key(point: ListedPoint) -> tuple[int, str]:
    raw_index = point.payload.get("chunk_index", 0)
    try:
        chunk_index = int(str(raw_index))
    except ValueError:
        chunk_index = 0
    return chunk_index, point.point_id


def _encode_cursor(snapshot_id: str, snapshot: _Snapshot, position: int) -> str:
    payload = CursorPayload(
        v=CURSOR_VERSION,
        k=snapshot.kind,
        f=snapshot.filter_value,
        s=snapshot.sort,
        w=snapshot.watermark,
        n=snapshot.scanned_points,
        sid=snapshot_id,
        pos=position,
        exp=snapshot.expires_at,
    )
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    signature = hmac.digest(_SIGNING_KEY, body, hashlib.sha256)
    return f"{_b64encode(body)}.{_b64encode(signature)}"


def _transition_page(sort: str, scanned_points: int) -> ListingPage:
    now = int(time.time())
    payload = CursorPayload(
        v=CURSOR_VERSION,
        k="documents",
        f="",
        s=sort,
        w=time.time_ns(),
        n=scanned_points,
        sid="document-index-transition",
        pos=0,
        exp=now + CURSOR_TTL_SECONDS,
    )
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    signature = hmac.digest(_SIGNING_KEY, body, hashlib.sha256)
    return ListingPage(
        items=(),
        next_cursor=f"{_b64encode(body)}.{_b64encode(signature)}",
        truncated=True,
        scanned_points=scanned_points,
        matched_items=0,
    )


def _validate_transition(payload: CursorPayload) -> None:
    if (
        payload["k"] != "documents"
        or payload["f"] != ""
        or payload["exp"] < int(time.time())
    ):
        raise CursorError


def _decode_cursor(cursor: str) -> CursorPayload:
    try:
        encoded_body, encoded_signature = cursor.split(".", maxsplit=1)
        body = _b64decode(encoded_body)
        signature = _b64decode(encoded_signature)
        expected = hmac.digest(_SIGNING_KEY, body, hashlib.sha256)
        if not hmac.compare_digest(signature, expected):
            raise CursorError
        raw = json.loads(body)
        payload = CursorPayload(
            v=int(raw["v"]),
            k=raw["k"],
            f=str(raw["f"]),
            s=str(raw["s"]),
            w=int(raw["w"]),
            n=int(raw["n"]),
            sid=str(raw["sid"]),
            pos=int(raw["pos"]),
            exp=int(raw["exp"]),
        )
    except _CURSOR_PARSE_ERRORS:
        raise CursorError from None
    if payload["v"] != CURSOR_VERSION or payload["k"] not in (
        "documents",
        "chunks",
    ):
        raise CursorError
    return payload


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.b64decode(value + padding, altchars=b"-_", validate=True)


listing_paginator = QdrantListingPaginator()
