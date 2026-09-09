"""Public widget SSE transport over verified admission and ephemeral RAG."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final, assert_never
from uuid import UUID

import anyio
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from src.api.chat_stream import STREAM_PROTOCOL_VERSION, sse_event
from src.api.mvp_public_admission import (
    PublicAdmissionAuthority,
    PublicAdmissionRejected,
    PublicAdmissionStoreUnavailableError,
)
from src.api.mvp_public_execution import (
    PublicExecutionScopeResolver,
    PublicExecutionScopeUnavailableError,
)
from src.api.personal_chat_state import project_safe_citation
from src.api.personal_lab_scope import PersonalLabScope
from src.api.public_stream_jobs import (
    PublicStreamCapacityError,
    PublicStreamConflictError,
    PublicStreamJobRegistry,
    PublicStreamKey,
    PublicStreamLease,
)
from src.api.routes.mvp_public import (
    public_cors_headers,
    public_rejection,
    public_rejection_status,
)
from src.graph.public_personal_lab_execution import (
    PublicGraphEvent,
    PublicResult,
    PublicToken,
    stream_public_personal_lab_graph,
)

_RETRY_AFTER: Final = 1
_ERROR_PAYLOAD: Final = {
    "code": "response_failed",
    "message": "Response could not be completed.",
    "retryable": True,
}
type PublicExecute = Callable[
    [PersonalLabScope, str, str], AsyncIterator[PublicGraphEvent]
]


class _StreamRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    proof: str = Field(min_length=1, max_length=2048)
    message: str = Field(min_length=1, max_length=4000)


class _CancelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    proof: str = Field(min_length=1, max_length=2048)


@dataclass(frozen=True, slots=True)
class _Handlers:
    authority: PublicAdmissionAuthority
    scopes: PublicExecutionScopeResolver
    jobs: PublicStreamJobRegistry
    execute: PublicExecute
    clock: Callable[[], datetime]

    async def preflight(self, public_key: UUID, request: Request) -> Response:
        origin = request.headers.get("origin")
        if request.headers.get("access-control-request-method") != "POST":
            return public_rejection(403)
        requested = request.headers.get("access-control-request-headers", "")
        if requested.strip().lower() not in ("", "content-type"):
            return public_rejection(403)
        try:
            await self.authority.issue(public_key, origin, self.clock())
        except PublicAdmissionRejected as rejected:
            return public_rejection(
                public_rejection_status(rejected),
                rejected.retry_after,
                rejected.cors_origin,
            )
        except PublicAdmissionStoreUnavailableError as unavailable:
            return public_rejection(503, cors_origin=unavailable.cors_origin)
        return Response(
            status_code=204,
            headers=public_cors_headers(origin, preflight=True),
        )

    async def cancel_preflight(
        self, public_key: UUID, session_id: UUID, request: Request
    ) -> Response:
        del session_id
        return await self.preflight(public_key, request)

    async def stream(self, public_key: UUID, request: Request) -> Response:
        origin = request.headers.get("origin")
        try:
            body = _StreamRequest.model_validate_json(await request.body())
        except ValidationError:
            return public_rejection(422)
        client_ip = request.client.host if request.client is not None else "unknown"
        try:
            admission = await self.authority.admit(
                public_key, origin, body.proof, client_ip, self.clock()
            )
        except PublicAdmissionRejected as rejected:
            return public_rejection(
                public_rejection_status(rejected),
                rejected.retry_after,
                rejected.cors_origin,
            )
        except PublicAdmissionStoreUnavailableError as unavailable:
            return public_rejection(503, cors_origin=unavailable.cors_origin)
        try:
            scope = await self.scopes.resolve(admission)
            key = PublicStreamKey(admission.publication_id, admission.session_id)
            lease = await self.jobs.acquire(key)
        except PublicExecutionScopeUnavailableError:
            await self.authority.release(admission.reservation_id)
            return public_rejection(503, cors_origin=origin)
        except PublicStreamConflictError:
            await self.authority.release(admission.reservation_id)
            return public_rejection(409, cors_origin=origin)
        except PublicStreamCapacityError:
            await self.authority.release(admission.reservation_id)
            return public_rejection(503, _RETRY_AFTER, origin)
        events = self._events(lease, scope, body.message, admission.reservation_id)
        return StreamingResponse(
            events,
            media_type="text/event-stream",
            headers={
                **public_cors_headers(origin),
                "Cache-Control": "no-store",
                "X-Accel-Buffering": "no",
                "X-Stream-Protocol": STREAM_PROTOCOL_VERSION,
            },
        )

    async def cancel(
        self, public_key: UUID, session_id: UUID, request: Request
    ) -> Response:
        origin = request.headers.get("origin")
        try:
            body = _CancelRequest.model_validate_json(await request.body())
        except ValidationError:
            return public_rejection(422)
        try:
            verified = await self.authority.verify(
                public_key, origin, body.proof, self.clock()
            )
        except PublicAdmissionRejected as rejected:
            return public_rejection(
                public_rejection_status(rejected),
                rejected.retry_after,
                rejected.cors_origin,
            )
        except PublicAdmissionStoreUnavailableError as unavailable:
            return public_rejection(503, cors_origin=unavailable.cors_origin)
        if verified.session_id != session_id:
            return public_rejection(404, cors_origin=origin)
        stopped = await self.jobs.cancel(
            PublicStreamKey(verified.publication_id, verified.session_id)
        )
        return JSONResponse(
            {"status": "stopped" if stopped else "idle"},
            headers=public_cors_headers(origin),
        )

    async def _events(
        self,
        lease: PublicStreamLease,
        scope: PersonalLabScope,
        message: str,
        reservation_id: UUID,
    ) -> AsyncIterator[str]:
        finalized = False
        try:
            yield sse_event("start", {"protocol": STREAM_PROTOCOL_VERSION})
            with lease.cancel_scope:
                async for event in self.execute(
                    scope, message, lease.key.graph_session_id
                ):
                    match event:
                        case PublicToken(value=token):
                            yield sse_event("token", {"token": token})
                        case PublicResult(citations=citations):
                            yield sse_event(
                                "citations",
                                {
                                    "citations": [
                                        project_safe_citation(item)
                                        for item in citations
                                    ]
                                },
                            )
                            if not await self.authority.commit(reservation_id):
                                raise PublicAdmissionStoreUnavailableError
                            finalized = True
                            yield sse_event("done", {"done": True})
                            return
                        case unreachable:
                            assert_never(unreachable)
            finalized = await self.authority.release(reservation_id)
            yield sse_event(
                "error",
                {
                    "code": "canceled",
                    "message": "Response was canceled.",
                    "retryable": True,
                },
            )
        except anyio.get_cancelled_exc_class():
            raise
        except Exception:  # noqa: BLE001  # noqa: BROAD_EXCEPT_OK -- public SSE boundary
            yield sse_event("error", _ERROR_PAYLOAD)
        finally:
            with anyio.CancelScope(shield=True):
                if not finalized:
                    await self.authority.release(reservation_id)
                await self.jobs.release(lease)


def create_mvp_public_stream_router(
    authority: PublicAdmissionAuthority,
    scopes: PublicExecutionScopeResolver,
    jobs: PublicStreamJobRegistry,
    *,
    execute: PublicExecute = stream_public_personal_lab_graph,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> APIRouter:
    """Create public streaming and cancellation routes over verified authority."""
    handlers = _Handlers(authority, scopes, jobs, execute, clock)
    router = APIRouter(prefix="/api/public/widgets", tags=["public-widget"])
    router.add_api_route(
        "/{public_key}/streams", handlers.preflight, methods=["OPTIONS"]
    )
    router.add_api_route("/{public_key}/streams", handlers.stream, methods=["POST"])
    router.add_api_route(
        "/{public_key}/streams/{session_id}/cancel",
        handlers.cancel_preflight,
        methods=["OPTIONS"],
    )
    router.add_api_route(
        "/{public_key}/streams/{session_id}/cancel",
        handlers.cancel,
        methods=["POST"],
    )
    return router
