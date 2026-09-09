"""Authenticated Personal Chat HTTP and streaming boundary."""

from __future__ import annotations

from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Final

import anyio
from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from src.api.chat_stream import (
    STREAM_PROTOCOL_VERSION,
    STREAM_RETRY_AFTER_SECONDS,
    sse_event,
)
from src.api.personal_chat_jobs import (
    PersonalChatJobAuthority,
    PersonalChatJobCapacityError,
    PersonalChatJobConflictError,
    PersonalChatJobNotFoundError,
    PersonalChatJobRegistry,
)
from src.api.personal_chat_state import (
    CitationPayload,
    PersonalChatConflictError,
    PersonalChatMessage,
    PersonalChatNotFoundError,
    PersonalChatResult,
    PersonalChatSession,
    PersonalChatStateStore,
    PersonalChatStorageError,
    PreparedPersonalTurn,
)
from src.api.personal_citations import project_safe_citations
from src.api.personal_lab_registry import PersonalLabRouteDependencies
from src.api.personal_lab_scope import PersonalLabScope
from src.graph.personal_lab_execution import run_personal_lab_graph
from src.graph.session import SessionPersistenceError, delete_session
from src.vector_store.models import JsonValue

_STREAM_BUFFER_BYTES: Final = 2 * 1024 * 1024
type PersonalChatExecute = Callable[
    [PersonalLabScope, str, str], Awaitable[PersonalChatResult]
]


class PersonalSessionCreate(BaseModel):
    model_config = ConfigDict(frozen=True)
    title: str | None = Field(default=None, max_length=200)


class PersonalSessionRename(BaseModel):
    model_config = ConfigDict(frozen=True)
    title: str = Field(min_length=1, max_length=200)


class PersonalMessageSend(BaseModel):
    model_config = ConfigDict(frozen=True)
    session_id: str = Field(min_length=1, max_length=100)
    message_id: str = Field(min_length=1, max_length=100)
    content: str = Field(min_length=1, max_length=10_000)


class PersonalMessageCommit(BaseModel):
    model_config = ConfigDict(frozen=True)
    message_id: str = Field(min_length=1, max_length=100)
    content: str = Field(min_length=1, max_length=10_000)


class PersonalFeedbackSubmit(BaseModel):
    model_config = ConfigDict(frozen=True)
    session_id: str = Field(min_length=1, max_length=100)
    message_id: str = Field(min_length=1, max_length=100)
    feedback: str = Field(pattern="^(like|dislike)$")
    reason: str | None = Field(default=None, max_length=1000)


class PersonalChatSessionResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: str
    title: str
    created_at: str
    message_count: int


class PersonalChatMessageResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    role: str
    content: str
    created_at: str
    in_reply_to: str | None
    generated_from: str | None
    citations: list[CitationPayload]


@dataclass(frozen=True, slots=True)
class _PersonalChatSendHandlers:
    dependencies: PersonalLabRouteDependencies
    state: PersonalChatStateStore
    jobs: PersonalChatJobAuthority
    execute: PersonalChatExecute

    async def list_sessions(
        self, request: Request
    ) -> list[PersonalChatSessionResponse]:
        scope = await _scope(request, self.dependencies)
        sessions = await _state_call(self.state.list_sessions, scope)
        return [_session_response(item) for item in sessions]

    async def create_session(
        self, request: Request, body: PersonalSessionCreate | None = None
    ) -> PersonalChatSessionResponse:
        scope = await _scope(request, self.dependencies)
        title = body.title if body and body.title else "New Session"
        created = await _state_call(self.state.create_session, scope, title)
        return _session_response(created)

    async def send(
        self, request: Request, body: PersonalMessageSend
    ) -> StreamingResponse:
        scope = await _scope(request, self.dependencies)
        prepared = await self._prepare_turn(scope, body)
        if prepared.completed is not None:
            return _stream(_completed_replay(body.session_id, prepared.completed))
        subscription = await self._start_job(scope, body, prepared)
        return _stream(subscription)

    async def _prepare_turn(
        self, scope: PersonalLabScope, body: PersonalMessageSend
    ) -> PreparedPersonalTurn:
        try:
            return await _state_call(
                self.state.prepare_turn,
                scope,
                body.session_id,
                body.message_id,
                body.content,
            )
        except PersonalChatNotFoundError:
            raise _not_found() from None
        except PersonalChatConflictError:
            raise _conflict() from None

    async def _produce_response(
        self,
        scope: PersonalLabScope,
        body: PersonalMessageSend,
        publish: Callable[[str], Awaitable[None]],
    ) -> None:
        await publish(
            sse_event(
                "start",
                {
                    "protocol": STREAM_PROTOCOL_VERSION,
                    "session_id": body.session_id,
                },
            )
        )
        result = await self.execute(scope, body.content, body.session_id)
        safe_result = PersonalChatResult(
            answer=result.answer,
            generated_from=result.generated_from,
            citations=project_safe_citations(result.citations),
        )
        saved = await _state_call(
            self.state.complete_turn,
            scope,
            body.session_id,
            body.message_id,
            safe_result,
        )
        await publish(sse_event("progress", {"stage": "complete"}))
        await publish(sse_event("done", _done_payload(saved, completed=False)))

    async def _start_job(
        self,
        scope: PersonalLabScope,
        body: PersonalMessageSend,
        prepared: PreparedPersonalTurn,
    ) -> AsyncGenerator[str]:
        async def produce(publish: Callable[[str], Awaitable[None]]) -> None:
            await self._produce_response(scope, body, publish)

        try:
            return await self.jobs.start(
                scope.id,
                body.session_id,
                produce,
                buffer_max_bytes=_STREAM_BUFFER_BYTES,
            )
        except PersonalChatJobConflictError:
            if prepared.created:
                await _state_call(
                    self.state.discard_pending_turn,
                    scope,
                    body.session_id,
                    body.message_id,
                )
            raise _conflict() from None
        except PersonalChatJobCapacityError:
            if prepared.created:
                await _state_call(
                    self.state.discard_pending_turn,
                    scope,
                    body.session_id,
                    body.message_id,
                )
            raise HTTPException(
                status_code=503,
                detail="Chat capacity is temporarily exhausted.",
                headers={"Retry-After": str(STREAM_RETRY_AFTER_SECONDS)},
            ) from None


