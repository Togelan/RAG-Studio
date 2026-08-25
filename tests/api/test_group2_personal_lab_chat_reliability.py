from __future__ import annotations

from collections.abc import AsyncGenerator, Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from src.api.personal_chat_jobs import (
    PersonalChatJobCapacityError,
    PersonalChatJobConflictError,
    PersonalChatJobNotFoundError,
    PersonalChatJobRegistry,
)
from src.api.personal_chat_state import PersonalChatResult
from src.api.personal_lab_registry import PersonalLabRouteDependencies
from src.api.personal_lab_scope import PersonalLabScope, PersonalLabScopeResolver
from src.api.routes.personal_chat import create_personal_chat_router
from src.api.saas_security import SaasCsrfMiddleware
from tests.api.test_group2_personal_lab_chat_scope import _app, _authorize


@dataclass(frozen=True, slots=True)
class _Claims:
    user_id: UUID


@dataclass(frozen=True, slots=True)
class _Auth:
    user_id: UUID

    async def resolve(self, request: Request, *, require_workspace: bool):
        del request, require_workspace
        return type("AuthResult", (), {"claims": _Claims(self.user_id)})()


class _ScopeRegistry:
    def __init__(self, scope_id: UUID) -> None:
        self.scope_id = scope_id

    async def resolve(self, user_id: UUID) -> UUID:
        del user_id
        return self.scope_id


class _ControlledJobs:
    def __init__(self) -> None:
        self.start_error: Exception | None = None
        self.cancelled = False

    async def start(self, *args, **kwargs) -> AsyncGenerator[str]:
        del kwargs
        if self.start_error is not None:
            raise self.start_error
        producer = args[2]
        events: list[str] = []

        async def publish(event: str) -> None:
            events.append(event)

        await producer(publish)
        return _events(events)

    async def subscribe(self, *args) -> AsyncGenerator[str]:
        del args
        raise PersonalChatJobNotFoundError

    async def cancel_and_wait(self, *args) -> bool:
        del args
        return self.cancelled

    async def shutdown(self) -> None:
        return None


async def _events(events: list[str]) -> AsyncGenerator[str]:
    for event in events:
        yield event


async def _execute(
    scope: PersonalLabScope, query: str, session_id: str
) -> PersonalChatResult:
    del scope, session_id
    if query == "explode":
        raise RuntimeError("provider-secret-and-private-path")
    return PersonalChatResult(answer="complete", generated_from="retrieval")


def _fixture(
    tmp_path: Path, jobs=None, scope_id: UUID | None = None
) -> tuple[TestClient, _ControlledJobs | PersonalChatJobRegistry, UUID]:
    selected_scope = scope_id or uuid4()
    dependencies = PersonalLabRouteDependencies(
        _Auth(uuid4()),
        PersonalLabScopeResolver(_ScopeRegistry(selected_scope), tmp_path / "personal"),
    )
    selected_jobs = jobs or PersonalChatJobRegistry(capacity=2)
    app = FastAPI()
    app.add_middleware(
        SaasCsrfMiddleware,
        trusted_origins=("https://testserver",),
        protected_roots=("/api/personal",),
    )
    app.include_router(
        create_personal_chat_router(dependencies, jobs=selected_jobs, execute=_execute)
    )
    return TestClient(app, base_url="https://testserver"), selected_jobs, selected_scope


def _headers(client: TestClient) -> dict[str, str]:
    client.cookies.set("__Host-ragstudio-csrf", "proof")
    return {"X-CSRF-Token": "proof", "Origin": "https://testserver"}


def _session(client: TestClient, headers: dict[str, str]) -> str:
    response = client.post(
        "/api/personal/chat/sessions", headers=headers, json={"title": "Chat"}
    )
    return str(response.json()["id"])


def test_completed_replay_conflict_capacity_and_sanitized_failure(
    tmp_path: Path,
) -> None:
    controlled = _ControlledJobs()
    client, _, _ = _fixture(tmp_path, controlled)
    with client:
        headers = _headers(client)
        session_id = _session(client, headers)
        first = client.post(
            "/api/personal/chat/send",
            headers=headers,
            json={"session_id": session_id, "message_id": "m1", "content": "hi"},
        )
        replay = client.post(
            "/api/personal/chat/send",
            headers=headers,
            json={"session_id": session_id, "message_id": "m1", "content": "hi"},
        )
        conflict = client.post(
            "/api/personal/chat/send",
            headers=headers,
            json={"session_id": session_id, "message_id": "m1", "content": "changed"},
        )
        controlled.start_error = PersonalChatJobConflictError()
        live_conflict = client.post(
            "/api/personal/chat/send",
            headers=headers,
            json={"session_id": session_id, "message_id": "m2", "content": "next"},
        )
        controlled.start_error = PersonalChatJobCapacityError()
        capacity = client.post(
            "/api/personal/chat/send",
            headers=headers,
            json={"session_id": session_id, "message_id": "m3", "content": "next"},
        )

    assert first.status_code == replay.status_code == 200
    assert '"completed":true' in replay.text
    assert conflict.status_code == live_conflict.status_code == 409
    assert capacity.status_code == 503
    assert capacity.headers["Retry-After"] == "1"
    assert "provider-secret-and-private-path" not in capacity.text


