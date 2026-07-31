"""Deterministic coverage for real chat streaming and bounded admission."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Generator
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessageChunk

from src.api.chat_stream import (
    MAX_CONCURRENT_STREAMS,
    StreamCapacityError,
    StreamLifecycleManager,
    StreamSessionConflictError,
)
from src.graph.builder import GraphResultError, stream_rag_graph


def _result(answer: str = "Hello world") -> dict[str, Any]:
    return {
        "final_answer": answer,
        "generated_from": "retrieval",
        "faithfulness_score": 0.9,
        "retrieved_docs": [
            {
                "text": "grounded context",
                "score": 0.95,
                "metadata": {"filename": "source.md", "chunk_index": 0},
            }
        ],
        "citations": [
            {
                "index": 1,
                "chunk_text": "grounded context",
                "filename": "source.md",
                "chunk_index": "0",
                "score": 0.95,
            }
        ],
    }


class _FakeCompiledGraph:
    async def astream(self, *_args: Any, **_kwargs: Any) -> AsyncIterator[object]:
        yield (
            "messages",
            (
                AIMessageChunk(content="Hello "),
                {"langgraph_node": "generate_from_retrieval"},
            ),
        )
        yield (
            "messages",
            (AIMessageChunk(content="ignored"), {"langgraph_node": "validate"}),
        )
        yield (
            "messages",
            (
                AIMessageChunk(content="world"),
                {"langgraph_node": "generate_from_retrieval"},
            ),
        )
        yield ("values", _result())


@pytest.mark.asyncio
async def test_graph_stream_emits_provider_chunks_before_result() -> None:
    """Only generation-node provider chunks are emitted, in source order."""
    events = [
        event
        async for event in stream_rag_graph(
            "question",
            "session",
            compiled_graph=_FakeCompiledGraph(),
        )
    ]

    assert [event["token"] for event in events[:-1]] == ["Hello ", "world"]
    assert events[-1]["type"] == "result"
    assert events[-1]["result"]["final_answer"] == "Hello world"


@pytest.mark.asyncio
async def test_graph_stream_rejects_non_mapping_result() -> None:
    """Malformed graph state is rejected at the serialization boundary."""

    class InvalidGraph:
        async def astream(self, *_args: Any, **_kwargs: Any) -> AsyncIterator[object]:
            yield ("values", 7)

    with pytest.raises(GraphResultError, match="invalid result"):
        async for _event in stream_rag_graph(
            "question",
            "session",
            compiled_graph=InvalidGraph(),
        ):
            pass


@pytest.mark.asyncio
async def test_lifecycle_enforces_session_and_global_limits() -> None:
    """Admission is atomic, bounded to ten, and idempotently released."""
    manager = StreamLifecycleManager()
    await manager.acquire("same-session")
    with pytest.raises(StreamSessionConflictError):
        await manager.acquire("same-session")
    await manager.release("same-session")

    for index in range(MAX_CONCURRENT_STREAMS):
        await manager.acquire(f"session-{index}")
    with pytest.raises(StreamCapacityError):
        await manager.acquire("overflow")

    snapshot = await manager.snapshot()
    assert snapshot.active_count == MAX_CONCURRENT_STREAMS
    for index in range(MAX_CONCURRENT_STREAMS):
        await manager.release(f"session-{index}")
    assert (await manager.snapshot()).active_count == 0


async def _fake_graph_stream(
    *_args: Any, **_kwargs: Any
) -> AsyncIterator[dict[str, Any]]:
    yield {"type": "token", "token": "Hello "}
    await asyncio.sleep(0)
    yield {"type": "token", "token": "world"}
    yield {"type": "result", "result": _result()}


async def _stalled_graph_stream(
    *_args: Any, **_kwargs: Any
) -> AsyncIterator[dict[str, Any]]:
    await asyncio.sleep(1)
    yield {"type": "result", "result": _result()}


@pytest.fixture(name="client")
def fixture_client(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> Generator[TestClient]:
    """Create an isolated app whose graph stream never reaches a provider."""
    monkeypatch.setenv("RAG_STUDIO_DATA_ROOT", str(tmp_path / "runtime"))
    from src.api import dependencies
    from src.api.routes import chat

    dependencies._audit_logger = None  # pyright: ignore[reportPrivateUsage]
    chat._session_meta.clear()  # pyright: ignore[reportPrivateUsage]
    chat._session_messages.clear()  # pyright: ignore[reportPrivateUsage]
    chat._stream_lifecycle = StreamLifecycleManager()  # pyright: ignore[reportPrivateUsage]
    with (
        patch("src.api.main.wait_for_qdrant_ready", new=AsyncMock(return_value=True)),
        patch("src.api.main.close_qdrant_client", new=AsyncMock(return_value=None)),
        patch("src.api.routes.chat.stream_rag_graph", new=_fake_graph_stream),
    ):
        from src.api.main import create_app

        with TestClient(create_app()) as test_client:
            yield test_client


def _events(response_lines: list[str]) -> list[tuple[str, dict[str, Any]]]:
    event_name = "message"
    parsed: list[tuple[str, dict[str, Any]]] = []
    for line in response_lines:
        if line.startswith("event: "):
            event_name = line.removeprefix("event: ")
        elif line.startswith("data: "):
            parsed.append((event_name, json.loads(line.removeprefix("data: "))))
    return parsed


def test_endpoint_uses_named_sse_protocol_and_persists_complete_turn(
    client: TestClient,
) -> None:
    """The browser receives real chunks and one completed assistant message."""
    with client.stream(
        "POST",
        "/api/chat/send",
        json={"content": "question", "session_id": "stream-session"},
    ) as response:
        lines = list(response.iter_lines())

    assert response.status_code == 200
    assert response.headers["x-stream-protocol"] == "1"
    events = _events(lines)
    assert [name for name, _payload in events] == [
        "start",
        "progress",
        "progress",
        "token",
        "token",
        "progress",
        "done",
    ]
    token_text = "".join(
        payload["token"] for name, payload in events if name == "token"
    )
    assert token_text == "Hello world"

    messages = client.get("/api/chat/sessions/stream-session/messages").json()
    assert [message["role"] for message in messages] == ["user", "assistant"]
    assert messages[-1]["content"] == "Hello world"


def test_endpoint_maps_admission_errors(client: TestClient) -> None:
    """Same-session conflicts and global saturation have actionable status codes."""
    from src.api.routes import chat

    with patch.object(
        chat._stream_lifecycle,  # pyright: ignore[reportPrivateUsage]
        "acquire",
        new=AsyncMock(side_effect=StreamSessionConflictError("session")),
    ):
        conflict = client.post(
            "/api/chat/send",
            json={"content": "question", "session_id": "session"},
        )
    assert conflict.status_code == 409

    with patch.object(
        chat._stream_lifecycle,  # pyright: ignore[reportPrivateUsage]
        "acquire",
        new=AsyncMock(side_effect=StreamCapacityError("10")),
    ):
        saturated = client.post(
            "/api/chat/send",
            json={"content": "question", "session_id": "other"},
        )
    assert saturated.status_code == 503
    assert saturated.headers["Retry-After"].isdigit()


def test_stream_contract_and_decision_evidence_are_canonical() -> None:
    """Requirements and every project role enforce measurable decision evidence."""
    spec = Path("system_spec.md").read_text(encoding="utf-8")
    for required in (
        "actual provider chunks",
        "at most 10 simultaneous streams",
        "409 Conflict",
        "503 Service Unavailable",
        "never persists a partial assistant message",
    ):
        assert required in spec

    guidance_paths = [
        Path("AGENTS.md"),
        Path(".agents/copilot-instructions.md"),
        Path(".agents/agents/architect.md"),
        Path(".agents/agents/ba.md"),
        Path(".agents/agents/developer.md"),
        Path(".agents/agents/qa.md"),
    ]
    for path in guidance_paths:
        guidance = path.read_text(encoding="utf-8").lower()
        assert "two" in guidance and "alternative" in guidance, path
        assert "load" in guidance, path
        assert "safety" in guidance or "safe" in guidance, path


@pytest.mark.asyncio
async def test_cancelled_stream_never_persists_partial_assistant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Closing a response after a token retains the user but no partial answer."""
    from src.api.routes import chat

    chat._session_messages.clear()  # pyright: ignore[reportPrivateUsage]
    chat._session_meta["cancel-session"] = {  # pyright: ignore[reportPrivateUsage]
        "id": "cancel-session",
        "title": "Chat",
        "created_at": "",
    }
    chat._stream_lifecycle = StreamLifecycleManager()  # pyright: ignore[reportPrivateUsage]
    await chat._stream_lifecycle.acquire("cancel-session")  # pyright: ignore[reportPrivateUsage]
    monkeypatch.setattr(chat, "stream_rag_graph", _fake_graph_stream)
    request = SimpleNamespace(is_disconnected=AsyncMock(return_value=False))

    stream = chat._sse_stream(  # pyright: ignore[reportPrivateUsage]
        "cancel-session",
        "question",
        request,
        compiled_graph=object(),
    )
    assert "event: start" in await anext(stream)
    assert "event: progress" in await anext(stream)
    assert "event: progress" in await anext(stream)
    assert "event: token" in await anext(stream)
    await stream.aclose()

    stored = chat._session_messages["cancel-session"]  # pyright: ignore[reportPrivateUsage]
    assert [message["role"] for message in stored] == ["user"]
    assert (await chat._stream_lifecycle.snapshot()).active_count == 0  # pyright: ignore[reportPrivateUsage]


