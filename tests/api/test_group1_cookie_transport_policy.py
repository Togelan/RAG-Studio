from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.routes.saas_auth import create_saas_auth_router
from src.api.saas_identity import IdentityTokens, IdentityUser, JwtClaims
from src.api.saas_runtime import load_runtime_configuration
from src.api.saas_security import (
    CSRF_HEADER_NAME,
    DEVELOPMENT_CSRF_COOKIE_NAME,
    DEVELOPMENT_SESSION_COOKIE_NAME,
    CookieTransportConfigurationError,
    SaasCsrfMiddleware,
    load_cookie_transport_policy,
)
from src.api.saas_sessions import BffSessionStore, Membership, MembershipResolver


@dataclass(frozen=True, slots=True)
class _Identity:
    user_id: UUID

    async def signup(self, email: str, password: str) -> IdentityTokens:
        return await self.signin(email, password)

    async def signin(self, email: str, password: str) -> IdentityTokens:
        del password
        return IdentityTokens(
            access_token="provider-access",
            refresh_token="provider-refresh",
            expires_in_seconds=900,
            user=IdentityUser(id=self.user_id, email=email),
        )

    async def refresh(self, refresh_token: str) -> IdentityTokens:
        del refresh_token
        return await self.signin("owner@example.test", "unused-value")

    async def signout(self, access_token: str) -> None:
        del access_token


@dataclass(frozen=True, slots=True)
class _Verifier:
    user_id: UUID

    async def verify(self, token: str) -> JwtClaims:
        del token
        return JwtClaims(user_id=self.user_id, email="owner@example.test")


@dataclass(frozen=True, slots=True)
class _NoMemberships(MembershipResolver):
    async def resolve(self, user_id: UUID, workspace_id: UUID) -> Membership | None:
        del user_id, workspace_id
        return None


def _configure_http_loopback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RAG_STUDIO_COOKIE_SECURE", "false")
    monkeypatch.setenv("RAG_STUDIO_CORS_ORIGINS", "http://127.0.0.1:8013")


def _configure_saas_runtime(
    monkeypatch: pytest.MonkeyPatch,
    origin: str,
) -> None:
    monkeypatch.setenv("RAG_STUDIO_RUNTIME_MODE", "saas")
    monkeypatch.setenv(
        "RAG_STUDIO_DATA_ROOT", str(Path.cwd() / ".tmp-test" / "cookie-policy")
    )
    monkeypatch.setenv("RAG_STUDIO_SUPABASE_URL", "http://identity.example.test")
    monkeypatch.setenv(
        "RAG_STUDIO_SUPABASE_JWT_ISSUER", "http://identity.example.test/auth/v1"
    )
    monkeypatch.setenv("RAG_STUDIO_SUPABASE_DATABASE_URL", "postgresql://db/app")
    monkeypatch.setenv("RAG_STUDIO_SESSION_SIGNING_KEY", "s" * 32)
    monkeypatch.setenv("QDRANT_URL", "http://qdrant.example.test")
    monkeypatch.setenv("RAG_STUDIO_CORS_ORIGINS", origin)
    monkeypatch.setenv("RAG_STUDIO_COOKIE_SECURE", "false")


def _http_auth_app() -> FastAPI:
    user_id = uuid4()
    app = FastAPI()
    app.add_middleware(
        SaasCsrfMiddleware,
        trusted_origins=("http://127.0.0.1:8013",),
    )
    app.include_router(
        create_saas_auth_router(
            identity_provider=_Identity(user_id),
            token_verifier=_Verifier(user_id),
            session_store=BffSessionStore(),
            membership_resolver=_NoMemberships(),
        )
    )
    return app


def test_http_loopback_policy_uses_unprefixed_nonsecure_cookie_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_http_loopback(monkeypatch)

    policy = load_cookie_transport_policy()

    assert policy.secure is False
    assert policy.csrf_cookie_name == DEVELOPMENT_CSRF_COOKIE_NAME
    assert policy.session_cookie_name == DEVELOPMENT_SESSION_COOKIE_NAME
    assert not policy.csrf_cookie_name.startswith("__Host-")


