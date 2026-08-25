from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from src.api.main import create_app
from src.api.saas_composition import InvalidApplicationModeError


@dataclass(frozen=True, slots=True)
class FakeClaims:
    user_id: UUID


@dataclass(frozen=True, slots=True)
class FakeAuthResult:
    claims: FakeClaims


@dataclass(frozen=True, slots=True)
class FakeAuthContext:
    user_id: UUID
    stale: bool = False

    async def resolve(self, request: Request, *, require_workspace: bool):
        del request, require_workspace
        if self.stale:
            from fastapi import HTTPException

            raise HTTPException(status_code=401, detail="Authentication required.")
        return FakeAuthResult(FakeClaims(self.user_id))


class FakeScopes:
    def __init__(self, scope_id: UUID) -> None:
        self.scope_id = scope_id

    async def resolve(self, user_id: UUID) -> UUID:
        del user_id
        return self.scope_id


def _write_react_dist(root: Path) -> None:
    (root / ".vite").mkdir(parents=True)
    (root / "assets").mkdir()
    (root / "index.html").write_text(
        '<main data-group2-react="true"></main>', encoding="utf-8"
    )
    (root / "assets" / "app.js").write_text("export {};", encoding="utf-8")
    (root / ".vite" / "manifest.json").write_text(
        json.dumps({"src/main.tsx": {"file": "assets/app.js"}}), encoding="utf-8"
    )


def test_personal_route_uses_only_authenticated_identity_for_scope(
    tmp_path: Path,
) -> None:
    # Given: an authenticated identity, its server-owned scope, and a forged selector.
    from src.api.personal_lab_registry import PersonalLabRouteDependencies
    from src.api.personal_lab_scope import PersonalLabScopeResolver
    from src.api.routes.personal_lab import create_personal_lab_router

    user_id = uuid4()
    own_scope = uuid4()
    forged_scope = uuid4()
    app = FastAPI()
    app.include_router(
        create_personal_lab_router(
            PersonalLabRouteDependencies(
                FakeAuthContext(user_id),
                PersonalLabScopeResolver(FakeScopes(own_scope), tmp_path),
            )
        )
    )

    # When: the browser supplies a foreign query and header selector.
    with TestClient(app) as client:
        response = client.get(
            f"/api/personal/context?scope_id={forged_scope}",
            headers={"X-Personal-Lab-ID": str(forged_scope)},
        )

    # Then: neither browser-controlled value can choose the resolved scope.
    assert response.status_code == 200
    assert response.json() == {
        "id": str(own_scope),
        "namespace": f"pl_{own_scope.hex}",
    }
    assert str(forged_scope) not in response.text


def test_stale_session_is_denied_before_scope_provisioning(tmp_path: Path) -> None:
    # Given: an expired session and a scope authority that must remain unused.
    from src.api.personal_lab_registry import PersonalLabRouteDependencies
    from src.api.personal_lab_scope import PersonalLabScopeResolver
    from src.api.routes.personal_lab import create_personal_lab_router

    scopes = FakeScopes(uuid4())
    app = FastAPI()
    app.include_router(
        create_personal_lab_router(
            PersonalLabRouteDependencies(
                FakeAuthContext(uuid4(), stale=True),
                PersonalLabScopeResolver(scopes, tmp_path),
            )
        )
    )

    # When: the stale browser requests its Personal Lab context.
    with TestClient(app) as client:
        response = client.get("/api/personal/context")

    # Then: authentication fails with no Personal result.
    assert response.status_code == 401
    assert response.json() == {"detail": "Authentication required."}


@pytest.mark.parametrize(
    ("runtime_mode", "ui_mode"),
    (("saas", "legacy"), ("local", "react")),
)
def test_invalid_runtime_ui_pairs_fail_startup_sanitized(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    runtime_mode: str,
    ui_mode: str,
) -> None:
    # Given: one explicitly invalid runtime/UI combination.
    if ui_mode == "react":
        react_dist = tmp_path / "react-dist"
        _write_react_dist(react_dist)
        monkeypatch.setenv("RAG_STUDIO_REACT_DIST", str(react_dist))
    monkeypatch.setenv("RAG_STUDIO_RUNTIME_MODE", runtime_mode)
    monkeypatch.setenv("RAG_STUDIO_UI_MODE", ui_mode)
    if runtime_mode == "saas":
        _configure_saas(monkeypatch, tmp_path)
    # When/Then: app creation fails before any route composition occurs.
    with pytest.raises(InvalidApplicationModeError) as error:
        create_app()
    assert str(error.value) == (
        "RAG-Studio requires either SaaS with React or local with Legacy UI."
    )
    assert str(tmp_path) not in str(error.value)


