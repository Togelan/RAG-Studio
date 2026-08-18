"""Protected SaaS tenant-storage readiness without collection disclosure."""

from __future__ import annotations

from enum import StrEnum
from typing import Protocol, assert_never

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict

from src.api.saas_auth_context import AuthContext
from src.api.saas_tenant_context import (
    WorkspaceContextUnavailableError,
    trusted_workspace_context,
)
from src.vector_store.workspace_collections import (
    CollectionAccessDeniedError,
    CollectionRegistryUnavailableError,
    WorkspaceCollectionRegistry,
    WorkspaceCollectionState,
)


class TenantStoragePublicState(StrEnum):
    """Public readiness classes that omit durable provider identifiers."""

    READY = "ready"
    PROVISIONING = "provisioning"
    DEGRADED = "degraded"


class TenantStorageStatus(BaseModel):
    """Sanitized tenant-storage readiness response."""

    model_config = ConfigDict(frozen=True)

    status: TenantStoragePublicState


class TenantAuthContextResolver(Protocol):
    """Resolve the BFF-owned identity and selected workspace for a request."""

    async def resolve(
        self, request: Request, *, require_workspace: bool
    ) -> AuthContext: ...


def create_saas_tenant_health_router(
    *,
    auth_context_resolver: TenantAuthContextResolver,
    registry: WorkspaceCollectionRegistry,
) -> APIRouter:
    """Build the protected tenant-storage readiness route."""
    router = APIRouter(prefix="/api/saas/tenant-storage", tags=["saas-storage"])

    @router.get("/readiness", response_model=TenantStorageStatus)
    async def tenant_storage_readiness(request: Request) -> TenantStorageStatus:
        auth_context = await auth_context_resolver.resolve(
            request, require_workspace=True
        )
        try:
            context = trusted_workspace_context(auth_context)
            state = await registry.state(context.workspace_id)
        except WorkspaceContextUnavailableError, CollectionAccessDeniedError:
            raise HTTPException(
                status_code=403, detail="Workspace is unavailable."
            ) from None
        except CollectionRegistryUnavailableError:
            raise HTTPException(
                status_code=503, detail="Workspace storage is unavailable."
            ) from None
        match state:
            case WorkspaceCollectionState.READY:
                public_state = TenantStoragePublicState.READY
            case (
                WorkspaceCollectionState.PENDING | WorkspaceCollectionState.PROVISIONING
            ):
                public_state = TenantStoragePublicState.PROVISIONING
            case WorkspaceCollectionState.FAILED:
                public_state = TenantStoragePublicState.DEGRADED
            case WorkspaceCollectionState.ARCHIVED:
                raise HTTPException(status_code=403, detail="Workspace is unavailable.")
            case unreachable:
                assert_never(unreachable)
        return TenantStorageStatus(status=public_state)

    return router