@pytest.mark.parametrize(
    "origin",
    (
        "https://app.example.test",
        "http://app.example.test",
        "http://127.0.0.1.example.test:8013",
    ),
)
def test_nonsecure_policy_rejects_public_or_https_origins_without_echoing_them(
    monkeypatch: pytest.MonkeyPatch,
    origin: str,
) -> None:
    monkeypatch.setenv("RAG_STUDIO_COOKIE_SECURE", "false")
    monkeypatch.setenv("RAG_STUDIO_CORS_ORIGINS", origin)

    with pytest.raises(CookieTransportConfigurationError) as caught:
        load_cookie_transport_policy()

    assert origin not in str(caught.value)


def test_cookie_policy_rejects_malformed_boolean(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RAG_STUDIO_COOKIE_SECURE", "sometimes")
    monkeypatch.setenv("RAG_STUDIO_CORS_ORIGINS", "http://127.0.0.1:8013")

    with pytest.raises(CookieTransportConfigurationError):
        load_cookie_transport_policy()


def test_saas_startup_accepts_only_explicit_http_loopback_development_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_saas_runtime(monkeypatch, "http://127.0.0.1:8013")

    configuration = load_runtime_configuration()

    assert str(configuration.trusted_origins[0]).rstrip("/") == (
        "http://127.0.0.1:8013"
    )


def test_saas_startup_sanitizes_nonsecure_public_origin_rejection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    public_origin = "http://app.example.test"
    _configure_saas_runtime(monkeypatch, public_origin)

    with pytest.raises(CookieTransportConfigurationError) as caught:
        load_runtime_configuration()

    assert public_origin not in str(caught.value)


def test_stage3_compose_exposes_an_overridable_local_cookie_policy() -> None:
    compose = yaml.safe_load(Path("docker-compose.yml").read_text(encoding="utf-8"))
    environment_template = Path(".env.example").read_text(encoding="utf-8")

    configured = compose["services"]["rag-studio-saas"]["environment"]

    assert configured["RAG_STUDIO_COOKIE_SECURE"] == ("${STAGE3_COOKIE_SECURE:-false}")
    assert "RAG_STUDIO_COOKIE_SECURE=true" in environment_template.splitlines()
    assert "STAGE3_COOKIE_SECURE=false" in environment_template.splitlines()


def test_https_policy_remains_secure_and_host_prefixed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RAG_STUDIO_COOKIE_SECURE", "true")
    monkeypatch.setenv("RAG_STUDIO_CORS_ORIGINS", "https://app.example.test")

    policy = load_cookie_transport_policy()

    assert policy.secure is True
    assert policy.csrf_cookie_name.startswith("__Host-")
    assert policy.session_cookie_name.startswith("__Host-")


def test_http_loopback_signin_persists_session_and_csrf_matching(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_http_loopback(monkeypatch)
    with TestClient(_http_auth_app(), base_url="http://127.0.0.1:8013") as client:
        csrf_response = client.get("/api/saas/auth/csrf")
        csrf = csrf_response.cookies[DEVELOPMENT_CSRF_COOKIE_NAME]
        signin = client.post(
            "/api/saas/auth/signin",
            headers={CSRF_HEADER_NAME: csrf},
            json={
                "email": "owner@example.test",
                "password": "correct horse battery",
            },
        )
        session = client.get("/api/saas/auth/session")

    cookie_headers = signin.headers.get_list("set-cookie")
    assert signin.status_code == 200
    assert session.status_code == 200
    assert DEVELOPMENT_SESSION_COOKIE_NAME in client.cookies
    assert all("Secure" not in header for header in cookie_headers)
    assert all("__Host-" not in header for header in cookie_headers)


def test_http_loopback_csrf_mismatch_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_http_loopback(monkeypatch)
    with TestClient(_http_auth_app(), base_url="http://127.0.0.1:8013") as client:
        client.get("/api/saas/auth/csrf")
        response = client.post(
            "/api/saas/auth/signin",
            headers={CSRF_HEADER_NAME: "replayed-proof"},
            json={
                "email": "owner@example.test",
                "password": "correct horse battery",
            },
        )

    assert response.status_code == 403
    assert response.json() == {"detail": "CSRF validation failed."}
