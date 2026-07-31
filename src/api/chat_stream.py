"""Concurrency admission and framing helpers for chat SSE streams."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any

MAX_CONCURRENT_STREAMS = 10
STREAM_RETRY_AFTER_SECONDS = 1
STREAM_HEARTBEAT_SECONDS = 15.0
STREAM_MAX_DURATION_SECONDS = 300.0
STREAM_PROTOCOL_VERSION = "1"


class StreamSessionConflictError(RuntimeError):
    """Raised when a session already has an active response stream."""


class StreamCapacityError(RuntimeError):
    """Raised when the process-wide stream limit has been reached."""


@dataclass(frozen=True, slots=True)
class StreamSnapshot:
    """Immutable admission-state snapshot used by tests and diagnostics."""

    active_count: int
    active_sessions: frozenset[str]


class StreamLifecycleManager:
    """Atomically enforce global capacity and one active stream per session."""

    def __init__(self, capacity: int = MAX_CONCURRENT_STREAMS) -> None:
        if capacity <= 0:
            raise ValueError("Stream capacity must be positive")
        self._capacity = capacity
        self._active_sessions: set[str] = set()
        self._lock = asyncio.Lock()

    async def acquire(self, session_id: str) -> None:
        """Reserve a stream slot or raise a typed admission error."""
        async with self._lock:
            if session_id in self._active_sessions:
                raise StreamSessionConflictError(session_id)
            if len(self._active_sessions) >= self._capacity:
                raise StreamCapacityError(str(self._capacity))
            self._active_sessions.add(session_id)

    async def release(self, session_id: str) -> None:
        """Release a session slot; repeated release is intentionally safe."""
        async with self._lock:
            self._active_sessions.discard(session_id)

    async def snapshot(self) -> StreamSnapshot:
        """Return the current bounded admission state."""
        async with self._lock:
            return StreamSnapshot(
                active_count=len(self._active_sessions),
                active_sessions=frozenset(self._active_sessions),
            )


def sse_event(event: str, payload: dict[str, Any]) -> str:
    """Encode one named SSE event with a JSON payload."""
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return f"event: {event}\ndata: {data}\n\n"


def sse_heartbeat() -> str:
    """Return a protocol-valid SSE comment heartbeat."""
    return ": heartbeat\n\n"
