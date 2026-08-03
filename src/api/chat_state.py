"""Bounded process-local cache for chat session metadata and messages."""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Final

SESSION_TTL_SECONDS: Final = 30 * 60
CLEANUP_BUDGET: Final = 20
MAX_SESSIONS: Final = 200
MAX_COMPLETED_TURNS: Final = 50
IDEMPOTENCY_TTL_SECONDS: Final = 10 * 60


class SessionCapacityError(RuntimeError):
    """Raised when every cached session is protected from eviction."""


class IdempotencyConflictError(RuntimeError):
    """Raised when an idempotency key is reused with different content."""


class ChatCacheConfigurationError(ValueError):
    """Raised when a cache limit would make bounded operation impossible."""


@dataclass(frozen=True, slots=True)
class CleanupResult:
    """Observable work performed by one request-boundary cleanup pass."""

    examined: int
    evicted: int


@dataclass(frozen=True, slots=True)
class _IdempotencyRecord:
    content: str
    user_message: dict[str, object]
    response: dict[str, object] | None
    expires_at: float


class ChatStateCache:
    """Own mutable, bounded chat state while persistence remains authoritative."""

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
        ttl_seconds: float = SESSION_TTL_SECONDS,
        cleanup_budget: int = CLEANUP_BUDGET,
        max_sessions: int = MAX_SESSIONS,
        max_completed_turns: int = MAX_COMPLETED_TURNS,
        idempotency_ttl_seconds: float = IDEMPOTENCY_TTL_SECONDS,
    ) -> None:
        if (
            min(
                ttl_seconds,
                cleanup_budget,
                max_sessions,
                max_completed_turns,
                idempotency_ttl_seconds,
            )
            <= 0
        ):
            raise ChatCacheConfigurationError("Chat cache limits must be positive")
        self._clock = clock
        self._ttl_seconds = ttl_seconds
        self._cleanup_budget = cleanup_budget
        self._max_sessions = max_sessions
        self._max_completed_turns = max_completed_turns
        self._idempotency_ttl_seconds = idempotency_ttl_seconds
        self.meta: dict[str, dict[str, object]] = {}
        self.messages: dict[str, list[dict[str, object]]] = {}
        self._accessed_at: dict[str, float] = {}
        self._access_order: dict[str, int] = {}
        self._next_access_order = 0
        self._active: set[str] = set()
        self._idempotency: dict[str, dict[str, _IdempotencyRecord]] = {}
        self._cleanup_queue: deque[str] = deque()
        self._queued: set[str] = set()

    @property
    def session_count(self) -> int:
        """Return the number of distinct memory-cached sessions."""
        return len(set(self.meta) | set(self.messages))

    def cleanup(self) -> CleanupResult:
        """Inspect a bounded number of sessions at one request boundary."""
        self._sync_external_entries()
        examined = min(self._cleanup_budget, len(self._cleanup_queue))
        evicted = 0
        now = self._clock()
        for _ in range(examined):
            session_id = self._cleanup_queue.popleft()
            self._queued.discard(session_id)
            if not self._exists(session_id):
                self._drop_bookkeeping(session_id)
                continue
            self._purge_idempotency(session_id, now)
            if self._expired(session_id, now) and not self._protected(session_id):
                self.remove(session_id)
                evicted += 1
                continue
            self._enqueue(session_id)
        return CleanupResult(examined=examined, evicted=evicted)

    def upsert_session(
        self, session_id: str, metadata: Mapping[str, object]
    ) -> dict[str, object]:
        """Insert or replace session metadata and refresh its TTL."""
        is_new = not self._exists(session_id)
        if is_new:
            self._drop_bookkeeping(session_id)
            self._admit_session(session_id)
            self.messages.setdefault(session_id, [])
        self.meta[session_id] = dict(metadata)
        self._touch(session_id)
        return self.meta[session_id]

    def get_meta(self, session_id: str) -> dict[str, object] | None:
        """Return cached metadata and refresh TTL, or evict an expired entry."""
        if not self._exists(session_id):
            return None
        if self._expired(session_id, self._clock()) and not self._protected(session_id):
            self.remove(session_id)
            return None
        self._touch(session_id)
        return self.meta.get(session_id)

    def get_messages(self, session_id: str) -> list[dict[str, object]] | None:
        """Return cached messages and refresh TTL, including an empty cache hit."""
        if self.get_meta(session_id) is None and session_id not in self.messages:
            return None
        self._touch(session_id)
        return self.messages.setdefault(session_id, [])

    def replace_messages(
        self, session_id: str, messages: list[dict[str, object]]
    ) -> list[dict[str, object]]:
        """Cache a rehydrated snapshot, trimming completed turns only."""
        self.messages[session_id] = list(messages)
        self._touch(session_id)
        self._trim_completed_turns(session_id)
        return self.messages[session_id]

    def store_user(
        self, session_id: str, content: str, message_id: str
    ) -> dict[str, object]:
        """Store one user message with bounded idempotency semantics."""
        now = self._clock()
        self._purge_idempotency(session_id, now)
        existing = self._idempotency.get(session_id, {}).get(message_id)
        if existing is not None:
            if existing.content != content:
                raise IdempotencyConflictError(message_id)
            self._touch(session_id)
            return existing.user_message
        message: dict[str, object] = {
            "id": message_id,
            "role": "user",
            "content": content,
        }
        self.messages.setdefault(session_id, []).append(message)
        self._idempotency.setdefault(session_id, {})[message_id] = _IdempotencyRecord(
            content=content,
            user_message=message,
            response=None,
            expires_at=now + self._idempotency_ttl_seconds,
        )
        self._touch(session_id)
        return message

    def store_assistant(
        self, session_id: str, message: dict[str, object]
    ) -> dict[str, object]:
        """Store a complete assistant message and enforce the turn cap."""
        self.messages.setdefault(session_id, []).append(message)
        reply_id = message.get("in_reply_to")
        if isinstance(reply_id, str):
            record = self._idempotency.get(session_id, {}).get(reply_id)
            if record is not None and self._clock() < record.expires_at:
                self._idempotency[session_id][reply_id] = _IdempotencyRecord(
                    content=record.content,
                    user_message=record.user_message,
                    response=message,
                    expires_at=record.expires_at,
                )
        self._touch(session_id)
        self._trim_completed_turns(session_id)
        return message

    def completed_response(
        self, session_id: str, message_id: str, content: str
    ) -> dict[str, object] | None:
        """Return a completed response while its idempotency record is live."""
        now = self._clock()
        self._purge_idempotency(session_id, now)
        record = self._idempotency.get(session_id, {}).get(message_id)
        if record is None:
            return None
        if record.content != content:
            raise IdempotencyConflictError(message_id)
        self._touch(session_id)
        return record.response

    def mark_active(self, session_id: str, *, active: bool) -> None:
        """Protect or release a session for the lifetime of a generation job."""
        if active:
            self._active.add(session_id)
            self._touch(session_id)
        else:
            self._active.discard(session_id)

    def remove(self, session_id: str) -> None:
        """Evict memory state only; callers own any explicit persistence deletion."""
        self.meta.pop(session_id, None)
        self.messages.pop(session_id, None)
        self._drop_bookkeeping(session_id)

    def clear(self) -> None:
        """Reset process-local state for deterministic shutdown and tests."""
        self.meta.clear()
        self.messages.clear()
        self._accessed_at.clear()
        self._access_order.clear()
        self._next_access_order = 0
        self._active.clear()
        self._idempotency.clear()
        self._cleanup_queue.clear()
        self._queued.clear()

    def _admit_session(self, incoming: str) -> None:
        if self.session_count < self._max_sessions:
            return
        candidates = (
            session_id
            for session_id in set(self.meta) | set(self.messages)
            if session_id != incoming and not self._protected(session_id)
        )
        lru = min(
            candidates, key=lambda item: self._access_order.get(item, 0), default=None
        )
        if lru is None:
            raise SessionCapacityError(incoming)
        self.remove(lru)

    def _touch(self, session_id: str) -> None:
        self._accessed_at[session_id] = self._clock()
        self._next_access_order += 1
        self._access_order[session_id] = self._next_access_order
        self._enqueue(session_id)

    def _enqueue(self, session_id: str) -> None:
        if session_id not in self._queued:
            self._cleanup_queue.append(session_id)
            self._queued.add(session_id)

    def _sync_external_entries(self) -> None:
        for session_id in set(self.meta) | set(self.messages):
            if session_id not in self._accessed_at:
                self._touch(session_id)

    def _exists(self, session_id: str) -> bool:
        return session_id in self.meta or session_id in self.messages

    def _expired(self, session_id: str, now: float) -> bool:
        return now - self._accessed_at.get(session_id, now) >= self._ttl_seconds

    def _protected(self, session_id: str) -> bool:
        return session_id in self._active or self._has_pending_turn(session_id)

    def _has_pending_turn(self, session_id: str) -> bool:
        return self._completed_pairs(session_id)[1]

    def _completed_pairs(self, session_id: str) -> tuple[list[set[int]], bool]:
        messages = self.messages.get(session_id, [])
        pending: list[tuple[int, str | None]] = []
        pairs: list[set[int]] = []
        for index, message in enumerate(messages):
            role = message.get("role")
            if role == "user":
                raw_id = message.get("id")
                pending.append((index, raw_id if isinstance(raw_id, str) else None))
            elif role == "assistant" and pending:
                reply_id = message.get("in_reply_to")
                match_index = next(
                    (
                        position
                        for position, (_, user_id) in enumerate(pending)
                        if isinstance(reply_id, str) and user_id == reply_id
                    ),
                    len(pending) - 1 if not isinstance(reply_id, str) else -1,
                )
                if match_index >= 0:
                    user_index, _ = pending.pop(match_index)
                    pairs.append({user_index, index})
        return pairs, bool(pending)

    def _trim_completed_turns(self, session_id: str) -> None:
        pairs, _ = self._completed_pairs(session_id)
        excess = len(pairs) - self._max_completed_turns
        if excess <= 0:
            return
        removed = set().union(*pairs[:excess])
        self.messages[session_id] = [
            message
            for index, message in enumerate(self.messages[session_id])
            if index not in removed
        ]

    def _purge_idempotency(self, session_id: str, now: float) -> None:
        records = self._idempotency.get(session_id)
        if records is None:
            return
        expired = [key for key, record in records.items() if now >= record.expires_at]
        for key in expired:
            records.pop(key, None)
        if not records:
            self._idempotency.pop(session_id, None)

    def _drop_bookkeeping(self, session_id: str) -> None:
        self._accessed_at.pop(session_id, None)
        self._access_order.pop(session_id, None)
        self._active.discard(session_id)
        self._idempotency.pop(session_id, None)
        self._queued.discard(session_id)
        self._cleanup_queue = deque(
            queued_id for queued_id in self._cleanup_queue if queued_id != session_id
        )