def test_cancel_is_idempotent_and_restart_reattach_is_truthful(tmp_path: Path) -> None:
    controlled = _ControlledJobs()
    client, _, scope_id = _fixture(tmp_path, controlled)
    with client:
        headers = _headers(client)
        session_id = _session(client, headers)
        idle = client.post(
            f"/api/personal/chat/sessions/{session_id}/cancel", headers=headers
        )
        controlled.cancelled = True
        stopped = client.post(
            f"/api/personal/chat/sessions/{session_id}/cancel", headers=headers
        )
        restarted_client, _, _ = _fixture(tmp_path, _ControlledJobs(), scope_id)
        with restarted_client:
            reattach = restarted_client.get(
                f"/api/personal/chat/sessions/{session_id}/stream"
            )

    assert idle.json()["status"] == "idle"
    assert stopped.json()["status"] == "stopped"
    assert reattach.status_code == 404
    assert reattach.json()["detail"] == "No active response. Reload session messages."


def test_provider_failure_is_sanitized_and_keeps_recoverable_user_turn(
    tmp_path: Path,
) -> None:
    client, _, _ = _fixture(tmp_path)
    with client:
        headers = _headers(client)
        session_id = _session(client, headers)
        failed = client.post(
            "/api/personal/chat/send",
            headers=headers,
            json={
                "session_id": session_id,
                "message_id": "failed-message",
                "content": "explode",
            },
        )
        messages = client.get(f"/api/personal/chat/sessions/{session_id}/messages")

    assert failed.status_code == 200
    assert '"code":"response_failed"' in failed.text
    assert "provider-secret-and-private-path" not in failed.text
    assert [item["role"] for item in messages.json()] == ["user"]


@pytest.mark.anyio
async def test_job_registry_bounds_scope_conflict_capacity_cancel_and_restart() -> None:
    first_scope, second_scope = uuid4(), uuid4()
    first_session, second_session = str(uuid4()), str(uuid4())
    blocker = pytest.importorskip("anyio").Event()

    async def produce(publish: Callable[[str], Awaitable[None]]) -> None:
        await publish("event: start\ndata: {}\n\n")
        await blocker.wait()

    jobs = PersonalChatJobRegistry(capacity=1)
    await jobs.start(first_scope, first_session, produce, buffer_max_bytes=1024)
    with pytest.raises(PersonalChatJobConflictError):
        await jobs.start(first_scope, first_session, produce, buffer_max_bytes=1024)
    with pytest.raises(PersonalChatJobCapacityError):
        await jobs.start(second_scope, second_session, produce, buffer_max_bytes=1024)
    with pytest.raises(PersonalChatJobNotFoundError):
        await jobs.subscribe(second_scope, first_session)
    assert await jobs.cancel_and_wait(first_scope, first_session) is True
    assert await jobs.cancel_and_wait(first_scope, first_session) is False
    with pytest.raises(PersonalChatJobNotFoundError):
        await PersonalChatJobRegistry(capacity=1).subscribe(first_scope, first_session)


def test_create_session_requires_identity_and_csrf_before_mutation(
    tmp_path: Path,
) -> None:
    app, first_scope, _ = _app(tmp_path)
    client = TestClient(app, base_url="https://testserver")
    with client:
        client.cookies.set("__Host-ragstudio-csrf", "proof")
        unauthenticated = client.post(
            "/api/personal/chat/sessions",
            headers={"X-CSRF-Token": "proof", "Origin": "https://testserver"},
        )
        client.cookies.set("identity", "a")
        missing_csrf = client.post("/api/personal/chat/sessions")
        valid = client.post(
            "/api/personal/chat/sessions", headers=_authorize(client, "a")
        )

    database = tmp_path / "personal" / f"pl_{first_scope.hex}" / "chat.sqlite"
    assert unauthenticated.status_code == 401
    assert missing_csrf.status_code == 403
    assert valid.status_code == 201
    assert database.is_file()
