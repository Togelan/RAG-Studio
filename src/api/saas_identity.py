"""Supabase identity exchange and bounded JWT verification."""

from __future__ import annotations

import base64
import json
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

import anyio
import httpx
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from pydantic import BaseModel, ConfigDict, Field, ValidationError


class IdentityRejectedError(PermissionError):
    """Identity input or credentials were rejected without provider detail."""


class IdentityUnavailableError(RuntimeError):
    """The identity authority could not complete a bounded request."""


@dataclass(frozen=True, slots=True)
class IdentityUser:
    """Sanitized identity returned by the authority."""

    id: UUID
    email: str


@dataclass(frozen=True, slots=True)
class IdentityTokens:
    """Provider credentials that never cross the BFF response boundary."""

    access_token: str
    refresh_token: str
    expires_in_seconds: int
    user: IdentityUser


@dataclass(frozen=True, slots=True)
class SignupPending:
    """Signup accepted but email confirmation is still required."""

    email: str


type SignupOutcome = IdentityTokens | SignupPending


@dataclass(frozen=True, slots=True)
class JwtClaims:
    """Trusted minimum JWT claims consumed by the BFF."""

    user_id: UUID
    email: str


class IdentityProvider(Protocol):
    """Narrow Supabase Auth operations used by browser routes."""

    async def signup(self, email: str, password: str) -> SignupOutcome: ...

    async def signin(self, email: str, password: str) -> IdentityTokens: ...

    async def refresh(self, refresh_token: str) -> IdentityTokens: ...

    async def signout(self, access_token: str) -> None: ...


class TokenVerifier(Protocol):
    """Verify provider access tokens into trusted claims."""

    async def verify(self, token: str) -> JwtClaims: ...


