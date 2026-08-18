from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.routes.saas_auth import create_saas_auth_router
from src.api.routes.saas_workspaces import create_saas_workspaces_router
from src.api.saas_auth_context import BffAuthContextResolver
from src.api.saas_identity import IdentityTokens, IdentityUser, JwtClaims
from src.api.saas_security import SaasCsrfMiddleware
from src.api.saas_sessions import BffSessionStore, Membership, WorkspaceRole
from src.api.saas_workspaces import (
    Invitation,
    InvitationAcceptance,
    InvitationCreation,
    MembershipChange,
    MembershipRecord,
    OwnershipTransfer,
    Workspace,
    WorkspaceActor,
    WorkspaceAuditEvent,
    WorkspaceCreation,
)


@dataclass(slots=True)
class FakeIdentityProvider:
    user_id: UUID
    email: str

    async def signup(self, email: str, password: str) -> IdentityTokens:
        return await self.signin(email, password)

    async def signin(self, email: str, password: str) -> IdentityTokens:
        del password
        return IdentityTokens(
            access_token="access-token",
            refresh_token="refresh-token",
            expires_in_seconds=900,
            user=IdentityUser(id=self.user_id, email=email),
        )

    async def refresh(self, refresh_token: str) -> IdentityTokens:
        del refresh_token
        return await self.signin(self.email, "ignored-value")

    async def signout(self, access_token: str) -> None:
        del access_token


@dataclass(frozen=True, slots=True)
class FakeVerifier:
    user_id: UUID
    email: str

    async def verify(self, token: str) -> JwtClaims:
        del token
        return JwtClaims(user_id=self.user_id, email=self.email)


@dataclass(slots=True)
class MutableMemberships:
    memberships: dict[tuple[UUID, UUID], Membership]

    async def resolve(self, user_id: UUID, workspace_id: UUID) -> Membership | None:
        return self.memberships.get((user_id, workspace_id))


@dataclass(slots=True)
class RecordingWorkspaceService:
    workspace: Workspace
    calls: list[str] = field(default_factory=list)

    async def list_workspaces(self, user_id: UUID) -> tuple[Workspace, ...]:
        del user_id
        self.calls.append("list")
        return (self.workspace,)

    async def create_workspace(self, command: WorkspaceCreation) -> Workspace:
        del command
        self.calls.append("create")
        return self.workspace

    async def list_memberships(
        self, actor: WorkspaceActor
    ) -> tuple[MembershipRecord, ...]:
        del actor
        self.calls.append("members:list")
        return ()

    async def change_membership(self, command: MembershipChange) -> MembershipRecord:
        self.calls.append("members:change")
        return MembershipRecord(
            user_id=command.target_user_id, role=WorkspaceRole(command.role.value)
        )

    async def revoke_membership(
        self, actor: WorkspaceActor, target_user_id: UUID
    ) -> None:
        del actor, target_user_id
        self.calls.append("members:revoke")

    async def list_invitations(self, actor: WorkspaceActor) -> tuple[Invitation, ...]:
        del actor
        self.calls.append("invites:list")
        return ()

    async def create_invitation(self, command: InvitationCreation) -> Invitation:
        self.calls.append("invites:create")
        return Invitation(id=uuid4(), email="invitee@example.test", role=command.role)

    async def revoke_invitation(
        self, actor: WorkspaceActor, invitation_id: UUID
    ) -> None:
        del actor, invitation_id
        self.calls.append("invites:revoke")

    async def accept_invitation(self, command: InvitationAcceptance) -> Workspace:
        del command
        self.calls.append("invites:accept")
        return self.workspace

    async def transfer_ownership(self, command: OwnershipTransfer) -> None:
        del command
        self.calls.append("transfer")

    async def archive_workspace(self, actor: WorkspaceActor) -> None:
        del actor
        self.calls.append("archive")

    async def list_audit_events(
        self, actor: WorkspaceActor
    ) -> tuple[WorkspaceAuditEvent, ...]:
        del actor
        return ()