class _PersonalChatHandlers(_PersonalChatSendHandlers):
    async def feedback(
        self, request: Request, body: PersonalFeedbackSubmit
    ) -> dict[str, str]:
        scope = await _scope(request, self.dependencies)
        try:
            feedback_id = await _state_call(
                self.state.save_feedback,
                scope,
                body.session_id,
                body.message_id,
                body.feedback,
                body.reason,
            )
        except PersonalChatNotFoundError:
            raise _not_found() from None
        return {"status": "saved", "feedback": body.feedback, "id": feedback_id}

    async def commit_message(
        self, request: Request, session_id: str, body: PersonalMessageCommit
    ) -> PersonalChatMessageResponse:
        scope = await _scope(request, self.dependencies)
        try:
            prepared = await _state_call(
                self.state.prepare_turn,
                scope,
                session_id,
                body.message_id,
                body.content,
            )
        except PersonalChatNotFoundError:
            raise _not_found() from None
        except PersonalChatConflictError:
            raise _conflict() from None
        return _message_response(prepared.user_message)

    async def reattach(self, request: Request, session_id: str) -> StreamingResponse:
        scope = await _scope(request, self.dependencies)
        await _require_session(self.state, scope, session_id)
        try:
            subscription = await self.jobs.subscribe(scope.id, session_id)
        except PersonalChatJobNotFoundError:
            raise HTTPException(
                status_code=404,
                detail="No active response. Reload session messages.",
            ) from None
        return _stream(subscription)

    async def cancel(self, request: Request, session_id: str) -> dict[str, str]:
        scope = await _scope(request, self.dependencies)
        await _require_session(self.state, scope, session_id)
        stopped = await self.jobs.cancel_and_wait(scope.id, session_id)
        return {"status": "stopped" if stopped else "idle", "session_id": session_id}

    async def delete(self, request: Request, session_id: str) -> dict[str, str]:
        scope = await _scope(request, self.dependencies)
        await _require_session(self.state, scope, session_id)
        await self.jobs.cancel_and_wait(scope.id, session_id)
        await _delete_checkpoint(scope, session_id)
        await _state_call(self.state.delete_session, scope, session_id)
        return {"status": "deleted", "session_id": session_id}

    async def rename(
        self, request: Request, session_id: str, body: PersonalSessionRename
    ) -> PersonalChatSessionResponse:
        scope = await _scope(request, self.dependencies)
        await _require_session(self.state, scope, session_id)
        renamed = await _state_call(
            self.state.rename_session, scope, session_id, body.title
        )
        return _session_response(renamed)

    async def messages(
        self, request: Request, session_id: str
    ) -> list[PersonalChatMessageResponse]:
        scope = await _scope(request, self.dependencies)
        try:
            messages = await _state_call(self.state.messages, scope, session_id)
        except PersonalChatNotFoundError:
            raise _not_found() from None
        return [_message_response(message) for message in messages]

    async def clear_messages(self, request: Request, session_id: str) -> dict[str, str]:
        scope = await _scope(request, self.dependencies)
        await _require_session(self.state, scope, session_id)
        await self.jobs.cancel_and_wait(scope.id, session_id)
        await _delete_checkpoint(scope, session_id)
        await _state_call(self.state.clear_messages, scope, session_id)
        return {"status": "cleared", "session_id": session_id}


