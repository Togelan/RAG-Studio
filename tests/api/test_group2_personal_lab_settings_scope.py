from __future__ import annotations

import socket
import threading
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from src.api.personal_lab_registry import PersonalLabRouteDependencies
from src.api.personal_lab_scope import PersonalLabScopeResolver
from src.api.routes.personal_settings import create_personal_settings_router
from src.api.saas_security import SaasCsrfMiddleware


@dataclass(frozen=True, slots=True)
class _Claims:
    user_id: UUID


@dataclass(frozen=True, slots=True)
class _AuthResult:
    claims: _Claims


@dataclass(frozen=True, slots=True)
class _CookieAuth:
    identities: dict[str, UUID]

    async def resolve(
        self, request: Request, *, require_workspace: bool
    ) -> _AuthResult:
        del require_workspace
        user_id = self.identities.get(request.cookies.get("identity", ""))
        if user_id is None:
            raise HTTPException(status_code=401, detail="Authentication required.")
        return _AuthResult(_Claims(user_id))


class _ScopeRegistry:
    def __init__(self, scopes: dict[UUID, UUID]) -> None:
        self._scopes = scopes

    async def resolve(self, user_id: UUID) -> UUID:
        return self._scopes[user_id]


class _ProviderGateway:
    async def validate(self, provider: str, api_key: str) -> bool:
        if api_key == "synthetic-provider-error":
            raise _SyntheticProviderError
        return provider == "deepseek" and api_key == "synthetic-secret-a"

    async def models(self, provider: str, api_key: str | None) -> tuple[str, ...]:
        if provider == "deepseek" and api_key == "synthetic-secret-a":
            return ("deepseek-chat",)
        return ()


class _SyntheticProviderError(RuntimeError):
    def __str__(self) -> str:
        return "synthetic-provider-error"


def _fixture(
    tmp_path: Path,
    monkeypatch,
) -> tuple[TestClient, UUID, UUID]:
    monkeypatch.setenv("RAG_STUDIO_DATA_ROOT", str(tmp_path / "runtime"))
    first_user, second_user = uuid4(), uuid4()
    scopes = {first_user: uuid4(), second_user: uuid4()}
    dependencies = PersonalLabRouteDependencies(
        _CookieAuth({"a": first_user, "b": second_user}),
        PersonalLabScopeResolver(_ScopeRegistry(scopes), tmp_path / "personal"),
    )
    app = FastAPI()
    app.add_middleware(
        SaasCsrfMiddleware,
        trusted_origins=("https://testserver",),
        protected_roots=("/api/personal",),
    )
    app.include_router(
        create_personal_settings_router(dependencies, _ProviderGateway())
    )
    return (
        TestClient(app, base_url="https://testserver"),
        scopes[first_user],
        scopes[second_user],
    )


def _csrf(client: TestClient) -> dict[str, str]:
    client.cookies.set("__Host-ragstudio-csrf", "proof")
    return {"X-CSRF-Token": "proof", "Origin": "https://testserver"}


def test_two_users_receive_isolated_masked_settings(
    tmp_path: Path,
    monkeypatch,
) -> None:
    # Given: two identities sharing one HTTP surface and no Personal settings.
    client, first_scope, second_scope = _fixture(tmp_path, monkeypatch)
    with client:
        headers = _csrf(client)
        client.cookies.set("identity", "a")
        saved = client.post(
            "/api/personal/settings",
            headers=headers,
            json={"provider": "deepseek", "model": "deepseek-chat"},
        )
        validated = client.post(
            "/api/personal/settings/validate-key",
            headers=headers,
            json={"provider": "deepseek", "api_key": "synthetic-secret-a"},
        )
        uncommitted = client.get("/api/personal/settings")
        atomic = client.post(
            "/api/personal/settings",
            headers=headers,
            json={
                "provider": "deepseek",
                "model": "deepseek-chat",
                "api_key": "synthetic-secret-a",
            },
        )

        # When: both users read settings and B forges A's scope selectors.
        first = client.get("/api/personal/settings")
        client.cookies.set("identity", "b")
        second = client.get(
            f"/api/personal/settings?scope_id={first_scope}",
            headers={"X-Personal-Lab-ID": str(first_scope)},
        )
        client.cookies.set("identity", "a")
        models = client.get("/api/personal/settings/models/deepseek")

    # Then: only A has masked metadata and ciphertext contains no plaintext key.
    assert saved.status_code == validated.status_code == atomic.status_code == 200
    assert uncommitted.json()["api_key"] is None
    assert first.json()["api_key"] == "********"
    assert first.json()["model"] == "deepseek-chat"
    assert second.json()["api_key"] is None
    assert second.json()["model"] == "gpt-4o-mini"
    assert models.json()["models"] == ["deepseek-chat"]
    first_file = tmp_path / "personal" / f"pl_{first_scope.hex}" / "settings.enc"
    second_file = tmp_path / "personal" / f"pl_{second_scope.hex}" / "settings.enc"
    assert first_file.is_file()
    assert "synthetic-secret-a" not in first_file.read_text(encoding="utf-8")
    assert not second_file.exists()


