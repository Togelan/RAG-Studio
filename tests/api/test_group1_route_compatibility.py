from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.react_ui import ReactBuild, UiMode, UiServingConfiguration
from src.api.routes.saas_auth import create_saas_auth_router
from src.api.routes.saas_auth_confirmation import create_saas_auth_confirmation_router
from src.api.routes.ui import create_ui_router
from src.api.saas_identity import IdentityTokens, IdentityUser, JwtClaims
from src.api.saas_security import SaasCsrfMiddleware
from src.api.saas_sessions import BffSessionStore, Membership


@dataclass(slots=True)  # noqa: MUTABLE_OK
class CountingIdentity:
    """Mutable provider double that proves middleware ordering."""

    user_id: UUID
    signin_calls: int = 0

    async def signup(self, email: str, password: str) -> IdentityTokens:
        return await self.signin(email, password)

    async def signin(self, email: str, password: str) -> IdentityTokens:
        del password
        self.signin_calls += 1
        return IdentityTokens(
            "access", "refresh", 900, IdentityUser(self.user_id, email)
        )

    async def refresh(self, refresh_token: str) -> IdentityTokens:
        del refresh_token
        return await self.signin("owner@example.test", "unused")

    async def signout(self, access_token: str) -> None:
        del access_token


@dataclass(frozen=True, slots=True)
class Verifier:
    user_id: UUID

    async def verify(self, token: str) -> JwtClaims:
        del token
        return JwtClaims(self.user_id, "owner@example.test")


@dataclass(frozen=True, slots=True)
class NoMemberships:
    async def resolve(self, user_id: UUID, workspace_id: UUID) -> Membership | None:
        del user_id, workspace_id
        return None


@dataclass(slots=True)  # noqa: MUTABLE_OK
class ConfirmationVerifier:
    """Mutable verifier double that records the forwarded opaque query."""

    queries: list[str] = field(default_factory=list)

    async def verify(self, query: str) -> None:
        self.queries.append(query)


def test_hostile_origin_is_denied_before_credentials_reach_identity() -> None:
    # Given: a valid CSRF token but a cross-site Origin.
    identity = CountingIdentity(uuid4())
    app = FastAPI()
    app.add_middleware(
        SaasCsrfMiddleware, trusted_origins=("https://rag.example.test",)
    )
    app.include_router(
        create_saas_auth_router(
            identity_provider=identity,
            token_verifier=Verifier(identity.user_id),
            session_store=BffSessionStore(),
            membership_resolver=NoMemberships(),
        )
    )
    with TestClient(app, base_url="https://rag.example.test") as client:
        csrf = client.get("/api/saas/auth/csrf").cookies["__Host-ragstudio-csrf"]

        # When: an attacker sends the matching token from an untrusted site.
        response = client.post(
            "/api/saas/auth/signin",
            headers={"X-CSRF-Token": csrf, "Origin": "https://evil.example.test"},
            json={"email": "owner@example.test", "password": "secret-value"},
        )

    # Then: middleware denies before any provider call and returns no input detail.
    assert response.status_code == 403
    assert response.json() == {"detail": "Origin validation failed."}
    assert identity.signin_calls == 0
    assert "evil.example.test" not in response.text
    assert "secret-value" not in response.text


def test_missing_origin_remains_available_to_non_browser_csrf_clients() -> None:
    # Given: a non-browser client with double-submit CSRF proof and no Origin header.
    identity = CountingIdentity(uuid4())
    app = FastAPI()
    app.add_middleware(
        SaasCsrfMiddleware, trusted_origins=("https://rag.example.test",)
    )
    app.include_router(
        create_saas_auth_router(
            identity_provider=identity,
            token_verifier=Verifier(identity.user_id),
            session_store=BffSessionStore(),
            membership_resolver=NoMemberships(),
        )
    )
    with TestClient(app, base_url="https://rag.example.test") as client:
        csrf = client.get("/api/saas/auth/csrf").cookies["__Host-ragstudio-csrf"]

        # When: it performs the authenticated mutation without Origin.
        response = client.post(
            "/api/saas/auth/signin",
            headers={"X-CSRF-Token": csrf},
            json={"email": "owner@example.test", "password": "secret-value"},
        )

    # Then: CSRF remains sufficient for this non-browser contract.
    assert response.status_code == 200
    assert identity.signin_calls == 1


def test_confirmation_completes_at_canonical_app_route() -> None:
    # Given: a verified GoTrue confirmation callback.
    verifier = ConfirmationVerifier()
    app = FastAPI()
    app.include_router(
        create_saas_auth_confirmation_router(completion_url="/app", verifier=verifier)
    )

    # When: the public callback is completed.
    with TestClient(app, base_url="https://rag.example.test") as client:
        response = client.get(
            "/auth/v1/verify?token=opaque&type=signup", follow_redirects=False
        )

    # Then: the user returns to the one canonical product entry.
    assert response.status_code == 303
    assert response.headers["location"] == "/app"
    assert verifier.queries == ["token=opaque&type=signup"]


