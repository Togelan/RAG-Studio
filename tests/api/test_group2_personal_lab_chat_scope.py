from __future__ import annotations

import socket
import threading
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from src.api.personal_chat_state import PersonalChatResult
from src.api.personal_lab_registry import PersonalLabRouteDependencies
from src.api.personal_lab_scope import PersonalLabScope, PersonalLabScopeResolver
from src.api.routes.personal_chat import create_personal_chat_router
from src.api.saas_security import SaasCsrfMiddleware


@dataclass(frozen=True, slots=True)
class _Claims:
    user_id: UUID


@dataclass(frozen=True, slots=True)
class _AuthResult:
    claims: _Claims


@dataclass(frozen=True, slots=True)
class _CookieAuth:
    identities: dict[str, UUID]

    async def resolve(
        self, request: Request, *, require_workspace: bool
    ) -> _AuthResult:
        del require_workspace
        user_id = self.identities.get(request.cookies.get("identity", ""))
        if user_id is None:
            raise HTTPException(status_code=401, detail="Authentication required.")
        return _AuthResult(_Claims(user_id))


class _ScopeRegistry:
    def __init__(self, scopes: dict[UUID, UUID]) -> None:
        self._scopes = scopes

    async def resolve(self, user_id: UUID) -> UUID:
        return self._scopes[user_id]


async def _execute(
    scope: PersonalLabScope, query: str, session_id: str
) -> PersonalChatResult:
    del scope, session_id
    return PersonalChatResult(
        answer=f"answer:{query}",
        generated_from="retrieval",
        citations=(
            {
                "document_id": "doc-a",
                "filename": "synthetic.txt",
                "chunk_index": 2,
                "text": "must-not-cross-the-wire",
                "path": "private/system/path",
            },
        ),
    )


def _app(tmp_path: Path) -> tuple[FastAPI, UUID, UUID]:
    first_user, second_user = uuid4(), uuid4()
    scopes = {first_user: uuid4(), second_user: uuid4()}
    dependencies = PersonalLabRouteDependencies(
        _CookieAuth({"a": first_user, "b": second_user}),
        PersonalLabScopeResolver(_ScopeRegistry(scopes), tmp_path / "personal"),
    )
    app = FastAPI()
    app.add_middleware(
        SaasCsrfMiddleware,
        trusted_origins=("https://testserver",),
        protected_roots=("/api/personal",),
    )
    app.include_router(create_personal_chat_router(dependencies, execute=_execute))
    return app, scopes[first_user], scopes[second_user]


def _fixture(tmp_path: Path) -> tuple[TestClient, UUID, UUID]:
    app, first_scope, second_scope = _app(tmp_path)
    return TestClient(app, base_url="https://testserver"), first_scope, second_scope


def _authorize(client: TestClient, identity: str) -> dict[str, str]:
    client.cookies.set("identity", identity)
    client.cookies.set("__Host-ragstudio-csrf", "proof")
    return {"X-CSRF-Token": "proof", "Origin": "https://testserver"}


def _create_session(client: TestClient, headers: dict[str, str]) -> str:
    response = client.post(
        "/api/personal/chat/sessions",
        headers=headers,
        json={"title": "Private"},
    )
    assert response.status_code == 201
    return str(response.json()["id"])


def _send_and_feedback(
    client: TestClient, headers: dict[str, str], session_id: str
) -> tuple[httpx.Response, httpx.Response, httpx.Response]:
    sent = client.post(
        "/api/personal/chat/send",
        headers=headers,
        json={
            "session_id": session_id,
            "message_id": "message-a",
            "content": "hello",
        },
    )
    messages = client.get(f"/api/personal/chat/sessions/{session_id}/messages")
    feedback = client.post(
        "/api/personal/chat/feedback",
        headers=headers,
        json={
            "session_id": session_id,
            "message_id": messages.json()[-1]["id"],
            "feedback": "like",
        },
    )
    return sent, messages, feedback


def _foreign_requests(
    client: TestClient,
    headers: dict[str, str],
    session_id: str,
    assistant_id: str,
) -> tuple[httpx.Response, ...]:
    _authorize(client, "b")
    return (
        client.get("/api/personal/chat/sessions"),
        client.get(f"/api/personal/chat/sessions/{session_id}/messages"),
        client.post(
            "/api/personal/chat/feedback",
            headers=headers,
            json={
                "session_id": session_id,
                "message_id": assistant_id,
                "feedback": "dislike",
            },
        ),
        client.post(
            f"/api/personal/chat/sessions/{session_id}/cancel", headers=headers
        ),
        client.get(f"/api/personal/chat/sessions/{session_id}/stream"),
    )


