"""Deterministic credential-free chat surface for Stage 2 runtime QA."""

from __future__ import annotations

import json
import threading
import uuid
from collections.abc import AsyncIterator
from typing import Literal, assert_never

import anyio
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from scripts.qa.stage2_qa_schema import WorkloadProfile

_CREATED_AT = "2026-01-01T00:00:00Z"
_NAMESPACE = uuid.UUID("52695ef8-3fb5-45e7-88d0-4be43a78b7a5")


class SessionRequest(BaseModel):
    """Validated deterministic session request."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    title: str = Field(min_length=1, max_length=200)


class MessageCommit(BaseModel):
    """Validated committed user message."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    content: str = Field(min_length=1, max_length=10_000)
    message_id: str = Field(min_length=1, max_length=100)


class MessageSend(MessageCommit):
    """Validated deterministic stream request."""

    session_id: str = Field(min_length=1, max_length=100)


class QaSession(BaseModel):
    """Public session shape consumed by the React client."""

    model_config = ConfigDict(frozen=True)
    id: str
    title: str
    created_at: str = _CREATED_AT
    updated_at: str = _CREATED_AT
    message_count: int = 0


class QaMessage(BaseModel):
    """Public committed message shape."""

    model_config = ConfigDict(frozen=True)
    id: str
    session_id: str
    role: Literal["user"] = "user"
    content: str
    created_at: str = _CREATED_AT
    citations: list[str] = Field(default_factory=list)
    feedback: None = None


class CancelResponse(BaseModel):
    """Public cancellation result."""

    model_config = ConfigDict(frozen=True)
    status: Literal["cancelled"] = "cancelled"


class ChatMetrics(BaseModel):
    """Redacted live admission metrics for the load barrier."""

    model_config = ConfigDict(frozen=True)
    active_streams: int
    max_streams: int
    engine: Literal["deterministic-fake-graph"]


class QaChatState:
    """Thread-safe mutable fake used only by the isolated QA application."""

    def __init__(self, workload: WorkloadProfile) -> None:
        self.workload = workload
        self._lock = threading.RLock()
        self._sessions: dict[str, QaSession] = {}
        self._messages: dict[str, dict[str, QaMessage]] = {}
        self._active_sessions: set[str] = set()
        self._cancelled_sessions: set[str] = set()
        self._list_requests = 0

    def create_session(self, title: str) -> QaSession:
        """Create one deterministic session."""
        with self._lock:
            ordinal = len(self._sessions)
            session_id = f"qa-session-{uuid.uuid5(_NAMESPACE, str(ordinal)).hex[:12]}"
            session = QaSession(id=session_id, title=title)
            self._sessions[session_id] = session
            self._messages[session_id] = {}
            return session

    def list_sessions(self) -> tuple[QaSession, ...] | None:
        """Return sessions until the fixed QA rate limit is exhausted."""
        with self._lock:
            self._list_requests += 1
            if self._list_requests > self.workload.rate_limit_requests:
                return None
            return tuple(self._sessions.values())

    def commit(self, session_id: str, payload: MessageCommit) -> QaMessage | None:
        """Commit idempotently; return None for conflicting content."""
        with self._lock:
            if session_id not in self._sessions:
                raise KeyError(session_id)
            prior = self._messages[session_id].get(payload.message_id)
            if prior is not None:
                return prior if prior.content == payload.content else None
            message = QaMessage(
                id=payload.message_id,
                session_id=session_id,
                content=payload.content,
            )
            self._messages[session_id][payload.message_id] = message
            session = self._sessions[session_id]
            self._sessions[session_id] = session.model_copy(
                update={"message_count": session.message_count + 1}
            )
            return message

    def admit(self, session_id: str) -> Literal["ok", "session_conflict", "capacity"]:
        """Admit one bounded stream without waiting."""
        with self._lock:
            if session_id in self._active_sessions:
                return "session_conflict"
            if len(self._active_sessions) >= self.workload.concurrent_streams:
                return "capacity"
            self._active_sessions.add(session_id)
            self._cancelled_sessions.discard(session_id)
            return "ok"

    def cancel(self, session_id: str) -> bool:
        """Mark an existing session cancelled."""
        with self._lock:
            if session_id not in self._sessions:
                return False
            self._cancelled_sessions.add(session_id)
            return True

    def cancelled(self, session_id: str) -> bool:
        """Return whether a stream received cancellation."""
        with self._lock:
            return session_id in self._cancelled_sessions

    def release(self, session_id: str) -> None:
        """Release a stream admission slot."""
        with self._lock:
            self._active_sessions.discard(session_id)

    def metrics(self) -> ChatMetrics:
        """Return redacted stream admission state."""
        with self._lock:
            return ChatMetrics(
                active_streams=len(self._active_sessions),
                max_streams=self.workload.concurrent_streams,
                engine=self.workload.chat_engine,
            )