def create_personal_chat_router(
    dependencies: PersonalLabRouteDependencies,
    *,
    state_store: PersonalChatStateStore | None = None,
    jobs: PersonalChatJobAuthority | None = None,
    execute: PersonalChatExecute | None = None,
) -> APIRouter:
    """Create scoped Personal Chat routes from trusted server authorities."""
    selected_jobs = jobs or PersonalChatJobRegistry()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        await selected_jobs.shutdown()

    router = APIRouter(
        prefix="/api/personal/chat",
        tags=["personal-chat"],
        lifespan=lifespan,
    )
    handlers = _PersonalChatHandlers(
        dependencies,
        state_store or PersonalChatStateStore(),
        selected_jobs,
        execute or _execute_graph,
    )
    for path, endpoint, method in (
        ("/send", handlers.send, "POST"),
        ("/sessions", handlers.list_sessions, "GET"),
        ("/sessions/{session_id}/stream", handlers.reattach, "GET"),
        ("/sessions/{session_id}/cancel", handlers.cancel, "POST"),
        ("/sessions/{session_id}", handlers.delete, "DELETE"),
        ("/sessions/{session_id}", handlers.rename, "PATCH"),
        ("/sessions/{session_id}/messages", handlers.messages, "GET"),
        ("/sessions/{session_id}/messages", handlers.clear_messages, "DELETE"),
    ):
        router.add_api_route(path, endpoint, methods=[method])
    for post_path, post_endpoint in (
        ("/feedback", handlers.feedback),
        ("/sessions", handlers.create_session),
        ("/sessions/{session_id}/messages", handlers.commit_message),
    ):
        router.add_api_route(
            post_path, post_endpoint, methods=["POST"], status_code=201
        )
    return router


async def _scope(
    request: Request, dependencies: PersonalLabRouteDependencies
) -> PersonalLabScope:
    if request.headers.get("X-API-Key"):
        raise HTTPException(
            status_code=400, detail="Browser API key headers are not accepted."
        )
    trusted = await dependencies.auth_context.resolve(request, require_workspace=False)
    return await dependencies.scopes.resolve(trusted.claims.user_id)


async def _execute_graph(
    scope: PersonalLabScope, query: str, session_id: str
) -> PersonalChatResult:
    result = await run_personal_lab_graph(scope, query=query, session_id=session_id)
    raw_docs = result.get("retrieved_docs", [])
    citations = (
        tuple(item for item in raw_docs if isinstance(item, Mapping))
        if isinstance(raw_docs, list)
        else ()
    )
    return PersonalChatResult(
        answer=str(result.get("final_answer", "")),
        generated_from=str(result.get("generated_from", "")),
        citations=citations,
    )


async def _state_call[**P, T](
    function: Callable[P, T], *args: P.args, **kwargs: P.kwargs
) -> T:
    try:
        if kwargs:
            return await anyio.to_thread.run_sync(lambda: function(*args, **kwargs))
        return await anyio.to_thread.run_sync(function, *args)
    except PersonalChatStorageError:
        raise HTTPException(
            status_code=503, detail="Personal Chat is unavailable."
        ) from None


async def _require_session(
    state: PersonalChatStateStore, scope: PersonalLabScope, session_id: str
) -> None:
    try:
        await _state_call(state.require_session, scope, session_id)
    except PersonalChatNotFoundError:
        raise _not_found() from None


async def _delete_checkpoint(scope: PersonalLabScope, session_id: str) -> None:
    try:
        await delete_session(
            session_id,
            db_path=str(scope.data_root / "checkpoints.sqlite"),
        )
    except SessionPersistenceError:
        raise HTTPException(
            status_code=503, detail="Personal Chat is unavailable."
        ) from None


def _completed_replay(
    session_id: str, message: PersonalChatMessage
) -> AsyncGenerator[str]:
    async def replay() -> AsyncGenerator[str]:
        yield sse_event(
            "start",
            {"protocol": STREAM_PROTOCOL_VERSION, "session_id": session_id},
        )
        yield sse_event("progress", {"stage": "complete"})
        yield sse_event("done", _done_payload(message, completed=True))

    return replay()


def _done_payload(
    message: PersonalChatMessage, *, completed: bool
) -> dict[str, JsonValue]:
    return {
        "done": True,
        "completed": completed,
        "message_id": message.id,
        "full_response": message.content,
        "citations": list(message.citations),
        "generated_from": message.generated_from or "",
    }


def _stream(events: AsyncGenerator[str]) -> StreamingResponse:
    return StreamingResponse(
        events,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "X-Stream-Protocol": STREAM_PROTOCOL_VERSION,
        },
    )


def _session_response(session: PersonalChatSession) -> PersonalChatSessionResponse:
    return PersonalChatSessionResponse(
        id=session.id,
        title=session.title,
        created_at=session.created_at,
        message_count=session.message_count,
    )


def _message_response(message: PersonalChatMessage) -> PersonalChatMessageResponse:
    return PersonalChatMessageResponse(
        id=message.id,
        role=message.role,
        content=message.content,
        created_at=message.created_at,
        in_reply_to=message.in_reply_to,
        generated_from=message.generated_from,
        citations=list(message.citations),
    )


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="Session or message not found.")


def _conflict() -> HTTPException:
    return HTTPException(
        status_code=409,
        detail="Message id conflicts with existing content or a live response.",
    )
