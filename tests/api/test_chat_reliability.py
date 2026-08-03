"""Regression coverage for safe chat persistence failures."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Generator
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from src.graph.retry import ProviderFailureError
from src.graph.session import SessionPersistenceError


@pytest.fixture(name="client")
def fixture_client(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> Generator[TestClient, Any]:
    """Create an app with startup dependencies and persistence isolated."""
    monkeypatch.setenv("RAG_STUDIO_DATA_ROOT", str(tmp_path / "runtime-data"))

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
    ):
        from src.api.main import create_app

        with TestClient(create_app()) as test_client:
            yield test_client


@pytest.fixture(autouse=True)
def reset_chat_state() -> Generator[None]:
    """Avoid leaking module-level session metadata between tests."""
    from src.api.routes import chat

    chat._session_meta.clear()  # pyright: ignore[reportPrivateUsage]
    chat._session_messages.clear()  # pyright: ignore[reportPrivateUsage]
    yield


def test_sse_checkpoint_error_does_not_expose_exception_text(
    client: TestClient,
) -> None:
    """SSE persistence errors provide a stable public message only."""
    with (
        patch(
            "src.api.routes.chat.stream_rag_graph",
            new_callable=AsyncMock,
            side_effect=RuntimeError("sqlite password=never-expose"),
        ),
        client.stream(
            "POST", "/api/chat/send", json={"content": "persist this safely"}
        ) as response,
    ):
        payloads = [
            json.loads(line.removeprefix("data: "))
            for line in response.iter_lines()
            if line.startswith("data: ") and line != "data: {}"
        ]

    assert response.status_code == 200
    final = payloads[-1]
    assert final["code"] == "stream_failed"
    assert final["retryable"] is True
    assert "temporarily unavailable" in final["message"]
    assert "never-expose" not in final["message"]


def test_delete_checkpoint_error_preserves_session_and_hides_details(
    client: TestClient,
) -> None:
    """Failed persistent deletion returns a safe error without losing local state."""
    session = client.post("/api/chat/sessions", json={"title": "Keep me"}).json()
    session_id = session["id"]

    with patch(
        "src.api.routes.chat.delete_graph_session",
        new_callable=AsyncMock,
        side_effect=SessionPersistenceError("disk details must remain private"),
    ):
        response = client.delete(f"/api/chat/sessions/{session_id}")

    assert response.status_code == 503
    assert (
        response.json()["detail"]
        == "Session could not be deleted safely. Please retry."
    )
    assert "disk details" not in response.text
    assert client.get(f"/api/chat/sessions/{session_id}/messages").status_code == 200


def test_terminal_auth_failure_is_safe_nonretryable_and_called_once(
    client: TestClient,
) -> None:
    failure = ProviderFailureError(
        code="provider_request_failed",
        retryable=False,
        stage="invoke",
        attempt=1,
    )
    stream = AsyncMock(side_effect=failure)

    with (
        patch("src.api.routes.chat.stream_rag_graph", stream),
        client.stream(
            "POST",
            "/api/chat/send",
            json={"content": "prompt-secret-must-not-leak"},
        ) as response,
    ):
        payloads = [
            json.loads(line.removeprefix("data: "))
            for line in response.iter_lines()
            if line.startswith("data: ") and line != "data: {}"
        ]

    assert response.status_code == 200
    assert payloads[-1]["code"] == "provider_request_failed"
    assert payloads[-1]["retryable"] is False
    assert "prompt-secret-must-not-leak" not in payloads[-1]["message"]
    assert stream.await_count == 1
    from src.api.routes import chat

    assert not any(
        message.get("role") == "assistant"
        for messages in chat._session_messages.values()
        for message in messages
    )


def test_post_token_failure_emits_safe_error_without_assistant_persistence(
    client: TestClient,
) -> None:
    async def post_token_failure(**kwargs: Any) -> AsyncIterator[dict[str, Any]]:
        del kwargs
        yield {"type": "token", "token": "partial-secret"}
        raise ProviderFailureError(
            code="provider_temporary_unavailable",
            retryable=True,
            stage="stream",
            attempt=1,
        )

    with (
        patch("src.api.routes.chat.stream_rag_graph", post_token_failure),
        client.stream(
            "POST", "/api/chat/send", json={"content": "do not persist partial"}
        ) as response,
    ):
        payloads = [
            json.loads(line.removeprefix("data: "))
            for line in response.iter_lines()
            if line.startswith("data: ") and line != "data: {}"
        ]

    from src.api.routes import chat

    assert response.status_code == 200
    assert [item["token"] for item in payloads if "token" in item] == ["partial-secret"]
    assert payloads[-1]["code"] == "provider_temporary_unavailable"
    assert payloads[-1]["retryable"] is True
    assert not any(
        message.get("role") == "assistant"
        for messages in chat._session_messages.values()
        for message in messages
    )