@pytest.mark.asyncio
async def test_stalled_stream_heartbeats_then_stops_at_max_duration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stalled provider remains observable but cannot retain a slot forever."""
    from src.api.routes import chat

    chat._session_messages.clear()  # pyright: ignore[reportPrivateUsage]
    chat._stream_lifecycle = StreamLifecycleManager()  # pyright: ignore[reportPrivateUsage]
    await chat._stream_lifecycle.acquire("stalled-session")  # pyright: ignore[reportPrivateUsage]
    monkeypatch.setattr(chat, "stream_rag_graph", _stalled_graph_stream)
    monkeypatch.setattr(chat, "STREAM_HEARTBEAT_SECONDS", 0.01)
    monkeypatch.setattr(chat, "STREAM_MAX_DURATION_SECONDS", 0.03)
    request = SimpleNamespace(is_disconnected=AsyncMock(return_value=False))

    events = [
        event
        async for event in chat._sse_stream(  # pyright: ignore[reportPrivateUsage]
            "stalled-session",
            "question",
            request,
            compiled_graph=object(),
        )
    ]

    assert any(event.startswith(": heartbeat") for event in events)
    assert any("event: error" in event for event in events)
    assert [
        message["role"]
        for message in chat._session_messages["stalled-session"]  # pyright: ignore[reportPrivateUsage]
    ] == ["user"]
    assert (await chat._stream_lifecycle.snapshot()).active_count == 0  # pyright: ignore[reportPrivateUsage]