class _ProviderUser(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    email: str = Field(min_length=3, max_length=320)


class _TokenPayload(BaseModel):
    model_config = ConfigDict(frozen=True)

    access_token: str = Field(min_length=1)
    refresh_token: str = Field(min_length=1)
    expires_in: int = Field(gt=0)
    user: _ProviderUser


class _SignupPayload(BaseModel):
    model_config = ConfigDict(frozen=True)

    access_token: str | None = None
    refresh_token: str | None = None
    expires_in: int | None = None
    user: _ProviderUser


class SupabaseIdentityProvider:
    """Bounded wire adapter for local or hosted Supabase Auth."""

    def __init__(self, base_url: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = httpx.Timeout(connect=5.0, read=10.0, write=10.0, pool=5.0)

    async def signup(self, email: str, password: str) -> SignupOutcome:
        payload = await self._request(
            "POST", "/signup", json_body={"email": email, "password": password}
        )
        try:
            if "user" not in payload:
                pending_user = _ProviderUser.model_validate(payload)
                return SignupPending(email=str(pending_user.email))
            parsed = _SignupPayload.model_validate(payload)
        except ValidationError:
            raise IdentityUnavailableError from None
        if (
            parsed.access_token is None
            or parsed.refresh_token is None
            or parsed.expires_in is None
        ):
            return SignupPending(email=str(parsed.user.email))
        return _identity_tokens(
            parsed.access_token, parsed.refresh_token, parsed.expires_in, parsed.user
        )

    async def signin(self, email: str, password: str) -> IdentityTokens:
        payload = await self._request(
            "POST",
            "/token?grant_type=password",
            json_body={"email": email, "password": password},
        )
        return _parse_tokens(payload)

    async def refresh(self, refresh_token: str) -> IdentityTokens:
        payload = await self._request(
            "POST",
            "/token?grant_type=refresh_token",
            json_body={"refresh_token": refresh_token},
        )
        return _parse_tokens(payload)

    async def signout(self, access_token: str) -> None:
        await self._request("POST", "/logout", bearer=access_token)

    async def verify_access_token(self, access_token: str) -> IdentityUser:
        payload = await self._request("GET", "/user", bearer=access_token)
        try:
            user = _ProviderUser.model_validate(payload)
        except ValidationError:
            raise IdentityUnavailableError from None
        return IdentityUser(id=user.id, email=str(user.email))

    async def fetch_jwks(self) -> tuple[Mapping[str, str], ...]:
        payload = await self._request("GET", "/.well-known/jwks.json")
        keys = payload.get("keys")
        if not isinstance(keys, list):
            raise IdentityUnavailableError
        return tuple(key for key in keys if isinstance(key, dict))

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: Mapping[str, str] | None = None,
        bearer: str | None = None,
    ) -> Mapping[str, object]:
        headers = {"Authorization": f"Bearer {bearer}"} if bearer else {}
        try:
            async with httpx.AsyncClient(
                base_url=self._base_url,
                timeout=self._timeout,
                follow_redirects=False,
                trust_env=False,
            ) as client:
                response = await client.request(
                    method, path, json=json_body, headers=headers
                )
        except httpx.ConnectError, httpx.TimeoutException, httpx.RemoteProtocolError:
            raise IdentityUnavailableError from None
        if response.status_code in {400, 401, 403, 422}:
            raise IdentityRejectedError from None
        if response.status_code < 200 or response.status_code >= 300:
            raise IdentityUnavailableError
        try:
            decoded = response.json()
        except json.JSONDecodeError:
            raise IdentityUnavailableError from None
        if not isinstance(decoded, dict):
            raise IdentityUnavailableError
        return decoded


JwksFetcher = Callable[[], Awaitable[tuple[Mapping[str, str], ...]]]


class JwksJwtVerifier:
    """RS256 verifier with a TTL cache and one forced refresh for key rotation."""

    def __init__(
        self,
        *,
        issuer: str,
        audience: str,
        fetch_jwks: JwksFetcher,
        cache_ttl_seconds: int,
    ) -> None:
        self._issuer = issuer.rstrip("/")
        self._audience = audience
        self._fetch_jwks = fetch_jwks
        self._cache_ttl_seconds = cache_ttl_seconds
        self._keys: tuple[Mapping[str, str], ...] = ()
        self._cache_expires_at = 0.0
        self._lock = anyio.Lock()

    async def verify(self, token: str) -> JwtClaims:
        header, payload, signing_input, signature = _decode_token(token)
        key_id = header.get("kid")
        if header.get("alg") != "RS256" or not isinstance(key_id, str):
            raise IdentityRejectedError
        key = await self._find_key(key_id, force_refresh=False)
        if key is None:
            key = await self._find_key(key_id, force_refresh=True)
        if key is None:
            raise IdentityRejectedError
        _verify_rs256(key, signing_input, signature)
        return _validated_claims(payload, self._issuer, self._audience)

    async def _find_key(
        self, key_id: str, *, force_refresh: bool
    ) -> Mapping[str, str] | None:
        async with self._lock:
            if (
                force_refresh
                or not self._keys
                or self._cache_expires_at <= time.monotonic()
            ):
                self._keys = await self._fetch_jwks()
                self._cache_expires_at = time.monotonic() + self._cache_ttl_seconds
            return next((key for key in self._keys if key.get("kid") == key_id), None)


class SupabaseAccessTokenVerifier:
    """Use JWKS for asymmetric tokens and Auth introspection for local HS256 tokens."""

    def __init__(
        self, *, provider: SupabaseIdentityProvider, issuer: str, audience: str
    ) -> None:
        self._provider = provider
        self._issuer = issuer.rstrip("/")
        self._audience = audience
        self._jwks = JwksJwtVerifier(
            issuer=self._issuer,
            audience=audience,
            fetch_jwks=provider.fetch_jwks,
            cache_ttl_seconds=300,
        )

    async def verify(self, token: str) -> JwtClaims:
        header, payload, _, _ = _decode_token(token)
        if header.get("alg") == "RS256":
            return await self._jwks.verify(token)
        if header.get("alg") != "HS256":
            raise IdentityRejectedError
        claims = _validated_claims(payload, self._issuer, self._audience)
        user = await self._provider.verify_access_token(token)
        if user.id != claims.user_id or user.email != claims.email:
            raise IdentityRejectedError
        return claims


def _parse_tokens(payload: Mapping[str, object]) -> IdentityTokens:
    try:
        parsed = _TokenPayload.model_validate(payload)
    except ValidationError:
        raise IdentityUnavailableError from None
    return _identity_tokens(
        parsed.access_token, parsed.refresh_token, parsed.expires_in, parsed.user
    )


def _identity_tokens(
    access: str, refresh: str, expires_in: int, user: _ProviderUser
) -> IdentityTokens:
    return IdentityTokens(
        access, refresh, expires_in, IdentityUser(user.id, str(user.email))
    )


def _b64decode(value: str) -> bytes:
    try:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except ValueError, TypeError:
        raise IdentityRejectedError from None


def _decode_token(
    token: str,
) -> tuple[Mapping[str, object], Mapping[str, object], bytes, bytes]:
    parts = token.split(".")
    if len(parts) != 3:
        raise IdentityRejectedError
    try:
        header = json.loads(_b64decode(parts[0]))
        payload = json.loads(_b64decode(parts[1]))
    except json.JSONDecodeError, UnicodeDecodeError:
        raise IdentityRejectedError from None
    if not isinstance(header, dict) or not isinstance(payload, dict):
        raise IdentityRejectedError
    return header, payload, f"{parts[0]}.{parts[1]}".encode(), _b64decode(parts[2])


def _validated_claims(
    payload: Mapping[str, object], issuer: str, audience: str
) -> JwtClaims:
    expires_at = payload.get("exp")
    subject = payload.get("sub")
    email = payload.get("email")
    token_audience = payload.get("aud")
    if (
        not isinstance(expires_at, int)
        or isinstance(expires_at, bool)
        or expires_at <= int(time.time())
        or payload.get("iss") != issuer
        or token_audience != audience
        or not isinstance(subject, str)
        or not isinstance(email, str)
    ):
        raise IdentityRejectedError
    try:
        user_id = UUID(subject)
    except ValueError:
        raise IdentityRejectedError from None
    return JwtClaims(user_id=user_id, email=email)


def _verify_rs256(
    key: Mapping[str, str], signing_input: bytes, signature: bytes
) -> None:
    modulus = key.get("n")
    exponent = key.get("e")
    if (
        key.get("kty") != "RSA"
        or key.get("alg") != "RS256"
        or modulus is None
        or exponent is None
    ):
        raise IdentityRejectedError
    try:
        public_key = rsa.RSAPublicNumbers(
            int.from_bytes(_b64decode(exponent), "big"),
            int.from_bytes(_b64decode(modulus), "big"),
        ).public_key()
        public_key.verify(signature, signing_input, padding.PKCS1v15(), hashes.SHA256())
    except ValueError, InvalidSignature:
        raise IdentityRejectedError from None