def test_saas_legacy_rollback_mounts_current_local_api(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Given: SaaS runtime explicitly selects the Legacy rollback UI mode.
    monkeypatch.setenv("RAG_STUDIO_UI_MODE", "legacy")
    monkeypatch.setenv("RAG_STUDIO_RUNTIME_MODE", "saas")
    monkeypatch.setenv("RAG_STUDIO_DATA_ROOT", str(tmp_path / "rollback-data"))
    monkeypatch.setenv("RAG_STUDIO_SUPABASE_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("RAG_STUDIO_SUPABASE_JWT_ISSUER", "http://127.0.0.1:9/auth/v1")
    monkeypatch.setenv("RAG_STUDIO_SUPABASE_JWT_AUDIENCE", "authenticated")
    monkeypatch.setenv(
        "RAG_STUDIO_SUPABASE_DATABASE_URL", "postgresql://local.invalid/postgres"
    )
    monkeypatch.setenv("RAG_STUDIO_SESSION_SIGNING_KEY", "x" * 32)
    monkeypatch.setenv(
        "RAG_STUDIO_SESSION_ENCRYPTION_KEYS",
        "test-v1:AQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQE",
    )
    monkeypatch.setenv("QDRANT_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("RAG_STUDIO_CORS_ORIGINS", "https://testserver")
    from src.api.main import create_app

    # When: the rollback HTML and an existing local settings API are requested.
    with (
        patch(
            "src.api.main.wait_for_qdrant_ready",
            new_callable=AsyncMock,
            return_value=True,
        ),
        patch(
            "src.api.main.close_qdrant_client",
            new_callable=AsyncMock,
            return_value=None,
        ),
        TestClient(create_app(), base_url="https://testserver") as client,
    ):
        rollback = client.get("/legacy/settings")
        local_settings = client.get("/api/settings")
        legacy_mutation = client.post("/api/settings")

    # Then: rollback is functional rather than an HTML-only dead end.
    assert rollback.status_code == 200
    assert local_settings.status_code == 200
    assert legacy_mutation.status_code == 422


def _react_ui_client(tmp_path: Path) -> TestClient:
    build_root = tmp_path / "react-dist"
    build_root.mkdir()
    index_path = build_root / "index.html"
    index_path.write_text('<main data-unified-shell="true"></main>', encoding="utf-8")
    configuration = UiServingConfiguration(
        UiMode.REACT,
        ReactBuild(
            build_root,
            index_path,
            build_root / "manifest.json",
            MappingProxyType({}),
        ),
    )
    app = FastAPI()
    app.include_router(create_ui_router(configuration))
    return TestClient(app, base_url="https://rag.example.test")


def test_retired_saas_direct_gets_enter_the_unified_react_router(
    tmp_path: Path,
) -> None:
    # Given: every retired route pattern documented by the compatibility table.
    workspace_id = "34b9d331-2043-5c6c-b2e6-c91dc8fa4713"
    chatbot_id = "7cf9fced-9a91-4c26-83d2-c08f2b18895d"
    paths = (
        "/saas",
        "/saas/sign-in",
        "/saas/sign-up",
        "/saas/invitations/accept",
        f"/saas/workspaces/{workspace_id}/people",
        f"/saas/workspaces/{workspace_id}/sources",
        f"/saas/workspaces/{workspace_id}/chatbots",
        f"/saas/workspaces/{workspace_id}/chatbots/new",
        f"/saas/workspaces/{workspace_id}/chatbots/{chatbot_id}/edit",
        f"/saas/workspaces/{workspace_id}/chatbots/{chatbot_id}/test",
        f"/saas/workspaces/{workspace_id}/chatbots/{chatbot_id}/test?session=opaque",
        f"/saas/workspaces/{workspace_id}/chatbots?status=private",
        f"/saas/workspaces/{workspace_id}/sources?sort=name",
        f"/saas/workspaces/{workspace_id}/people?tab=members",
        "/saas/workspaces/not-a-uuid/chatbots",
        f"/saas/workspaces/{workspace_id}/chatbots/not-a-uuid/test",
        "/saas/unknown/path",
    )

    # When: each route is opened as a direct document request.
    with _react_ui_client(tmp_path) as client:
        responses = [client.get(path, follow_redirects=False) for path in paths]

    # Then: FastAPI serves the SPA document so its compatibility router can recover.
    assert all(response.status_code == 200 for response in responses)
    assert all('data-unified-shell="true"' in response.text for response in responses)
    assert all(
        response.headers["cache-control"] == "no-store" for response in responses
    )


def test_retired_invitation_query_is_not_echoed_and_api_legacy_stay_separate(
    tmp_path: Path,
) -> None:
    # Given: a bearer-bearing invitation link and similarly named protected routes.
    token = "sensitive-invitation-token"

    # When: the retired document, internal API, and Legacy rollback are requested.
    with _react_ui_client(tmp_path) as client:
        invitation = client.get(f"/saas/invitations/accept?token={token}")
        internal_api = client.get("/api/saas/unmapped")
        legacy = client.get("/legacy/chat")

    # Then: only the retired UI route receives the SPA without echoing the bearer.
    assert invitation.status_code == 200
    assert token not in invitation.text
    assert internal_api.status_code == 404
    assert legacy.status_code == 200
    assert 'data-unified-shell="true"' not in legacy.text
