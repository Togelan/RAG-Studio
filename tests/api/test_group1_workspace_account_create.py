from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import cast
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.routes.saas_workspaces import create_saas_workspaces_router
from src.api.saas_account_models import (
    AccountContext,
    AccountOwnerProjection,
    AccountStatus,
    SelectedAccountContext,
)
from src.api.saas_auth_context import AuthContext, BffAuthContextResolver
from src.api.saas_identity import JwtClaims
from src.api.saas_security import SESSION_COOKIE_NAME, BffSessionHandle
from src.api.saas_sessions import BffSession, WorkspaceRole
from src.api.saas_workspace_models import Workspace, WorkspaceCreation, WorkspaceService


@dataclass(slots=True)
class RecordingService:
    calls: list[WorkspaceCreation] = field(default_factory=list)

    async def create_workspace(self, command: WorkspaceCreation) -> Workspace:
        self.calls.append(command)
        return Workspace(uuid4(), command.name, WorkspaceRole.OWNER)


@dataclass(frozen=True, slots=True)
class FixedResolver:
    context: AuthContext

    async def resolve(self, request: object, *, require_workspace: bool) -> AuthContext:
        del request, require_workspace
        return self.context


def _context(selected: SelectedAccountContext | None) -> AuthContext:
    user_id = uuid4()
    session = BffSession(
        BffSessionHandle("opaque"),
        user_id,
        "owner@example.test",
        "access",
        "refresh",
        time.time() + 900,
        time.time() + 3600,
        active_account_id=selected.account.id if selected is not None else None,
    )
    return AuthContext(
        session,
        JwtClaims(user_id, "owner@example.test"),
        None,
        selected,
    )


def _client(context: AuthContext) -> tuple[TestClient, RecordingService]:
    service = RecordingService()
    app = FastAPI()
    app.include_router(
        create_saas_workspaces_router(
            cast(BffAuthContextResolver, FixedResolver(context)),
            cast(WorkspaceService, service),
        )
    )
    client = TestClient(app, base_url="https://testserver")
    client.cookies.set(SESSION_COOKIE_NAME, "opaque")
    return client, service


def test_workspace_create_threads_selected_owned_account() -> None:
    # Given: the server revalidated an explicitly selected owned Account.
    account_id = uuid4()
    selected = SelectedAccountContext(
        AccountContext(
            account_id,
            "Owner Account",
            AccountStatus.ACTIVE,
            AccountOwnerProjection(),
            (),
        ),
        None,
    )
    client, service = _client(_context(selected))

    # When: the owner creates a Workspace.
    with client:
        response = client.post(
            "/api/saas/workspaces",
            headers={"Idempotency-Key": "account-create-1"},
            json={"name": "Account Workspace"},
        )

    # Then: only the trusted server-selected Account reaches persistence.
    assert response.status_code == 201
    assert len(service.calls) == 1
    assert service.calls[0].account_id == account_id


def test_workspace_create_rejects_missing_account_before_service() -> None:
    # Given: an authenticated identity with no selected Account.
    client, service = _client(_context(None))

    # When: it attempts a Workspace mutation.
    with client:
        response = client.post(
            "/api/saas/workspaces",
            headers={"Idempotency-Key": "account-create-2"},
            json={"name": "Unscoped Workspace"},
        )

    # Then: the BFF denies before invoking persistence.
    assert response.status_code == 403
    assert service.calls == []


def test_workspace_create_rejects_foreign_account_before_service() -> None:
    # Given: a member selected an Account it does not own.
    selected = SelectedAccountContext(
        AccountContext(uuid4(), "Foreign Account", AccountStatus.ACTIVE, None, ()),
        None,
    )
    client, service = _client(_context(selected))

    # When: it attempts owner-level Workspace creation.
    with client:
        response = client.post(
            "/api/saas/workspaces",
            headers={"Idempotency-Key": "account-create-3"},
            json={"name": "Foreign Workspace"},
        )

    # Then: owner authority is denied before persistence.
    assert response.status_code == 403
    assert service.calls == []