def test_direct_knowledge_link_serves_react_and_legacy_api_is_absent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Given: the valid SaaS plus React composition with authorities isolated.
    react_dist = tmp_path / "react-dist"
    _write_react_dist(react_dist)
    _configure_saas(monkeypatch, tmp_path)
    monkeypatch.setenv("RAG_STUDIO_UI_MODE", "react")
    monkeypatch.setenv("RAG_STUDIO_REACT_DIST", str(react_dist))
    # When: React deep-link and Legacy settings paths are requested.
    with _isolated_saas_app(create_app()) as client:
        deep_link = client.get("/app/knowledge")
        legacy_settings = client.get("/api/settings")
        legacy_ingest = client.post("/api/ingest/upload")
        legacy_chat = client.post("/api/chat/send")
        legacy_page = client.get("/legacy")
        unknown_personal = client.get("/api/personal/unknown")

    # Then: only the React document and mounted Personal namespace are present.
    assert deep_link.status_code == 200
    assert 'data-group2-react="true"' in deep_link.text
    assert legacy_settings.status_code == 404
    assert legacy_ingest.status_code == 404
    assert legacy_chat.status_code == 404
    assert legacy_page.status_code == 404
    assert unknown_personal.status_code == 404


def test_local_legacy_mounts_only_global_apis_and_shared_contracts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: the valid explicit local plus Legacy rollback composition.
    monkeypatch.setenv("RAG_STUDIO_RUNTIME_MODE", "local")
    monkeypatch.setenv("RAG_STUDIO_UI_MODE", "legacy")

    # When: global, Personal, health, and locale contracts are requested.
    with _isolated_saas_app(create_app()) as client:
        settings = client.get("/api/settings")
        personal = client.get("/api/personal/context")
        health = client.get("/health")
        locale = client.post("/api/ui/locale", json={"locale": "en"})

    # Then: only Legacy data APIs and shared non-data contracts are mounted.
    assert settings.status_code == 200
    assert personal.status_code == 404
    assert health.status_code == 200
    assert health.json() == {"status": "ok"}
    assert locale.status_code == 200
    assert locale.json()["locale"] == "en"


def test_explicit_local_legacy_mode_keeps_chat_rollback_surface(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: the only approved rollback composition is explicitly selected.
    monkeypatch.setenv("RAG_STUDIO_RUNTIME_MODE", "local")
    monkeypatch.setenv("RAG_STUDIO_UI_MODE", "legacy")

    # When: an operator opens the explicit Legacy Chat alias.
    with _isolated_saas_app(create_app()) as client:
        legacy_chat = client.get("/legacy/chat")
        personal_chat = client.get("/api/personal/chat/sessions")

    # Then: the host-global UI remains available without mounting Personal APIs.
    assert legacy_chat.status_code == 200
    assert 'id="chatForm"' in legacy_chat.text
    assert personal_chat.status_code == 404


def _configure_saas(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("RAG_STUDIO_RUNTIME_MODE", "saas")
    monkeypatch.setenv("RAG_STUDIO_DATA_ROOT", str(tmp_path / "saas-data"))
    monkeypatch.setenv("RAG_STUDIO_SUPABASE_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("RAG_STUDIO_SUPABASE_JWT_ISSUER", "http://127.0.0.1:9/auth/v1")
    monkeypatch.setenv("RAG_STUDIO_SUPABASE_JWT_AUDIENCE", "authenticated")
    monkeypatch.setenv("RAG_STUDIO_SUPABASE_DATABASE_URL", "postgresql://invalid/db")
    monkeypatch.setenv("RAG_STUDIO_SESSION_SIGNING_KEY", "x" * 32)
    monkeypatch.setenv(
        "RAG_STUDIO_SESSION_ENCRYPTION_KEYS",
        "v1:AQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQE",
    )
    monkeypatch.setenv("QDRANT_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("RAG_STUDIO_CORS_ORIGINS", "https://testserver")


@contextmanager
def _isolated_saas_app(app: FastAPI) -> Iterator[TestClient]:
    from unittest.mock import AsyncMock, patch

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
        TestClient(app, base_url="https://testserver") as client,
    ):
        yield client
