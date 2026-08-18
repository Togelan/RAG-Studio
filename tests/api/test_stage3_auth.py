from __future__ import annotations

import base64
import json
import time
from collections.abc import Mapping
from dataclasses import dataclass
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.routes.saas_auth import create_saas_auth_router
from src.api.saas_identity import (
    IdentityTokens,
    IdentityUser,
    JwksJwtVerifier,
    JwtClaims,
    SignupPending,
    SupabaseIdentityProvider,
)
from src.api.saas_security import SaasCsrfMiddleware
from src.api.saas_sessions import BffSessionStore, Membership, MembershipResolver


@dataclass(slots=True)
class FakeIdentityProvider:
    user_id: UUID
    signed_out: list[str]

    async def signup(self, email: str, password: str) -> IdentityTokens:
        del password
        return self._tokens(email, "signup-access", "signup-refresh")

    async def signin(self, email: str, password: str) -> IdentityTokens:
        del password
        return self._tokens(email, "signin-access", "signin-refresh")

    async def refresh(self, refresh_token: str) -> IdentityTokens:
        assert refresh_token == "signin-refresh"
        return self._tokens("owner@example.test", "renewed-access", "renewed-refresh")

    async def signout(self, access_token: str) -> None:
        self.signed_out.append(access_token)

    async def verify_access_token(self, access_token: str) -> IdentityUser:
        if access_token == "expired-access":
            raise PermissionError
        return IdentityUser(id=self.user_id, email="owner@example.test")

    def _tokens(self, email: str, access: str, refresh: str) -> IdentityTokens:
        return IdentityTokens(
            access_token=access,
            refresh_token=refresh,
            expires_in_seconds=900,
            user=IdentityUser(id=self.user_id, email=email),
        )


@dataclass(frozen=True, slots=True)
class RemoteVerifier:
    provider: FakeIdentityProvider

    async def verify(self, token: str) -> JwtClaims:
        user = await self.provider.verify_access_token(token)
        return JwtClaims(user_id=user.id, email=user.email)


@dataclass(frozen=True, slots=True)
class NoMemberships(MembershipResolver):
    async def resolve(self, user_id: UUID, workspace_id: UUID) -> Membership | None:
        del user_id, workspace_id
        return None


def _app(provider: FakeIdentityProvider) -> FastAPI:
    app = FastAPI()
    app.add_middleware(SaasCsrfMiddleware)
    app.include_router(
        create_saas_auth_router(
            identity_provider=provider,
            token_verifier=RemoteVerifier(provider),
            session_store=BffSessionStore(),
            membership_resolver=NoMemberships(),
        )
    )
    return app


def _csrf(client: TestClient) -> str:
    response = client.get("/api/saas/auth/csrf")
    assert response.status_code == 204
    return response.cookies["__Host-ragstudio-csrf"]


@pytest.mark.asyncio
async def test_supabase_signup_accepts_confirmation_required_top_level_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: GoTrue's successful confirmation-required response has no session wrapper.
    user_id = uuid4()
    provider = SupabaseIdentityProvider("http://identity.example.test")
    request = AsyncMock(
        return_value={
            "id": str(user_id),
            "email": "pending@example.test",
            "aud": "authenticated",
        }
    )
    monkeypatch.setattr(provider, "_request", request)

    # When: the BFF exchanges a signup that requires email confirmation.
    outcome = await provider.signup("pending@example.test", "secret-value")

    # Then: successful pending state is preserved without exposing credentials.
    assert outcome == SignupPending(email="pending@example.test")
    assert "secret-value" not in repr(outcome)