def test_sessions_messages_citations_and_feedback_are_scope_owned(
    tmp_path: Path,
) -> None:
    client, first_scope, second_scope = _fixture(tmp_path)
    with client:
        headers = _authorize(client, "a")
        session_id = _create_session(client, headers)
        sent, first_messages, feedback = _send_and_feedback(client, headers, session_id)
        assistant_id = first_messages.json()[-1]["id"]
        foreign = _foreign_requests(client, headers, session_id, assistant_id)

    assert sent.status_code == 200
    assert feedback.status_code == 201
    assert foreign[0].json() == []
    assert all(response.status_code == 404 for response in foreign[1:])
    assistant = first_messages.json()[-1]
    assert assistant["citations"] == [
        {"document_id": "doc-a", "filename": "synthetic.txt", "chunk_index": 2}
    ]
    assert "must-not-cross-the-wire" not in sent.text
    assert "private/system/path" not in sent.text
    assert (tmp_path / "personal" / f"pl_{first_scope.hex}" / "chat.sqlite").is_file()
    assert not (
        tmp_path / "personal" / f"pl_{second_scope.hex}" / "chat.sqlite"
    ).exists()


def test_personal_chat_requires_cookie_identity_and_csrf(tmp_path: Path) -> None:
    client, _, _ = _fixture(tmp_path)
    with client:
        unauthenticated = client.get("/api/personal/chat/sessions")
        client.cookies.set("identity", "a")
        missing_csrf = client.post(
            "/api/personal/chat/sessions", json={"title": "Denied"}
        )
        headers = _authorize(client, "a")
        wrong_origin = client.post(
            "/api/personal/chat/sessions",
            headers={**headers, "Origin": "https://foreign.invalid"},
            json={"title": "Denied"},
        )

    assert unauthenticated.status_code == 401
    assert missing_csrf.status_code == 403
    assert wrong_origin.status_code == 403


def test_session_rename_commit_clear_and_delete_lifecycle(tmp_path: Path) -> None:
    client, _, _ = _fixture(tmp_path)
    with client:
        headers = _authorize(client, "a")
        session_id = _create_session(client, headers)
        renamed = client.patch(
            f"/api/personal/chat/sessions/{session_id}",
            headers=headers,
            json={"title": "Renamed"},
        )
        committed = client.post(
            f"/api/personal/chat/sessions/{session_id}/messages",
            headers=headers,
            json={"message_id": "manual", "content": "draft"},
        )
        cleared = client.delete(
            f"/api/personal/chat/sessions/{session_id}/messages", headers=headers
        )
        after_clear = client.get(f"/api/personal/chat/sessions/{session_id}/messages")
        deleted = client.delete(
            f"/api/personal/chat/sessions/{session_id}", headers=headers
        )
        missing = client.get(f"/api/personal/chat/sessions/{session_id}/messages")

    assert renamed.status_code == 200
    assert renamed.json()["title"] == "Renamed"
    assert committed.status_code == 201
    assert cleared.json()["status"] == "cleared"
    assert after_clear.json() == []
    assert deleted.json()["status"] == "deleted"
    assert missing.status_code == 404


def _start_live_server(app: FastAPI) -> tuple[uvicorn.Server, threading.Thread, str]:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    return server, thread, f"http://127.0.0.1:{port}"


def test_live_http_personal_chat_is_scope_isolated(
    tmp_path: Path, record_property
) -> None:
    app, _, _ = _app(tmp_path)
    server, thread, origin = _start_live_server(app)
    try:
        with httpx.Client(base_url=origin, timeout=5.0) as client:
            for _ in range(100):
                try:
                    client.get("/openapi.json")
                    break
                except httpx.ConnectError:
                    continue
            client.cookies.set("__Host-ragstudio-csrf", "proof")
            client.cookies.set("identity", "a")
            headers = {"X-CSRF-Token": "proof", "Origin": origin}
            created = client.post(
                "/api/personal/chat/sessions",
                headers=headers,
                json={"title": "Live"},
            )
            session_id = str(created.json()["id"])
            sent = client.post(
                "/api/personal/chat/send",
                headers=headers,
                json={
                    "session_id": session_id,
                    "message_id": "live-message",
                    "content": "hello",
                },
            )
            client.cookies.set("identity", "b")
            foreign = client.get(f"/api/personal/chat/sessions/{session_id}/messages")
    finally:
        server.should_exit = True
        thread.join(timeout=5.0)

    assert not thread.is_alive()
    assert created.status_code == 201
    assert sent.status_code == 200
    assert '"full_response":"answer:hello"' in sent.text
    assert foreign.status_code == 404
    record_property("loopback_origin", origin)
    record_property("observable", "A=stream complete; B=404; raw citation absent")
