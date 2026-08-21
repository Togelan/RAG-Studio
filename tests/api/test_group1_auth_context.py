from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.routes.saas_auth import create_saas_auth_router
from src.api.saas_account_models import (
    AccountContext,
    AccountContextError,
    AccountContextErrorCode,
    AccountOwnerProjection,
    AccountStatus,
    SelectedAccountContext,
    WorkspaceContext,
)
from src.api.saas_identity import IdentityTokens, IdentityUser, JwtClaims
from src.api.saas_security import SaasCsrfMiddleware
from src.api.saas_sessions import BffSessionStore, Membership, WorkspaceRole


@dataclass(slots=True)  # noqa: MUTABLE_OK
class FakeIdentity:
    """Mutable test double that records provider refresh calls."""

    user_id: UUID
    refresh_calls: int = 0

    async def signup(self, email: str, password: str) -> IdentityTokens:
        del password
        return self._tokens(email, "signup-access", "signup-refresh")

    async def signin(self, email: str, password: str) -> IdentityTokens:
        del password
        return self._tokens(email, "signin-access", "signin-refresh")

    async def refresh(self, refresh_token: str) -> IdentityTokens:
        assert refresh_token == "signin-refresh"
        self.refresh_calls += 1
        return self._tokens("owner@example.test", "renewed-access", "renewed-refresh")

    async def signout(self, access_token: str) -> None:
        del access_token

    def _tokens(self, email: str, access: str, refresh: str) -> IdentityTokens:
        return IdentityTokens(
            access_token=access,
            refresh_token=refresh,
            expires_in_seconds=900,
            user=IdentityUser(id=self.user_id, email=email),
        )


@dataclass(frozen=True, slots=True)
class FakeVerifier:
    user_id: UUID

    async def verify(self, token: str) -> JwtClaims:
        del token
        return JwtClaims(user_id=self.user_id, email="owner@example.test")


@dataclass(slots=True)  # noqa: MUTABLE_OK
class FakeAccounts:
    """Mutable authority double used to simulate membership revocation."""

    user_id: UUID
    owned: AccountContext
    foreign: AccountContext
    revoked: bool = False
    bootstrapped: list[UUID] = field(default_factory=list)

    async def bootstrap_default_account(self, user_id: UUID) -> AccountContext:
        self.bootstrapped.append(user_id)
        return self.owned

    async def available(self, user_id: UUID) -> tuple[AccountContext, ...]:
        assert user_id == self.user_id
        return (self.owned,) if self.revoked else (self.owned, self.foreign)

    async def resolve(
        self,
        user_id: UUID,
        *,
        account_id: UUID,
        workspace_id: UUID | None,
    ) -> SelectedAccountContext:
        assert user_id == self.user_id
        for account in await self.available(user_id):
            if account.id != account_id:
                continue
            if workspace_id is None:
                if account.owner_projection is None:
                    break
                return SelectedAccountContext(account, None)
            for workspace in account.workspaces:
                if workspace.id == workspace_id:
                    return SelectedAccountContext(account, workspace)
        raise AccountContextError(AccountContextErrorCode.DENIED)


@dataclass(frozen=True, slots=True)
class FakeMemberships:
    accounts: FakeAccounts

    async def resolve(self, user_id: UUID, workspace_id: UUID) -> Membership | None:
        if self.accounts.revoked:
            return None
        for account in (self.accounts.owned, self.accounts.foreign):
            for workspace in account.workspaces:
                if workspace.id == workspace_id:
                    return Membership(workspace_id, workspace.role)
        return None


def _fixture() -> tuple[FastAPI, FakeIdentity, FakeAccounts, UUID]:
    user_id = uuid4()
    foreign_workspace_id = uuid4()
    owned = AccountContext(
        uuid4(),
        "Personal account",
        AccountStatus.ACTIVE,
        AccountOwnerProjection(),
        (),
    )
    foreign = AccountContext(
        uuid4(),
        "Support team",
        AccountStatus.ACTIVE,
        None,
        (WorkspaceContext(foreign_workspace_id, "Handbook", WorkspaceRole.MEMBER),),
    )
    identity = FakeIdentity(user_id)
    accounts = FakeAccounts(user_id, owned, foreign)
    app = FastAPI()
    app.add_middleware(SaasCsrfMiddleware, trusted_origins=("https://testserver",))
    app.include_router(
        create_saas_auth_router(
            identity_provider=identity,
            token_verifier=FakeVerifier(user_id),
            session_store=BffSessionStore(),
            membership_resolver=FakeMemberships(accounts),
            account_context_resolver=accounts,
            account_bootstrapper=accounts,
        )
    )
    return app, identity, accounts, foreign_workspace_id


