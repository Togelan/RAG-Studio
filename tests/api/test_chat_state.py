from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from src.api.chat_state import (
    ChatStateCache,
    IdempotencyConflictError,
    SessionCapacityError,
)


class FakeClock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


@dataclass(frozen=True, slots=True)
class FakeCheckpointTuple:
    checkpoint: dict[str, object]


class FakeCheckpointer:
    def __init__(self, checkpoint: dict[str, object]) -> None:
        self.checkpoint = checkpoint
        self.calls = 0

    async def aget_tuple(self, config: Mapping[str, object]) -> FakeCheckpointTuple:
        del config
        self.calls += 1
        return FakeCheckpointTuple(self.checkpoint)


@dataclass(frozen=True, slots=True)
class FakeGraph:
    checkpointer: FakeCheckpointer


def _meta(session_id: str) -> dict[str, object]:
    return {"id": session_id, "title": session_id, "created_at": ""}


def _complete_turn(cache: ChatStateCache, session_id: str, index: int) -> None:
    user_id = f"user-{index}"
    cache.store_user(session_id, f"question-{index}", user_id)
    cache.store_assistant(
        session_id,
        {
            "id": f"answer-{index}",
            "role": "assistant",
            "content": f"answer-{index}",
            "in_reply_to": user_id,
        },
    )


def test_ttl_expires_at_boundary_and_access_refreshes() -> None:
    clock = FakeClock()
    cache = ChatStateCache(clock=clock)
    cache.upsert_session("before", _meta("before"))
    cache.upsert_session("at", _meta("at"))
    cache.upsert_session("after", _meta("after"))
    cache.upsert_session("refreshed", _meta("refreshed"))

    clock.advance(1799)
    assert cache.get_meta("before") is not None
    assert cache.get_meta("refreshed") is not None
    clock.advance(1)
    assert cache.get_meta("at") is None
    clock.advance(1)
    assert cache.get_meta("after") is None
    clock.advance(1798)
    assert cache.get_meta("refreshed") is None


def test_request_cleanup_scans_at_most_twenty_entries_and_makes_progress() -> None:
    clock = FakeClock()
    cache = ChatStateCache(clock=clock)
    for index in range(25):
        cache.upsert_session(f"session-{index}", _meta(f"session-{index}"))
    clock.advance(1800)

    first = cache.cleanup()
    second = cache.cleanup()

    assert (first.examined, first.evicted) == (20, 20)
    assert (second.examined, second.evicted) == (5, 5)
    assert cache.session_count == 0


def test_lru_capacity_evicts_only_memory_and_reports_exhaustion() -> None:
    clock = FakeClock()
    cache = ChatStateCache(clock=clock, max_sessions=3)
    for session_id in ("old", "middle", "recent"):
        cache.upsert_session(session_id, _meta(session_id))
        clock.advance(1)
    assert cache.get_meta("old") is not None

    cache.upsert_session("new", _meta("new"))

    assert cache.get_meta("middle") is None
    assert cache.session_count == 3
    for session_id in ("old", "recent", "new"):
        cache.mark_active(session_id, active=True)
    with pytest.raises(SessionCapacityError):
        cache.upsert_session("overflow", _meta("overflow"))


def test_default_global_limit_is_exactly_two_hundred_sessions() -> None:
    cache = ChatStateCache(clock=FakeClock())
    for index in range(201):
        cache.upsert_session(f"session-{index}", _meta(f"session-{index}"))

    assert cache.session_count == 200
    assert cache.get_meta("session-0") is None
    assert cache.get_meta("session-200") is not None


