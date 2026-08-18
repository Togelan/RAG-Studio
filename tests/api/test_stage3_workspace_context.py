from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.routes.saas_auth import create_saas_auth_router
from src.api.saas_identity import IdentityTokens, IdentityUser, JwtClaims
from src.api.saas_security import SaasCsrfMiddleware
from src.api.saas_sessions import BffSessionStore, Membership, WorkspaceRole


@dataclass(slots=True)
class FakeProvider:
    user_id: UUID

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
        return await self.signin("member@example.test", "ignored")

    async def signout(self, access_token: str) -> None:
        del access_token


@dataclass(frozen=True, slots=True)
class FakeVerifier:
    user_id: UUID

    async def verify(self, token: str) -> JwtClaims:
        del token
        return JwtClaims(user_id=self.user_id, email="member@example.test")


@dataclass(slots=True)
class MutableMemberships:
    memberships: dict[tuple[UUID, UUID], Membership] = field(default_factory=dict)

    async def resolve(self, user_id: UUID, workspace_id: UUID) -> Membership | None:
        return self.memberships.get((user_id, workspace_id))


def test_workspace_selector_is_revalidated_and_cleared_after_revocation() -> None:
    # Given: an authenticated member with one active workspace.
    user_id = uuid4()
    workspace_id = uuid4()
    other_workspace_id = uuid4()
    memberships = MutableMemberships(
        {(user_id, workspace_id): Membership(workspace_id, WorkspaceRole.MEMBER)}
    )
    app = FastAPI()
    app.add_middleware(SaasCsrfMiddleware)
    app.include_router(
        create_saas_auth_router(
            identity_provider=FakeProvider(user_id),
            token_verifier=FakeVerifier(user_id),
            session_store=BffSessionStore(),
            membership_resolver=memberships,
        )
    )

    with TestClient(app, base_url="https://testserver") as client:
        csrf_response = client.get("/api/saas/auth/csrf")
        csrf = csrf_response.cookies["__Host-ragstudio-csrf"]
        client.post(
            "/api/saas/auth/signin",
            headers={"X-CSRF-Token": csrf},
            json={"email": "member@example.test", "password": "secret-value"},
        )

        # When: a foreign UUID is selected, then the valid membership is revoked.
        tampered = client.put(
            "/api/saas/auth/workspace",
            headers={"X-CSRF-Token": csrf},
            json={"workspace_id": str(other_workspace_id)},
        )
        selected = client.put(
            "/api/saas/auth/workspace",
            headers={"X-CSRF-Token": csrf},
            json={"workspace_id": str(workspace_id)},
        )
        memberships.memberships.clear()
        stale_context = client.get("/api/saas/auth/context")
        recovered_session = client.get("/api/saas/auth/session")

    # Then: tampering and stale-tab access are denied before tenant work.
    assert tampered.status_code == 403
    assert tampered.json() == {"detail": "Workspace is unavailable."}
    assert selected.status_code == 200
    assert stale_context.status_code == 403
    assert stale_context.json() == {"detail": "Workspace is unavailable."}
    assert recovered_session.status_code == 200
    assert recovered_session.json()["workspace"] is None


def test_malformed_session_handle_returns_sanitized_401() -> None:
    # Given: a browser-supplied opaque handle that the BFF never issued.
    user_id = uuid4()
    app = FastAPI()
    app.add_middleware(SaasCsrfMiddleware)
    app.include_router(
        create_saas_auth_router(
            identity_provider=FakeProvider(user_id),
            token_verifier=FakeVerifier(user_id),
            session_store=BffSessionStore(),
            membership_resolver=MutableMemberships(),
        )
    )

    with TestClient(app, base_url="https://testserver") as client:
        client.cookies.set("__Host-ragstudio-session", "attacker-controlled")
        response = client.get("/api/saas/auth/session")

    # Then: no store, token, or identifier detail crosses the HTTP boundary.
    assert response.status_code == 401
    assert response.json() == {"detail": "Authentication required."}
    assert "attacker-controlled" not in response.text