def test_rejected_write_preserves_prior_settings_and_security_boundary(
    tmp_path: Path,
    monkeypatch,
) -> None:
    # Given: A has published settings and an authenticated CSRF proof.
    client, _, _ = _fixture(tmp_path, monkeypatch)
    with client:
        headers = _csrf(client)
        client.cookies.set("identity", "a")
        first = client.post(
            "/api/personal/settings",
            headers=headers,
            json={
                "provider": "deepseek",
                "model": "deepseek-chat",
                "api_key": "synthetic-secret-a",
            },
        )

        # When: writes omit CSRF, fail key validation, or inject a key header.
        missing_csrf = client.post(
            "/api/personal/settings",
            json={"provider": "deepseek", "model": "changed"},
        )
        invalid = client.post(
            "/api/personal/settings",
            headers=headers,
            json={
                "provider": "deepseek",
                "model": "changed",
                "api_key": "rejected-secret",
            },
        )
        provider_error = client.post(
            "/api/personal/settings/validate-key",
            headers=headers,
            json={
                "provider": "deepseek",
                "api_key": "synthetic-provider-error",
            },
        )

        def fail_replace(source: Path, target: Path) -> None:
            del source, target
            raise PermissionError("synthetic-private-path")

        monkeypatch.setattr("src.api.personal_lab_settings.os.replace", fail_replace)
        interrupted = client.post(
            "/api/personal/settings",
            headers=headers,
            json={
                "provider": "deepseek",
                "model": "partial",
                "api_key": "synthetic-secret-a",
            },
        )
        header_key = client.get(
            "/api/personal/settings",
            headers={"X-API-Key": "browser-secret"},
        )
        retained = client.get("/api/personal/settings")

    # Then: denials are sanitized and the prior published value remains.
    assert first.status_code == 200
    assert missing_csrf.status_code == 403
    assert invalid.status_code == 400
    assert provider_error.status_code == 502
    assert "synthetic-provider-error" not in provider_error.text
    assert interrupted.status_code == 500
    assert "synthetic-private-path" not in interrupted.text
    assert header_key.status_code == 400
    assert "browser-secret" not in header_key.text
    assert retained.json()["model"] == "deepseek-chat"
    assert retained.json()["api_key"] == "********"


def test_live_http_two_user_settings_sequence_is_masked_and_isolated(
    tmp_path: Path,
    monkeypatch,
    record_property,
) -> None:
    # Given: a real loopback HTTP server with two cookie-authenticated identities.
    monkeypatch.setenv("RAG_STUDIO_DATA_ROOT", str(tmp_path / "runtime"))
    first_user, second_user = uuid4(), uuid4()
    scopes = {first_user: uuid4(), second_user: uuid4()}
    dependencies = PersonalLabRouteDependencies(
        _CookieAuth({"a": first_user, "b": second_user}),
        PersonalLabScopeResolver(_ScopeRegistry(scopes), tmp_path / "personal"),
    )
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    origin = f"http://127.0.0.1:{port}"
    app = FastAPI()
    app.add_middleware(
        SaasCsrfMiddleware,
        trusted_origins=(origin,),
        protected_roots=("/api/personal",),
    )
    app.include_router(
        create_personal_settings_router(dependencies, _ProviderGateway())
    )
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        with httpx.Client(base_url=origin, timeout=5.0) as client:
            for _ in range(100):
                try:
                    client.get("/openapi.json")
                    break
                except httpx.ConnectError:
                    continue
            client.cookies.set("__Host-ragstudio-csrf", "proof")
            client.cookies.set("identity", "a")
            headers = {"X-CSRF-Token": "proof", "Origin": origin}

            # When: A saves a secret and B reads the same Personal endpoint.
            saved = client.post(
                "/api/personal/settings",
                headers=headers,
                json={
                    "provider": "deepseek",
                    "model": "deepseek-chat",
                    "api_key": "synthetic-secret-a",
                },
            )
            first = client.get("/api/personal/settings")
            client.cookies.set("identity", "b")
            second = client.get("/api/personal/settings")
    finally:
        server.should_exit = True
        thread.join(timeout=5.0)

    # Then: the wire response is masked and B receives only isolated defaults.
    assert not thread.is_alive()
    assert saved.status_code == 200
    assert first.json()["api_key"] == "********"
    assert "synthetic-secret-a" not in first.text
    assert second.json()["api_key"] is None
    assert second.json()["model"] == "gpt-4o-mini"
    record_property("loopback_origin", origin)
    record_property("observable", "A=masked; B=defaults; secret_absent")