def test_route_maps_fully_protected_cache_to_retryable_503(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.api.routes import chat

    cache = ChatStateCache(clock=FakeClock(), max_sessions=1)
    cache.upsert_session("active", _meta("active"))
    cache.mark_active("active", active=True)
    monkeypatch.setattr(chat, "_chat_state", cache)

    with pytest.raises(HTTPException) as caught:
        chat._upsert_session_or_503("overflow", _meta("overflow"))

    assert caught.value.status_code == 503
    assert caught.value.headers is not None
    assert caught.value.headers["Retry-After"].isdigit()


def test_active_and_pending_sessions_are_exempt_from_ttl_and_lru() -> None:
    clock = FakeClock()
    cache = ChatStateCache(clock=clock, max_sessions=2)
    cache.upsert_session("active", _meta("active"))
    cache.mark_active("active", active=True)
    cache.upsert_session("pending", _meta("pending"))
    cache.store_user("pending", "unfinished", "pending-user")
    clock.advance(1800)

    result = cache.cleanup()

    assert result.evicted == 0
    assert cache.get_meta("active") is not None
    assert cache.get_meta("pending") is not None
    with pytest.raises(SessionCapacityError):
        cache.upsert_session("other", _meta("other"))


def test_completed_turn_limit_removes_whole_oldest_turns_only() -> None:
    cache = ChatStateCache(clock=FakeClock(), max_completed_turns=2)
    cache.upsert_session("chat", _meta("chat"))
    for index in range(3):
        _complete_turn(cache, "chat", index)
    cache.store_user("chat", "still running", "pending")

    messages = cache.get_messages("chat")

    assert messages is not None
    assert [message["id"] for message in messages] == [
        "user-1",
        "answer-1",
        "user-2",
        "answer-2",
        "pending",
    ]


def test_idempotency_retains_trimmed_response_for_ten_minutes() -> None:
    clock = FakeClock()
    cache = ChatStateCache(clock=clock, max_completed_turns=1)
    cache.upsert_session("chat", _meta("chat"))
    _complete_turn(cache, "chat", 0)
    _complete_turn(cache, "chat", 1)

    clock.advance(599)
    response = cache.completed_response("chat", "user-0", "question-0")
    clock.advance(1)
    expired = cache.completed_response("chat", "user-0", "question-0")

    assert response is not None and response["id"] == "answer-0"
    assert expired is None


def test_repeated_idempotency_key_reuses_user_and_rejects_other_content() -> None:
    cache = ChatStateCache(clock=FakeClock())
    cache.upsert_session("chat", _meta("chat"))

    first = cache.store_user("chat", "same", "request-id")
    repeated = cache.store_user("chat", "same", "request-id")

    assert repeated is first
    assert len(cache.get_messages("chat") or []) == 1
    with pytest.raises(IdempotencyConflictError):
        cache.store_user("chat", "different", "request-id")


def test_memory_eviction_can_be_rehydrated_without_cross_session_loss() -> None:
    cache = ChatStateCache(clock=FakeClock(), max_sessions=2)
    cache.upsert_session("one", _meta("one"))
    _complete_turn(cache, "one", 1)
    persistent_messages = list(cache.get_messages("one") or [])
    cache.remove("one")

    cache.upsert_session("one", _meta("one"))
    cache.replace_messages("one", persistent_messages)

    assert [message["content"] for message in cache.get_messages("one") or []] == [
        "question-1",
        "answer-1",
    ]


def test_route_rehydrate_preserves_checkpoint_and_capacity_status(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from src.api.main import create_app
    from src.api.routes import chat

    clock = FakeClock()
    cache = ChatStateCache(clock=clock, max_sessions=1)
    monkeypatch.setattr(chat, "_chat_state", cache)
    monkeypatch.setattr(chat, "_session_meta", cache.meta)
    monkeypatch.setattr(chat, "_session_messages", cache.messages)
    monkeypatch.setenv("RAG_STUDIO_DATA_ROOT", str(tmp_path / "runtime"))
    persistent_messages: list[dict[str, object]] = [
        {"id": "persisted-user", "role": "user", "content": "keep me"},
        {"id": "persisted-answer", "role": "assistant", "content": "kept"},
    ]
    checkpoint: dict[str, object] = {
        "channel_values": {"messages": persistent_messages}
    }
    checkpointer = FakeCheckpointer(checkpoint)
    with (
        patch("src.api.main.wait_for_qdrant_ready", new=AsyncMock(return_value=True)),
        patch("src.api.main.close_qdrant_client", new=AsyncMock(return_value=None)),
        TestClient(create_app()) as client,
    ):
        session_id = client.post("/api/chat/sessions", json={}).json()["id"]
        client.app.state.graph = FakeGraph(checkpointer)
        clock.advance(1800)

        response = client.get(f"/api/chat/sessions/{session_id}/messages")
        cache.mark_active(session_id, active=True)
        overload = client.get("/api/chat/sessions/other-persisted/messages")

    assert response.status_code == 200
    assert [message["content"] for message in response.json()] == ["keep me", "kept"]
    assert checkpoint["channel_values"] == {"messages": persistent_messages}
    assert checkpointer.calls == 2
    assert cache.session_count == 1
    assert overload.status_code == 503
    assert overload.headers["Retry-After"].isdigit()


def test_ten_sessions_at_turn_cap_do_not_share_or_lose_messages() -> None:
    cache = ChatStateCache(clock=FakeClock())
    for session_index in range(10):
        session_id = f"session-{session_index}"
        cache.upsert_session(session_id, _meta(session_id))
        for turn_index in range(51):
            _complete_turn(cache, session_id, turn_index)

    assert cache.session_count == 10
    for session_index in range(10):
        messages = cache.get_messages(f"session-{session_index}") or []
        assert len(messages) == 100
        assert messages[0]["content"] == "question-1"
        assert messages[-1]["content"] == "answer-50"
