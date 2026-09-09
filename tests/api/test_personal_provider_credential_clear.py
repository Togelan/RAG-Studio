from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from src.api.personal_lab_registry import PersonalLabRouteDependencies
from src.api.personal_lab_scope import PersonalLabScope, PersonalLabScopeResolver
from src.api.personal_lab_settings import PersonalLabSettingsStore
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
        return provider == "deepseek" and api_key == "synthetic-secret-a"

    async def models(self, provider: str, api_key: str | None) -> tuple[str, ...]:
        del provider, api_key
        return ()


def _fixture(
    tmp_path: Path, monkeypatch
) -> tuple[TestClient, PersonalLabSettingsStore, PersonalLabScope, PersonalLabScope]:
    monkeypatch.setenv("RAG_STUDIO_DATA_ROOT", str(tmp_path / "runtime"))
    first_user, second_user = uuid4(), uuid4()
    scopes = {first_user: uuid4(), second_user: uuid4()}
    dependencies = PersonalLabRouteDependencies(
        _CookieAuth({"a": first_user, "b": second_user}),
        PersonalLabScopeResolver(_ScopeRegistry(scopes), tmp_path / "personal"),
    )
    store = PersonalLabSettingsStore()
    app = FastAPI()
    app.add_middleware(
        SaasCsrfMiddleware,
        trusted_origins=("https://testserver",),
        protected_roots=("/api/personal",),
    )
    app.include_router(
        create_personal_settings_router(dependencies, _ProviderGateway(), store)
    )
    return (
        TestClient(app, base_url="https://testserver"),
        store,
        PersonalLabScope(
            scopes[first_user],
            f"pl_{scopes[first_user].hex}",
            tmp_path / "personal" / f"pl_{scopes[first_user].hex}",
            f"pl_{scopes[first_user].hex}",
        ),
        PersonalLabScope(
            scopes[second_user],
            f"pl_{scopes[second_user].hex}",
            tmp_path / "personal" / f"pl_{scopes[second_user].hex}",
            f"pl_{scopes[second_user].hex}",
        ),
    )


def _csrf(client: TestClient) -> dict[str, str]:
    client.cookies.set("__Host-ragstudio-csrf", "proof")
    return {"Origin": "https://testserver", "X-CSRF-Token": "proof"}


def test_clear_provider_credential_removes_only_selected_secret_after_authenticated_csrf_request(
    tmp_path: Path, monkeypatch
) -> None:
    # Given: an authenticated Personal Lab owner with an encrypted DeepSeek credential.
    client, store, first_scope, _ = _fixture(tmp_path, monkeypatch)
    with client:
        client.cookies.set("identity", "a")
        headers = _csrf(client)
        saved = client.post(
            "/api/personal/settings",
            headers=headers,
            json={
                "provider": "deepseek",
                "model": "deepseek-chat",
                "api_key": "synthetic-secret-a",
            },
        )

        # When: the owner explicitly removes the current provider credential.
        cleared = client.request(
            "DELETE",
            "/api/personal/settings/credential",
            headers=headers,
            json={"confirm": True},
        )

    # Then: the credential presence marker and encrypted selected secret are gone, while settings remain.
    record = store.load(first_scope)
    assert saved.status_code == 200
    assert cleared.status_code == 200
    assert cleared.json()["api_key"] is None
    assert record.provider_secrets == {}
    assert record.settings.model == "deepseek-chat"
    assert "synthetic-secret-a" not in store.path_for(first_scope).read_text(
        encoding="utf-8"
    )


def test_clear_provider_credential_denies_missing_csrf_unauthenticated_and_cross_scope_requests(
    tmp_path: Path, monkeypatch
) -> None:
    # Given: A owns a stored provider credential and B has a separate Personal Lab scope.
    client, store, first_scope, second_scope = _fixture(tmp_path, monkeypatch)
    with client:
        client.cookies.set("identity", "a")
        headers = _csrf(client)
        client.post(
            "/api/personal/settings",
            headers=headers,
            json={"provider": "deepseek", "api_key": "synthetic-secret-a"},
        )

        # When: requests omit confirmation or CSRF, omit authentication, or target A from B.
        unconfirmed = client.request(
            "DELETE",
            "/api/personal/settings/credential",
            headers=headers,
            json={"confirm": False},
        )
        missing_csrf = client.request(
            "DELETE", "/api/personal/settings/credential", json={"confirm": True}
        )
        client.cookies.set("identity", "")
        unauthenticated = client.request(
            "DELETE",
            "/api/personal/settings/credential",
            headers=headers,
            json={"confirm": True},
        )
        client.cookies.set("identity", "b")
        other_scope = client.request(
            "DELETE",
            f"/api/personal/settings/credential?scope_id={first_scope.id}",
            headers={**headers, "X-Personal-Lab-ID": str(first_scope.id)},
            json={"confirm": True},
        )

    # Then: all unauthorized paths leave A's secret intact and B's scope contains no credential.
    assert unconfirmed.status_code == 422
    assert missing_csrf.status_code == 403
    assert unauthenticated.status_code == 401
    assert other_scope.status_code == 400
    assert store.load(first_scope).masked_secret == "********"
    assert store.load(second_scope).masked_secret is None
