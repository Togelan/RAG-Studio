"""Unit tests for BoundedSessionStore — LRU eviction and message trimming.

Covers EDGE-C01: bounded in-memory storage with max 50 sessions and
max 100 messages per session.
"""

from __future__ import annotations

import pytest

from src.api.routes.session_store import BoundedSessionStore


@pytest.fixture
def store() -> BoundedSessionStore:
    """Return a fresh BoundedSessionStore for each test."""
    return BoundedSessionStore(max_sessions=50, max_messages_per_session=100)


class TestMessageTrimming:
    """Verify per-session message count limits."""

    @pytest.mark.asyncio
    async def test_append_trims_to_100_keeping_newest(
        self, store: BoundedSessionStore
    ) -> None:
        """Appending 150 messages keeps only the newest 100."""
        for i in range(150):
            await store.append("s1", {"role": "user", "content": f"msg_{i}"})
        messages = await store.get("s1")
        assert messages is not None
        assert len(messages) == 100
        assert messages[0]["content"] == "msg_50"  # oldest kept
        assert messages[-1]["content"] == "msg_149"  # newest kept

    @pytest.mark.asyncio
    async def test_put_trims_to_100_keeping_newest(
        self, store: BoundedSessionStore
    ) -> None:
        """put() with 150 messages keeps newest 100."""
        msgs: list[dict[str, object]] = [
            {"role": "user", "content": f"msg_{i}"} for i in range(150)
        ]
        await store.put("s1", msgs)
        messages = await store.get("s1")
        assert messages is not None
        assert len(messages) == 100
        assert messages[-1]["content"] == "msg_149"

    @pytest.mark.asyncio
    async def test_append_trim_removes_oldest_one_by_one(
        self, store: BoundedSessionStore
    ) -> None:
        """Each append beyond 100 pops the oldest message."""
        for i in range(101):
            await store.append("s1", {"role": "user", "content": f"msg_{i}"})
        messages = await store.get("s1")
        assert messages is not None
        assert len(messages) == 100
        assert messages[0]["content"] == "msg_1"
        assert messages[-1]["content"] == "msg_100"


class TestSessionEviction:
    """Verify max sessions LRU eviction."""

    @pytest.mark.asyncio
    async def test_max_50_sessions_lru_eviction(
        self, store: BoundedSessionStore
    ) -> None:
        """Adding 60 sessions keeps only the 50 most recently used."""
        for i in range(60):
            await store.put(f"sess_{i}", [{"role": "user", "content": f"msg_{i}"}])
        snapshot = await store.items_snapshot()
        assert len(snapshot) == 50
        # First 10 sessions should be evicted
        for i in range(10):
            assert await store.get(f"sess_{i}") is None
        # Last 50 sessions should remain
        assert await store.get("sess_59") is not None

    @pytest.mark.asyncio
    async def test_get_promotes_to_mru(self, store: BoundedSessionStore) -> None:
        """get() marks session as recently used, protecting it from eviction."""
        # Fill to capacity
        for i in range(50):
            await store.put(f"sess_{i:03d}", [{"content": f"msg_{i}"}])
        # Access sess_000 (oldest), promoting it to MRU
        await store.get("sess_000")
        # Add one more session — should evict sess_001 (now oldest), NOT sess_000
        await store.put("sess_new", [{"content": "new"}])
        assert await store.get("sess_000") is not None  # protected by get()
        assert await store.get("sess_001") is None  # evicted

    @pytest.mark.asyncio
    async def test_evicted_session_returns_none(
        self, store: BoundedSessionStore
    ) -> None:
        """Evicted sessions return None from get()."""
        await store.put("s1", [{"content": "hello"}])
        await store.pop("s1")
        assert await store.get("s1") is None


class TestPop:
    """Verify pop() behavior."""

    @pytest.mark.asyncio
    async def test_pop_existing_session(self, store: BoundedSessionStore) -> None:
        """pop() removes and returns session messages."""
        await store.put("s1", [{"content": "hello"}, {"content": "world"}])
        msgs = await store.pop("s1")
        assert msgs is not None
        assert len(msgs) == 2
        assert await store.get("s1") is None

    @pytest.mark.asyncio
    async def test_pop_nonexistent_returns_none(
        self, store: BoundedSessionStore
    ) -> None:
        """pop() on nonexistent session returns None."""
        assert await store.pop("no_such") is None


class TestSnapshot:
    """Verify items_snapshot() behavior."""

    @pytest.mark.asyncio
    async def test_snapshot_is_copy_not_reference(
        self, store: BoundedSessionStore
    ) -> None:
        """Snapshot key-level mutations don't affect the store."""
        await store.put("s1", [{"content": "hello"}])
        snapshot = await store.items_snapshot()
        # Deleting a key from snapshot doesn't affect store
        del snapshot["s1"]
        assert await store.get("s1") is not None
        # Adding a key to snapshot doesn't affect store
        snapshot["s2"] = [{"content": "intruder"}]
        assert "s2" not in store


class TestAppendAutoCreate:
    """Verify append() auto-creates sessions."""

    @pytest.mark.asyncio
    async def test_append_auto_creates_session(
        self, store: BoundedSessionStore
    ) -> None:
        """append() creates session if it doesn't exist."""
        assert "new_session" not in store
        await store.append("new_session", {"content": "first"})
        assert "new_session" in store
        msgs = await store.get("new_session")
        assert msgs is not None
        assert len(msgs) == 1


class TestClear:
    """Verify clear() removes all sessions."""

    @pytest.mark.asyncio
    async def test_clear_removes_all(self, store: BoundedSessionStore) -> None:
        """clear() empties the store."""
        await store.put("s1", [{"content": "a"}])
        await store.put("s2", [{"content": "b"}])
        await store.clear()
        assert await store.items_snapshot() == {}
