"""Regression coverage for safe chat persistence failures."""

from __future__ import annotations

import json
from collections.abc import Generator
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from src.graph.session import SessionPersistenceError


@pytest.fixture(name="client")
def fixture_client(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> Generator[TestClient, Any, None]:
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
def reset_chat_state() -> Generator[None, None, None]:
    """Avoid leaking module-level session metadata between tests."""
    import src.api.routes.chat as chat

    chat._session_meta.clear()  # pyright: ignore[reportPrivateUsage]
    chat._session_messages.clear()  # pyright: ignore[reportPrivateUsage]
    yield


def test_sse_checkpoint_error_does_not_expose_exception_text(client: TestClient) -> None:
    """SSE persistence errors provide a stable public message only."""
    with patch(
        "src.api.routes.chat.run_rag_graph",
        new_callable=AsyncMock,
        side_effect=RuntimeError("sqlite password=never-expose"),
    ):
        with client.stream(
            "POST", "/api/chat/send", json={"content": "persist this safely"}
        ) as response:
            payloads = [
                json.loads(line.removeprefix("data: "))
                for line in response.iter_lines()
                if line.startswith("data: ") and line != "data: {}"
            ]

    assert response.status_code == 200
    final = payloads[-1]
    assert final["done"] is True
    assert "temporarily unavailable" in final["full_response"]
    assert "never-expose" not in final["full_response"]


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
    assert response.json()["detail"] == "Session could not be deleted safely. Please retry."
    assert "disk details" not in response.text
    assert client.get(f"/api/chat/sessions/{session_id}/messages").status_code == 200