def _csrf(client: TestClient) -> str:
    response = client.get("/api/saas/auth/csrf")
    assert response.status_code == 204
    return response.cookies["__Host-ragstudio-csrf"]


def test_signin_selects_personal_lab_and_requires_explicit_foreign_context() -> None:
    # Given: one owner Account and one foreign Account membership.
    app, _, accounts, foreign_workspace_id = _fixture()
    with TestClient(app, base_url="https://testserver") as client:
        csrf = _csrf(client)

        # When: the user signs in and explicitly selects the foreign Workspace.
        signed_in = client.post(
            "/api/saas/auth/signin",
            headers={"X-CSRF-Token": csrf, "Origin": "https://testserver"},
            json={"email": "owner@example.test", "password": "correct horse battery"},
        )
        selected = client.put(
            "/api/saas/auth/context",
            headers={"X-CSRF-Token": csrf, "Origin": "https://testserver"},
            json={
                "account_id": str(accounts.foreign.id),
                "workspace_id": str(foreign_workspace_id),
            },
        )

    # Then: the server selects only the owned Personal Lab, not the foreign Workspace.
    assert signed_in.status_code == 200
    assert signed_in.json()["active_account_id"] == str(accounts.owned.id)
    assert signed_in.json()["workspace"] is None
    assert len(signed_in.json()["accounts"]) == 2
    assert accounts.bootstrapped == [accounts.user_id]
    assert selected.status_code == 200
    assert selected.json()["active_account_id"] == str(accounts.foreign.id)
    assert selected.json()["workspace"]["role"] == "member"


def test_revoked_foreign_context_is_cleared_before_next_protected_request() -> None:
    # Given: a selected foreign Workspace whose membership is later revoked.
    app, _, accounts, foreign_workspace_id = _fixture()
    with TestClient(app, base_url="https://testserver") as client:
        csrf = _csrf(client)
        client.post(
            "/api/saas/auth/signin",
            headers={"X-CSRF-Token": csrf},
            json={"email": "owner@example.test", "password": "correct horse battery"},
        )
        client.put(
            "/api/saas/auth/context",
            headers={"X-CSRF-Token": csrf},
            json={
                "account_id": str(accounts.foreign.id),
                "workspace_id": str(foreign_workspace_id),
            },
        )

        # When: authorization is revoked and the stale tab asks for its context.
        accounts.revoked = True
        denied = client.get("/api/saas/auth/context")
        recovered = client.get("/api/saas/auth/session")

    # Then: access is denied and both stale selections are removed server-side.
    assert denied.status_code == 403
    assert denied.json() == {"detail": "Account or Workspace is unavailable."}
    assert recovered.status_code == 200
    assert recovered.json()["active_account_id"] is None
    assert recovered.json()["workspace"] is None


def test_rotated_handle_replay_is_denied_before_provider_refresh() -> None:
    # Given: a signed-in browser that has completed one session rotation.
    app, identity, _, _ = _fixture()
    with TestClient(app, base_url="https://testserver") as client:
        csrf = _csrf(client)
        client.post(
            "/api/saas/auth/signin",
            headers={"X-CSRF-Token": csrf},
            json={"email": "owner@example.test", "password": "correct horse battery"},
        )
        old_handle = client.cookies["__Host-ragstudio-session"]
        first_refresh = client.post(
            "/api/saas/auth/refresh", headers={"X-CSRF-Token": csrf}
        )

        # When: a stale tab replays the already-rotated handle.
        client.cookies.set("__Host-ragstudio-session", old_handle)
        replay = client.post("/api/saas/auth/refresh", headers={"X-CSRF-Token": csrf})

    # Then: the local CAS gate denies before reusing the provider refresh token.
    assert first_refresh.status_code == 200
    assert replay.status_code == 401
    assert replay.json() == {"detail": "Authentication required."}
    assert identity.refresh_calls == 1