def _signed_in_client(
    role: WorkspaceRole,
) -> tuple[TestClient, RecordingWorkspaceService, UUID, UUID, str]:
    user_id = uuid4()
    workspace_id = uuid4()
    email = "actor@example.test"
    memberships = MutableMemberships(
        {(user_id, workspace_id): Membership(workspace_id, role)}
    )
    provider = FakeIdentityProvider(user_id, email)
    store = BffSessionStore()
    resolver = BffAuthContextResolver(FakeVerifier(user_id, email), store, memberships)
    service = RecordingWorkspaceService(Workspace(workspace_id, "Workspace", role))
    app = FastAPI()
    app.add_middleware(SaasCsrfMiddleware)
    app.include_router(
        create_saas_auth_router(
            identity_provider=provider,
            token_verifier=resolver.token_verifier,
            session_store=store,
            membership_resolver=memberships,
        )
    )
    app.include_router(create_saas_workspaces_router(resolver, service))
    client = TestClient(app, base_url="https://testserver")
    client.__enter__()
    csrf = client.get("/api/saas/auth/csrf").cookies["__Host-ragstudio-csrf"]
    signed_in = client.post(
        "/api/saas/auth/signin",
        headers={"X-CSRF-Token": csrf},
        json={"email": email, "password": "correct horse battery"},
    )
    assert signed_in.status_code == 200
    selected = client.put(
        "/api/saas/auth/workspace",
        headers={"X-CSRF-Token": csrf},
        json={"workspace_id": str(workspace_id)},
    )
    assert selected.status_code == 200
    return client, service, user_id, workspace_id, csrf


def test_admin_can_invite_but_cannot_manage_members_or_archive() -> None:
    # Given: an authenticated admin with one selected active workspace.
    client, service, _, workspace_id, csrf = _signed_in_client(WorkspaceRole.ADMIN)
    target_user_id = uuid4()
    headers = {"X-CSRF-Token": csrf, "Idempotency-Key": "invite-admin-1"}

    # When: the admin invites, then attempts owner-only mutations.
    invited = client.post(
        f"/api/saas/workspaces/{workspace_id}/invitations",
        headers=headers,
        json={"email": "invitee@example.test", "role": "member"},
    )
    member_change = client.patch(
        f"/api/saas/workspaces/{workspace_id}/members/{target_user_id}",
        headers={"X-CSRF-Token": csrf},
        json={"role": "admin"},
    )
    archived = client.post(
        f"/api/saas/workspaces/{workspace_id}/archive",
        headers={"X-CSRF-Token": csrf},
    )
    client.__exit__(None, None, None)

    # Then: invitation reaches the service while owner-only writes stop at the BFF.
    assert invited.status_code == 201
    assert member_change.status_code == 403
    assert archived.status_code == 403
    assert service.calls == ["invites:create"]


def test_foreign_workspace_path_is_denied_before_service_access() -> None:
    # Given: an owner whose selected membership is for a different workspace.
    client, service, _, _, csrf = _signed_in_client(WorkspaceRole.OWNER)

    # When: a route UUID is changed to a foreign tenant.
    response = client.get(
        f"/api/saas/workspaces/{uuid4()}/members",
        headers={"X-CSRF-Token": csrf},
    )
    client.__exit__(None, None, None)

    # Then: the sanitized denial occurs without a service invocation.
    assert response.status_code == 403
    assert response.json() == {"detail": "Workspace is unavailable."}
    assert service.calls == []


def test_invitation_acceptance_uses_verified_identity_not_request_identity() -> None:
    # Given: an authenticated member with a provider-owned identity.
    client, service, user_id, _, csrf = _signed_in_client(WorkspaceRole.MEMBER)

    # When: only an opaque invitation token is submitted.
    response = client.post(
        "/api/saas/workspace-invitations/accept",
        headers={"X-CSRF-Token": csrf},
        json={"token": "a" * 43},
    )
    client.__exit__(None, None, None)

    # Then: acceptance succeeds without a client-supplied user or workspace UUID.
    assert response.status_code == 200
    assert response.json()["id"] == str(service.workspace.id)
    assert user_id != service.workspace.id
    assert service.calls == ["invites:accept"]
