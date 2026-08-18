from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
import yaml
from fastapi import FastAPI
from fastapi.responses import Response
from fastapi.testclient import TestClient

from src.api.main import create_app
from src.api.react_ui import load_ui_serving_configuration
from src.api.routes.ui import create_ui_router


def _write_react_build(root: Path) -> None:
    (root / ".vite").mkdir(parents=True)
    (root / "assets").mkdir()
    (root / "index.html").write_text(
        '<main data-stage2-route-contract="react"></main>', encoding="utf-8"
    )
    (root / "assets" / "app.js").write_text("export {};", encoding="utf-8")
    (root / ".vite" / "manifest.json").write_text(
        json.dumps({"src/main.tsx": {"file": "assets/app.js"}}),
        encoding="utf-8",
    )


def test_stage2_canonical_and_legacy_route_contract_is_preserved(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Given: the unchanged Stage 2 React runtime and a valid bundled build.
    react_dist = tmp_path / "react-dist"
    _write_react_build(react_dist)
    monkeypatch.setenv("RAG_STUDIO_UI_MODE", "react")
    monkeypatch.setenv("RAG_STUDIO_REACT_DIST", str(react_dist))
    monkeypatch.setenv("RAG_STUDIO_DATA_ROOT", str(tmp_path / "saas-data"))
    app = FastAPI()
    app.include_router(create_ui_router(load_ui_serving_configuration()))

    # When: every canonical, React alias, and explicit rollback route is requested.
    with TestClient(app) as client:
        canonical = [client.get(path) for path in ("/", "/settings", "/chat")]
        aliases = [client.get(path) for path in ("/app", "/app/settings", "/app/chat")]
        legacy = [
            client.get(path) for path in ("/legacy", "/legacy/settings", "/legacy/chat")
        ]

    # Then: canonical/alias routes stay React and rollback routes stay legacy.
    assert all(response.status_code == 200 for response in canonical + aliases)
    assert all(
        'data-stage2-route-contract="react"' in response.text
        for response in canonical + aliases
    )
    assert all(response.status_code == 200 for response in legacy)
    assert all(
        'data-stage2-route-contract="react"' not in response.text for response in legacy
    )


def test_invalid_runtime_mode_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    # Given: a malformed runtime selector that cannot name an approved mode.
    monkeypatch.setenv("RAG_STUDIO_UI_MODE", "legacy")
    monkeypatch.setenv("RAG_STUDIO_RUNTIME_MODE", "unexpected")

    # When/Then: application construction refuses to guess or fall back.
    with pytest.raises(ValueError, match="RAG_STUDIO_RUNTIME_MODE"):
        create_app()


def test_saas_mode_requires_complete_redacted_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: SaaS mode without identity or BFF session authority.
    monkeypatch.setenv("RAG_STUDIO_UI_MODE", "legacy")
    monkeypatch.setenv("RAG_STUDIO_RUNTIME_MODE", "saas")
    for name in (
        "RAG_STUDIO_SUPABASE_URL",
        "RAG_STUDIO_SUPABASE_JWT_ISSUER",
        "RAG_STUDIO_SUPABASE_DATABASE_URL",
        "RAG_STUDIO_SESSION_SIGNING_KEY",
    ):
        monkeypatch.delenv(name, raising=False)

    # When/Then: construction fails with a sanitized configuration error.
    with pytest.raises(ValueError) as error:
        create_app()
    assert "SaaS runtime configuration is incomplete or invalid." in str(error.value)
    assert "postgres" not in str(error.value).lower()


def test_saas_mode_rejects_malformed_url_without_echoing_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a complete-looking configuration with a secret-bearing invalid URL.
    monkeypatch.setenv("RAG_STUDIO_UI_MODE", "legacy")
    monkeypatch.setenv("RAG_STUDIO_RUNTIME_MODE", "saas")
    monkeypatch.setenv(
        "RAG_STUDIO_SUPABASE_URL", "postgres://user:do-not-echo@invalid/database"
    )
    monkeypatch.setenv(
        "RAG_STUDIO_SUPABASE_JWT_ISSUER", "http://127.0.0.1:8013/auth/v1"
    )
    monkeypatch.setenv(
        "RAG_STUDIO_SUPABASE_DATABASE_URL", "postgresql://local.invalid/postgres"
    )
    monkeypatch.setenv("RAG_STUDIO_SESSION_SIGNING_KEY", "x" * 32)

    # When/Then: boundary parsing rejects it through the same sanitized error.
    with pytest.raises(ValueError) as error:
        create_app()
    assert str(error.value) == "SaaS runtime configuration is incomplete or invalid."
    assert "do-not-echo" not in str(error.value)


def test_saas_routes_are_gated_and_dependency_failure_is_sanitized(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # Given: a complete SaaS configuration whose identity dependency is absent.
    react_dist = tmp_path / "react-dist"
    _write_react_build(react_dist)
    monkeypatch.setenv("RAG_STUDIO_UI_MODE", "react")
    monkeypatch.setenv("RAG_STUDIO_REACT_DIST", str(react_dist))
    monkeypatch.setenv("RAG_STUDIO_RUNTIME_MODE", "saas")
    monkeypatch.setenv("RAG_STUDIO_DATA_ROOT", str(tmp_path / "saas-data"))
    monkeypatch.setenv("RAG_STUDIO_SUPABASE_URL", "http://127.0.0.1:9")
    monkeypatch.setenv(
        "RAG_STUDIO_SUPABASE_JWT_ISSUER", "http://127.0.0.1:54321/auth/v1"
    )
    monkeypatch.setenv("RAG_STUDIO_SUPABASE_JWT_AUDIENCE", "authenticated")
    monkeypatch.setenv(
        "RAG_STUDIO_SUPABASE_DATABASE_URL", "postgresql://local.invalid/postgres"
    )
    monkeypatch.setenv("RAG_STUDIO_SESSION_SIGNING_KEY", "x" * 32)

    # When: the SaaS UI and dependency status endpoints are requested.
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
        TestClient(create_app()) as client,
    ):
        saas_ui = client.get("/saas")
        readiness = client.get("/api/saas/runtime")
        local_api = [
            client.get(path)
            for path in ("/api/settings", "/api/chat/sessions", "/api/ingest/documents")
        ]
        legacy = client.get("/legacy")

    # Then: the UI boundary is present and dependency failure exposes no URL.
    assert saas_ui.status_code == 200
    assert 'data-stage2-route-contract="react"' in saas_ui.text
    assert readiness.status_code == 503
    assert readiness.json() == {"detail": "SaaS identity service is unavailable."}
    assert "127.0.0.1" not in readiness.text
    assert all(response.status_code == 404 for response in local_api)
    assert legacy.status_code == 200


def test_saas_unsafe_methods_require_matching_csrf(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: local mode with no authenticated SaaS session.
    monkeypatch.setenv("RAG_STUDIO_UI_MODE", "legacy")
    monkeypatch.setenv("RAG_STUDIO_RUNTIME_MODE", "local")
    with TestClient(create_app()) as client:
        # When: an unsafe SaaS path is probed without and with matching CSRF.
        root_missing = client.post("/api/saas")
        missing = client.post("/api/saas/not-implemented")
        client.cookies.set("__Host-ragstudio-csrf", "same-token")
        matching = client.post(
            "/api/saas/not-implemented",
            headers={"X-CSRF-Token": "same-token"},
        )

    # Then: CSRF blocks first; matching proof reaches normal route resolution.
    assert root_missing.status_code == 403
    assert missing.status_code == 403
    assert missing.json() == {"detail": "CSRF validation failed."}
    assert matching.status_code == 404


def test_bff_session_cookie_is_host_only_and_browser_unreadable() -> None:
    # Given: an opaque server-side session handle and an empty response.
    from src.api.saas_security import (
        BffSessionCookie,
        BffSessionHandle,
        apply_bff_session_cookie,
    )

    response = Response()
    cookie = BffSessionCookie(
        handle=BffSessionHandle("opaque-session-handle"), max_age_seconds=900
    )

    # When: the BFF applies its session cookie contract.
    apply_bff_session_cookie(response, cookie)

    # Then: the browser cannot read it and cross-site delivery is constrained.
    set_cookie = response.headers["set-cookie"]
    assert set_cookie.startswith("__Host-ragstudio-session=")
    assert "HttpOnly" in set_cookie
    assert "Secure" in set_cookie
    assert "SameSite=lax" in set_cookie
    assert "Path=/" in set_cookie
    assert "Domain=" not in set_cookie


def test_stage3_compose_services_are_pinned_and_isolated_from_legacy_data() -> None:
    # Given: the checked-in Compose contract.
    compose_path = Path(__file__).parents[2] / "docker-compose.yml"
    compose = yaml.safe_load(compose_path.read_text(encoding="utf-8"))

    # When: the task-owned Stage 3 service definitions are inspected.
    services = compose["services"]
    auth = services["stage3-auth"]
    database = services["stage3-db"]
    inbox = services["stage3-mail"]
    application = services["rag-studio-saas"]

    # Then: images are exact and SaaS storage cannot bind legacy rag-data.
    assert auth["image"] == "supabase/gotrue:v2.189.0"
    assert database["image"] == "postgres:17.6-alpine"
    assert inbox["image"] == "axllent/mailpit:v1.30.0"
    assert application["profiles"] == ["stage3"]
    assert all("./rag-data" not in volume for volume in application["volumes"])
    assert application["environment"]["RAG_STUDIO_RUNTIME_MODE"] == "saas"

    environment = {
        line.partition("=")[0]: line.partition("=")[2]
        for line in (Path(__file__).parents[2] / ".env.example")
        .read_text(encoding="utf-8")
        .splitlines()
        if line and not line.startswith("#") and "=" in line
    }
    assert environment["RAG_STUDIO_SESSION_SIGNING_KEY"] == ""
    assert environment["RAG_STUDIO_SUPABASE_DATABASE_URL"] == ""
    assert environment["STAGE3_POSTGRES_PASSWORD"] == ""
    assert environment["STAGE3_JWT_SECRET"] == ""


def test_stage3_auth_schema_bootstrap_is_idempotent_and_health_ordered() -> None:
    # Given: the checked-in Compose and task-owned Auth bootstrap contracts.
    project_root = Path(__file__).parents[2]
    compose = yaml.safe_load(
        (project_root / "docker-compose.yml").read_text(encoding="utf-8")
    )
    sql_path = project_root / "docker" / "stage3" / "001-auth-schema.sql"

    # When: the one-shot database bootstrap and Auth dependency are inspected.
    services = compose["services"]
    bootstrap = services["stage3-db-bootstrap"]
    auth = services["stage3-auth"]
    sql = sql_path.read_text(encoding="utf-8")

    # Then: every clean or resumed start creates the bounded Auth authority.
    assert bootstrap["profiles"] == ["stage3"]
    assert bootstrap["image"] == "postgres:17.6-alpine"
    assert bootstrap["depends_on"]["stage3-db"]["condition"] == "service_healthy"
    assert any(
        volume.endswith("/bootstrap/001-auth-schema.sql:ro")
        for volume in bootstrap["volumes"]
    )
    assert (
        auth["depends_on"]["stage3-db-bootstrap"]["condition"]
        == "service_completed_successfully"
    )
    assert auth["environment"]["GOTRUE_DB_DATABASE_URL"].endswith(
        "?sslmode=disable&search_path=auth"
    )
    assert "CREATE SCHEMA IF NOT EXISTS auth;" in sql
    assert "CREATE ROLE authenticated NOLOGIN NOINHERIT;" in sql
    assert "CREATE OR REPLACE FUNCTION auth.uid()" in sql
    assert "GRANT EXECUTE ON FUNCTION auth.uid()" in sql
