from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from src.api.routes.saas_tenant_health import create_saas_tenant_health_router
from src.api.saas_auth_context import AuthContext
from src.api.saas_identity import JwtClaims
from src.api.saas_security import BffSessionHandle
from src.api.saas_sessions import BffSession, Membership, WorkspaceRole
from src.vector_store.workspace_collections import (
    CollectionAccessDeniedError,
    ProvisioningResult,
    WorkspaceCollectionClaim,
    WorkspaceCollectionState,
)


@dataclass(frozen=True, slots=True)
class FakeAuthResolver:
    context: AuthContext

    async def resolve(
        self, request: Request, *, require_workspace: bool
    ) -> AuthContext:
        del request, require_workspace
        return self.context


@dataclass(frozen=True, slots=True)
class StateRegistry:
    state_value: WorkspaceCollectionState

    async def claim(self, workspace_id: UUID) -> WorkspaceCollectionClaim:
        raise CollectionAccessDeniedError

    async def complete(self, workspace_id: UUID, result: ProvisioningResult) -> None:
        del workspace_id, result

    async def state(self, workspace_id: UUID) -> WorkspaceCollectionState:
        del workspace_id
        return self.state_value


def _auth_context(*, active: bool = True) -> AuthContext:
    user_id = uuid4()
    workspace_id = uuid4()
    session = BffSession(
        handle=BffSessionHandle("opaque-session"),
        user_id=user_id,
        email="owner@example.test",
        access_token="server-only-access",
        refresh_token="server-only-refresh",
        expires_at=99_999_999_999.0,
        active_workspace_id=workspace_id,
    )
    return AuthContext(
        session=session,
        claims=JwtClaims(user_id=user_id, email=session.email),
        membership=(Membership(workspace_id, WorkspaceRole.OWNER) if active else None),
    )


def _app(context: AuthContext, state: WorkspaceCollectionState) -> FastAPI:
    app = FastAPI()
    app.include_router(
        create_saas_tenant_health_router(
            auth_context_resolver=FakeAuthResolver(context),
            registry=StateRegistry(state),
        )
    )
    return app


def test_tenant_health_distinguishes_ready_provisioning_and_failed() -> None:
    # Given: the same authorized workspace at each durable lifecycle class.
    context = _auth_context()

    # When: the protected readiness endpoint observes each class.
    ready = TestClient(_app(context, WorkspaceCollectionState.READY)).get(
        "/api/saas/tenant-storage/readiness"
    )
    pending = TestClient(_app(context, WorkspaceCollectionState.PENDING)).get(
        "/api/saas/tenant-storage/readiness"
    )
    provisioning = TestClient(_app(context, WorkspaceCollectionState.PROVISIONING)).get(
        "/api/saas/tenant-storage/readiness"
    )
    failed = TestClient(_app(context, WorkspaceCollectionState.FAILED)).get(
        "/api/saas/tenant-storage/readiness"
    )

    # Then: public status distinguishes progress without a collection identifier.
    assert ready.json() == {"status": "ready"}
    assert pending.json() == {"status": "provisioning"}
    assert provisioning.json() == {"status": "provisioning"}
    assert failed.json() == {"status": "degraded"}
    combined = ready.text + pending.text + provisioning.text + failed.text
    assert "ws_" not in combined
    assert str(context.session.active_workspace_id) not in combined


def test_tenant_health_denies_stale_or_archived_workspace() -> None:
    # Given: a stale session without membership and an archived durable registry state.
    stale_context = _auth_context(active=False)
    active_context = _auth_context()

    # When: each caller probes the tenant storage boundary.
    stale = TestClient(_app(stale_context, WorkspaceCollectionState.READY)).get(
        "/api/saas/tenant-storage/readiness"
    )
    archived = TestClient(_app(active_context, WorkspaceCollectionState.ARCHIVED)).get(
        "/api/saas/tenant-storage/readiness"
    )

    # Then: both fail before any collection capability or identifier is returned.
    assert stale.status_code == 403
    assert archived.status_code == 403
    assert stale.json() == {"detail": "Workspace is unavailable."}
    assert archived.json() == {"detail": "Workspace is unavailable."}
    assert "ws_" not in stale.text + archived.text