def _sse(event: str, payload: dict[str, bool | int | str | list[str]]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, separators=(',', ':'))}\n\n"


async def _fake_graph_stream(
    chat: QaChatState,
    payload: MessageSend,
    *,
    deadline_ms: int | None = None,
) -> AsyncIterator[str]:
    try:
        response_id = f"qa-response-{uuid.uuid5(_NAMESPACE, payload.message_id).hex[:12]}"
        yield _sse(
            "start",
            {"protocol": "1", "message_id": response_id, "session_id": payload.session_id},
        )
        yield _sse("progress", {"stage": "retrieving"})
        if deadline_ms is None:
            await anyio.sleep(chat.workload.stream_hold_ms / 1000)
        else:
            with anyio.move_on_after(deadline_ms / 1000) as deadline_scope:
                await anyio.sleep(chat.workload.stream_hold_ms / 1000)
            if deadline_scope.cancelled_caught:
                yield _sse(
                    "error",
                    {
                        "code": "deadline_exceeded",
                        "message": "Server deadline exceeded.",
                        "retryable": True,
                    },
                )
                return
        if chat.cancelled(payload.session_id):
            yield _sse("error", {"code": "cancelled", "message": "Cancelled.", "retryable": False})
            return
        yield _sse("token", {"token": "Deterministic QA response.", "index": 0, "message_id": response_id})
        yield _sse("progress", {"stage": "complete"})
        yield _sse(
            "done",
            {
                "done": True,
                "message_id": response_id,
                "full_response": "Deterministic QA response.",
                "citations": [],
                "generated_from": "deterministic-fake-graph",
            },
        )
    finally:
        chat.release(payload.session_id)


def _admit_or_raise(chat: QaChatState, session_id: str) -> None:
    admission = chat.admit(session_id)
    match admission:
        case "session_conflict":
            raise HTTPException(
                status_code=409,
                detail="Session already has an active stream.",
            )
        case "capacity":
            raise HTTPException(
                status_code=503,
                detail="Stream capacity reached.",
                headers={"Retry-After": "1"},
            )
        case "ok":
            return
        case unreachable:
            assert_never(unreachable)


def register_chat(app: FastAPI, workload: WorkloadProfile) -> None:
    """Register the credential-free chat and bounded-failure QA surface."""
    chat = QaChatState(workload)

    @app.get("/__qa/chat-metrics")
    async def chat_metrics() -> ChatMetrics:
        return chat.metrics()

    @app.post("/api/chat/sessions", status_code=201)
    async def create_session(payload: SessionRequest) -> QaSession:
        return chat.create_session(payload.title)

    @app.get("/api/chat/sessions", response_model=None)
    async def list_sessions() -> tuple[QaSession, ...] | JSONResponse:
        sessions = chat.list_sessions()
        if sessions is None:
            return JSONResponse(
                {"detail": "Rate limit exceeded."},
                status_code=429,
                headers={"Retry-After": "1"},
            )
        return sessions

    @app.post("/api/chat/sessions/{session_id}/messages", status_code=201)
    async def commit_message(session_id: str, payload: MessageCommit) -> QaMessage:
        try:
            message = chat.commit(session_id, payload)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Session was not found.") from error
        if message is None:
            raise HTTPException(status_code=409, detail="Message id conflicts.")
        return message

    @app.post("/api/chat/send")
    async def send_message(payload: MessageSend) -> StreamingResponse:
        _admit_or_raise(chat, payload.session_id)
        return StreamingResponse(
            _fake_graph_stream(chat, payload),
            media_type="text/event-stream",
            headers={"X-Stream-Protocol": "1", "X-QA-Graph": workload.chat_engine},
        )

    @app.post("/__qa/chat/deadline")
    async def deadline_stream(payload: MessageSend) -> StreamingResponse:
        _admit_or_raise(chat, payload.session_id)
        return StreamingResponse(
            _fake_graph_stream(
                chat,
                payload,
                deadline_ms=workload.server_deadline_ms,
            ),
            media_type="text/event-stream",
            headers={"X-QA-Deadline-Ms": str(workload.server_deadline_ms)},
        )

    @app.post("/api/chat/sessions/{session_id}/cancel")
    async def cancel_stream(session_id: str) -> CancelResponse:
        if not chat.cancel(session_id):
            raise HTTPException(status_code=404, detail="Session was not found.")
        return CancelResponse()