def test_signin_refresh_and_signout_keep_provider_tokens_browser_unreadable() -> None:
    # Given: a browser with a fresh double-submit CSRF cookie.
    provider = FakeIdentityProvider(user_id=uuid4(), signed_out=[])
    with TestClient(_app(provider), base_url="https://testserver") as client:
        csrf = _csrf(client)

        # When: the user signs in and rotates the server-owned session.
        signin = client.post(
            "/api/saas/auth/signin",
            headers={"X-CSRF-Token": csrf},
            json={"email": "owner@example.test", "password": "correct horse battery"},
        )
        first_handle = client.cookies["__Host-ragstudio-session"]
        refreshed = client.post(
            "/api/saas/auth/refresh",
            headers={"X-CSRF-Token": csrf},
        )
        second_handle = client.cookies["__Host-ragstudio-session"]
        signed_out = client.post(
            "/api/saas/auth/signout",
            headers={"X-CSRF-Token": csrf},
        )

    # Then: only opaque rotating handles reached the browser and signout revoked locally.
    assert signin.status_code == 200
    assert refreshed.status_code == 200
    assert signed_out.status_code == 204
    assert first_handle != second_handle
    assert "signin-access" not in signin.text
    assert "signin-refresh" not in signin.text
    assert "renewed-access" not in refreshed.text
    assert provider.signed_out == ["renewed-access"]
    assert "Max-Age=0" in signed_out.headers["set-cookie"]


def test_unsafe_auth_request_with_csrf_mismatch_is_rejected_before_provider() -> None:
    # Given: a browser whose CSRF header does not match its cookie.
    provider = FakeIdentityProvider(user_id=uuid4(), signed_out=[])
    with TestClient(_app(provider), base_url="https://testserver") as client:
        _csrf(client)

        # When: a credential mutation is attempted with a replayed token.
        response = client.post(
            "/api/saas/auth/signin",
            headers={"X-CSRF-Token": "replayed-token"},
            json={"email": "owner@example.test", "password": "secret-value"},
        )

    # Then: the BFF returns one sanitized denial without credential material.
    assert response.status_code == 403
    assert response.json() == {"detail": "CSRF validation failed."}
    assert "secret-value" not in response.text


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _signed_jwt(
    private_key: rsa.RSAPrivateKey,
    *,
    key_id: str,
    issuer: str,
    audience: str,
    expires_at: int,
    user_id: UUID,
) -> str:
    header = _b64url(json.dumps({"alg": "RS256", "kid": key_id}).encode())
    payload = _b64url(
        json.dumps(
            {
                "iss": issuer,
                "aud": audience,
                "exp": expires_at,
                "sub": str(user_id),
                "email": "owner@example.test",
            }
        ).encode()
    )
    signing_input = f"{header}.{payload}".encode()
    signature = private_key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
    return f"{header}.{payload}.{_b64url(signature)}"


@pytest.mark.asyncio
async def test_jwks_verifier_refreshes_once_for_rotated_key_and_rejects_expired_token() -> (
    None
):
    # Given: two signing keys and a JWKS fetcher that rotates from old to new.
    issuer = "https://identity.example.test/auth/v1"
    audience = "authenticated"
    user_id = uuid4()
    old_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    new_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    calls = 0

    def jwk(key: rsa.RSAPrivateKey, kid: str) -> Mapping[str, str]:
        public = key.public_key().public_numbers()
        return {
            "kty": "RSA",
            "alg": "RS256",
            "kid": kid,
            "n": _b64url(public.n.to_bytes((public.n.bit_length() + 7) // 8, "big")),
            "e": _b64url(public.e.to_bytes((public.e.bit_length() + 7) // 8, "big")),
        }

    async def fetch_jwks() -> tuple[Mapping[str, str], ...]:
        nonlocal calls
        calls += 1
        return (jwk(old_key, "old"),) if calls == 1 else (jwk(new_key, "new"),)

    verifier = JwksJwtVerifier(
        issuer=issuer,
        audience=audience,
        fetch_jwks=fetch_jwks,
        cache_ttl_seconds=60,
    )
    fresh = _signed_jwt(
        new_key,
        key_id="new",
        issuer=issuer,
        audience=audience,
        expires_at=int(time.time()) + 60,
        user_id=user_id,
    )
    expired = _signed_jwt(
        new_key,
        key_id="new",
        issuer=issuer,
        audience=audience,
        expires_at=int(time.time()) - 1,
        user_id=user_id,
    )

    # When: a previously unseen rotated key and then an expired token are verified.
    claims = await verifier.verify(fresh)
    with pytest.raises(PermissionError):
        await verifier.verify(expired)

    # Then: a single bounded refresh accepted the new key and expiry remained enforced.
    assert claims.user_id == user_id
    assert calls == 2
