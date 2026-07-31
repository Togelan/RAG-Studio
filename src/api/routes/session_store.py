"""Bounded in-memory session message store with LRU eviction.

Provides a thread-safe, bounded store for session messages using
collections.OrderedDict for LRU tracking. Enforces limits on total
sessions and messages per session to prevent unbounded memory growth.
"""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from typing import Any


class BoundedSessionStore:
    """LRU-bounded in-memory store for session messages.

    Uses OrderedDict for O(1) LRU eviction. All public methods are
    async and acquire an internal asyncio.Lock for thread safety.

    Attributes:
        max_sessions: Maximum number of sessions to retain.
        max_messages_per_session: Maximum messages per session.
    """

    def __init__(
        self, max_sessions: int = 50, max_messages_per_session: int = 100
    ) -> None:
        """Initialize with bounded limits.

        Args:
            max_sessions: Max sessions before LRU eviction.
            max_messages_per_session: Max messages retained per session.
        """
        self.max_sessions = max_sessions
        self.max_messages_per_session = max_messages_per_session
        self._store: OrderedDict[str, list[dict[str, object]]] = OrderedDict()
        self._lock = asyncio.Lock()

    async def get(self, session_id: str) -> list[dict[str, object]] | None:
        """Return messages for a session, marking it as recently used.

        Args:
            session_id: The session ID to look up.

        Returns:
            List of message dicts, or None if session not found.
        """
        async with self._lock:
            if session_id not in self._store:
                return None
            self._store.move_to_end(session_id)
            return self._store[session_id]

    async def put(self, session_id: str, messages: list[dict[str, object]]) -> None:
        """Store messages for a session, evicting LRU if over max_sessions.

        Trims messages to max_messages_per_session, keeping the newest.

        Args:
            session_id: The session ID.
            messages: List of message dicts to store.
        """
        async with self._lock:
            # Trim to max_messages_per_session (keep newest)
            if len(messages) > self.max_messages_per_session:
                messages = messages[-self.max_messages_per_session :]

            # If new session and at capacity, evict LRU
            if session_id not in self._store and len(self._store) >= self.max_sessions:
                self._store.popitem(last=False)

            self._store[session_id] = messages
            self._store.move_to_end(session_id)

    async def append(self, session_id: str, message: dict[str, object]) -> None:
        """Append one message to a session, creating the session if needed.

        Trims oldest messages if over max_messages_per_session.

        Args:
            session_id: The session ID.
            message: The message dict to append.
        """
        async with self._lock:
            if session_id not in self._store:
                # New session — evict LRU if at capacity
                if len(self._store) >= self.max_sessions:
                    self._store.popitem(last=False)
                self._store[session_id] = []

            self._store[session_id].append(message)

            # Trim oldest if over limit
            while len(self._store[session_id]) > self.max_messages_per_session:
                self._store[session_id].pop(0)

            self._store.move_to_end(session_id)

    async def pop(self, session_id: str) -> list[dict[str, object]] | None:
        """Remove and return session messages, or None if not found.

        Args:
            session_id: The session ID to remove.

        Returns:
            List of message dicts that were stored, or None.
        """
        async with self._lock:
            return self._store.pop(session_id, None)

    async def items_snapshot(self) -> dict[str, list[dict[str, object]]]:
        """Return a shallow copy of all sessions for safe iteration.

        Returns:
            Dict mapping session_id → list of message dicts.
        """
        async with self._lock:
            return dict(self._store)

    def __contains__(self, session_id: str) -> bool:
        """Check session existence (synchronous, not locked).

        For quick membership checks. Use get() for atomic access.

        Args:
            session_id: The session ID to check.

        Returns:
            True if session exists in the store.
        """
        return session_id in self._store

    async def clear(self) -> None:
        """Remove all sessions from the store.

        Used by test fixtures to reset state between tests.
        """
        async with self._lock:
            self._store.clear()

    async def __aiter__(self) -> Any:
        """Async iteration not supported — use items_snapshot()."""
        raise NotImplementedError("Use items_snapshot() for safe iteration")
