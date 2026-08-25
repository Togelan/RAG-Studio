"""Authenticated Personal Lab context route."""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict

from src.api.personal_lab_registry import PersonalLabRouteDependencies


class PersonalLabContextResponse(BaseModel):
    """Public opaque context identifier and non-authoritative namespace label."""

    model_config = ConfigDict(frozen=True)

    id: str
    namespace: str


def create_personal_lab_router(
    dependencies: PersonalLabRouteDependencies,
) -> APIRouter:
    """Create the Personal Lab root router from server-owned authorities."""
    router = APIRouter(prefix="/api/personal", tags=["personal-lab"])

    @router.get("/context", response_model=PersonalLabContextResponse)
    async def personal_lab_context(request: Request) -> PersonalLabContextResponse:
        trusted = await dependencies.auth_context.resolve(
            request, require_workspace=False
        )
        scope = await dependencies.scopes.resolve(trusted.claims.user_id)
        return PersonalLabContextResponse(id=str(scope.id), namespace=scope.namespace)

    return router
