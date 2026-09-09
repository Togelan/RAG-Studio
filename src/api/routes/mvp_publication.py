"""Authenticated management routes for one Personal Lab publication."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol, assert_never
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from src.api.mvp_publication import Publication, PublicationConflictError
from src.api.mvp_publication_origin import OriginRejectedError
from src.api.mvp_publication_store import PublicationStoreUnavailableError
from src.api.personal_lab_registry import PersonalLabRouteDependencies


class PublicationStore(Protocol):
    """Durable lifecycle capability required by the authenticated route."""

    async def read(self, personal_lab_id: UUID) -> Publication | None: ...

    async def publish(self, personal_lab_id: UUID, raw_origin: str) -> Publication: ...

    async def disable(self, personal_lab_id: UUID) -> Publication | None: ...

    async def rotate(self, personal_lab_id: UUID) -> Publication | None: ...

    async def revoke(self, personal_lab_id: UUID) -> Publication | None: ...


class PublishRequest(BaseModel):
    """The only browser-controlled publication field."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    allowed_origin: str = Field(min_length=1, max_length=512)


class PublicationResponse(BaseModel):
    """Sanitized publication status without Personal Lab or collection scope."""

    model_config = ConfigDict(frozen=True)

    publication_id: UUID
    public_key: UUID
    allowed_origin: str
    state: str
    key_version: int
    audit_event_count: int


@dataclass(frozen=True, slots=True)
class _PublicationHandlers:
    dependencies: PersonalLabRouteDependencies
    store: PublicationStore

    async def read(self, request: Request) -> PublicationResponse:
        publication = await self._invoke(request, "read")
        return _response(publication)

    async def publish(
        self, payload: PublishRequest, request: Request
    ) -> PublicationResponse:
        publication = await self._invoke(request, "publish", payload.allowed_origin)
        return _response(publication)

    async def disable(self, request: Request) -> PublicationResponse:
        publication = await self._invoke(request, "disable")
        return _response(publication)

    async def rotate(self, request: Request) -> PublicationResponse:
        publication = await self._invoke(request, "rotate")
        return _response(publication)

    async def revoke(self, request: Request) -> PublicationResponse:
        publication = await self._invoke(request, "revoke")
        return _response(publication)

    async def _invoke(
        self,
        request: Request,
        operation: Literal["read", "publish", "disable", "rotate", "revoke"],
        raw_origin: str | None = None,
    ) -> Publication:
        trusted = await self.dependencies.auth_context.resolve(
            request, require_workspace=False
        )
        scope = await self.dependencies.scopes.resolve(trusted.claims.user_id)
        try:
            match operation:
                case "read":
                    result = await self.store.read(scope.id)
                case "publish":
                    if raw_origin is None:
                        raise AssertionError
                    result = await self.store.publish(scope.id, raw_origin)
                case "disable":
                    result = await self.store.disable(scope.id)
                case "rotate":
                    result = await self.store.rotate(scope.id)
                case "revoke":
                    result = await self.store.revoke(scope.id)
                case unreachable:
                    assert_never(unreachable)
        except OriginRejectedError:
            raise HTTPException(422, detail="Invalid publication origin.") from None
        except PublicationConflictError:
            raise HTTPException(409, detail="Publication state conflict.") from None
        except PublicationStoreUnavailableError:
            raise HTTPException(
                503, detail="Publication state is unavailable."
            ) from None
        if result is None:
            raise HTTPException(404, detail="Publication is not available.")
        return result


def create_mvp_publication_router(
    dependencies: PersonalLabRouteDependencies, store: PublicationStore
) -> APIRouter:
    """Create the authenticated publication lifecycle transport."""
    handlers = _PublicationHandlers(dependencies, store)
    router = APIRouter(prefix="/api/personal/widget-publication", tags=["publication"])
    router.add_api_route(
        "", handlers.read, methods=["GET"], response_model=PublicationResponse
    )
    router.add_api_route(
        "", handlers.publish, methods=["PUT"], response_model=PublicationResponse
    )
    router.add_api_route(
        "/disable",
        handlers.disable,
        methods=["POST"],
        response_model=PublicationResponse,
    )
    router.add_api_route(
        "/rotate", handlers.rotate, methods=["POST"], response_model=PublicationResponse
    )
    router.add_api_route(
        "", handlers.revoke, methods=["DELETE"], response_model=PublicationResponse
    )
    return router


def _response(publication: Publication) -> PublicationResponse:
    return PublicationResponse(
        publication_id=publication.id,
        public_key=publication.public_key,
        allowed_origin=str(publication.allowed_origin),
        state=publication.state.value,
        key_version=publication.key_version,
        audit_event_count=len(publication.audit),
    )
