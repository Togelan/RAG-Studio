"""Exact-origin HTTP proof and admission boundary for the MVP public widget."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final
from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from src.api.mvp_public_admission import (
    AdmissionDenial,
    PublicAdmissionAuthority,
    PublicAdmissionRejected,
    PublicAdmissionStoreUnavailableError,
)

_ALLOW_METHODS: Final = "POST, OPTIONS"
_ALLOW_HEADERS: Final = "Content-Type"


class _ProofRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class _AdmissionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    proof: str = Field(min_length=1, max_length=2048)
    message: str = Field(min_length=1, max_length=4000)


class PublicProofResponse(BaseModel):
    """Anonymous proof response without durable or private session authority."""

    model_config = ConfigDict(frozen=True)

    proof: str
    session_id: UUID
    expires_at: datetime


class PublicAdmissionResponse(BaseModel):
    """Reserved public execution identifiers for the later stream adapter."""

    model_config = ConfigDict(frozen=True)

    session_id: UUID
    reservation_id: UUID


@dataclass(frozen=True, slots=True)
class _Handlers:
    authority: PublicAdmissionAuthority
    clock: Callable[[], datetime]

    async def preflight(self, public_key: UUID, request: Request) -> Response:
        origin = request.headers.get("origin")
        if request.headers.get("access-control-request-method") != "POST":
            return public_rejection(403)
        requested_headers = request.headers.get("access-control-request-headers", "")
        if requested_headers.strip().lower() not in ("", "content-type"):
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
            status_code=204, headers=public_cors_headers(origin, preflight=True)
        )

    async def proof(self, public_key: UUID, request: Request) -> Response:
        origin = request.headers.get("origin")
        if not _valid_body(_ProofRequest, await request.body(), empty_allowed=True):
            return public_rejection(422)
        try:
            issued = await self.authority.issue(public_key, origin, self.clock())
        except PublicAdmissionRejected as rejected:
            return public_rejection(
                public_rejection_status(rejected),
                rejected.retry_after,
                rejected.cors_origin,
            )
        except PublicAdmissionStoreUnavailableError as unavailable:
            return public_rejection(503, cors_origin=unavailable.cors_origin)
        payload = PublicProofResponse(
            proof=issued.proof,
            session_id=issued.session_id,
            expires_at=issued.expires_at,
        )
        return JSONResponse(
            payload.model_dump(mode="json"), headers=public_cors_headers(origin)
        )

    async def admit(self, public_key: UUID, request: Request) -> Response:
        origin = request.headers.get("origin")
        try:
            payload = _AdmissionRequest.model_validate_json(await request.body())
        except ValidationError:
            return public_rejection(422)
        client_ip = request.client.host if request.client is not None else "unknown"
        try:
            admitted = await self.authority.admit(
                public_key, origin, payload.proof, client_ip, self.clock()
            )
        except PublicAdmissionRejected as rejected:
            retry_after = rejected.retry_after
            if rejected.reason is AdmissionDenial.QUOTA_EXHAUSTED:
                retry_after = _quota_retry_after(self.clock())
            return public_rejection(
                public_rejection_status(rejected), retry_after, rejected.cors_origin
            )
        except PublicAdmissionStoreUnavailableError as unavailable:
            return public_rejection(503, cors_origin=unavailable.cors_origin)
        response = PublicAdmissionResponse(
            session_id=admitted.session_id,
            reservation_id=admitted.reservation_id,
        )
        return JSONResponse(
            response.model_dump(mode="json"),
            status_code=201,
            headers=public_cors_headers(origin),
        )


def create_mvp_public_router(
    authority: PublicAdmissionAuthority,
    *,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> APIRouter:
    """Create public proof/preflight/admission endpoints with exact CORS."""
    handlers = _Handlers(authority, clock)
    router = APIRouter(prefix="/api/public/widgets", tags=["public-widget"])
    router.add_api_route("/{public_key}/proof", handlers.preflight, methods=["OPTIONS"])
    router.add_api_route(
        "/{public_key}/admissions", handlers.preflight, methods=["OPTIONS"]
    )
    router.add_api_route("/{public_key}/proof", handlers.proof, methods=["POST"])
    router.add_api_route("/{public_key}/admissions", handlers.admit, methods=["POST"])
    return router


def _valid_body(
    model: type[BaseModel], body: bytes, *, empty_allowed: bool = False
) -> bool:
    try:
        model.model_validate_json(body or (b"{}" if empty_allowed else body))
    except ValidationError:
        return False
    return True


def public_cors_headers(
    origin: str | None, *, preflight: bool = False
) -> dict[str, str]:
    """Return exact-origin public response headers after authorization."""
    if origin is None:
        return {}
    headers = {"Access-Control-Allow-Origin": origin, "Vary": "Origin"}
    if preflight:
        headers.update(
            {
                "Access-Control-Allow-Methods": _ALLOW_METHODS,
                "Access-Control-Allow-Headers": _ALLOW_HEADERS,
                "Access-Control-Max-Age": "600",
            }
        )
    return headers


def public_rejection_status(rejected: PublicAdmissionRejected) -> int:
    """Map sanitized admission outcomes to the public HTTP contract."""
    match rejected.reason:
        case AdmissionDenial.FEATURE_DISABLED | AdmissionDenial.NOT_FOUND:
            return 404
        case (
            AdmissionDenial.DISABLED
            | AdmissionDenial.REVOKED
            | AdmissionDenial.ORIGIN
            | AdmissionDenial.NOT_ENTITLED
            | AdmissionDenial.STALE_AUTHORITY
        ):
            return 403
        case AdmissionDenial.INVALID_PROOF | AdmissionDenial.REPLAYED_PROOF:
            return 401
        case AdmissionDenial.RATE_LIMITED | AdmissionDenial.QUOTA_EXHAUSTED:
            return 429
        case unreachable:
            from typing import assert_never

            assert_never(unreachable)


def public_rejection(
    status_code: int,
    retry_after: int | None = None,
    cors_origin: str | None = None,
) -> JSONResponse:
    """Return one detail-free public rejection with optional authorized CORS."""
    headers = public_cors_headers(cors_origin)
    if retry_after is not None:
        headers["Retry-After"] = str(retry_after)
    return JSONResponse(
        {"detail": "Public widget request rejected."},
        status_code=status_code,
        headers=headers or None,
    )


def _quota_retry_after(now: datetime) -> int:
    current = now.astimezone(UTC)
    year = current.year + (1 if current.month == 12 else 0)
    month = 1 if current.month == 12 else current.month + 1
    next_month = datetime(year, month, 1, tzinfo=UTC)
    return max(1, int((next_month - current).total_seconds()))
