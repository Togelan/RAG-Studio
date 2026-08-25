from __future__ import annotations

import json
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient


@contextmanager
def _client_for_mode(
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    react_dist: Path | None = None,
) -> Generator[TestClient]:
    monkeypatch.setenv("RAG_STUDIO_UI_MODE", mode)
    monkeypatch.delenv("RAG_STUDIO_REACT_DIST", raising=False)
    monkeypatch.setenv("RAG_STUDIO_RUNTIME_MODE", "saas" if mode == "react" else "local")
    if react_dist is not None:
        monkeypatch.setenv("RAG_STUDIO_REACT_DIST", str(react_dist))
        monkeypatch.setenv("RAG_STUDIO_DATA_ROOT", str(react_dist.parent / "runtime-data"))
        monkeypatch.setenv("RAG_STUDIO_SUPABASE_URL", "http://127.0.0.1:9")
        monkeypatch.setenv(
            "RAG_STUDIO_SUPABASE_JWT_ISSUER", "http://127.0.0.1:9/auth/v1"
        )
        monkeypatch.setenv("RAG_STUDIO_SUPABASE_JWT_AUDIENCE", "authenticated")
        monkeypatch.setenv(
            "RAG_STUDIO_SUPABASE_DATABASE_URL", "postgresql://invalid/db"
        )
        monkeypatch.setenv("RAG_STUDIO_SESSION_SIGNING_KEY", "x" * 32)
        monkeypatch.setenv(
            "RAG_STUDIO_SESSION_ENCRYPTION_KEYS",
            "v1:AQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQE",
        )
        monkeypatch.setenv("QDRANT_URL", "http://127.0.0.1:9")
        monkeypatch.setenv("RAG_STUDIO_CORS_ORIGINS", "https://testserver")

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
    ):
        from src.api.main import create_app

        with TestClient(create_app()) as client:
            yield client


def _write_valid_react_dist(root: Path) -> None:
    (root / ".vite").mkdir(parents=True)
    (root / "assets").mkdir()
    (root / "index.html").write_text(
        '<main data-stage2-react="true"></main>', encoding="utf-8"
    )
    (root / "assets" / "app-012.js").write_text(
        "export const stage2 = true;", encoding="utf-8"
    )
    (root / ".vite" / "manifest.json").write_text(
        json.dumps({"src/main.tsx": {"file": "assets/app-012.js"}}),
        encoding="utf-8",
    )


def test_legacy_mode_keeps_explicit_rollback_aliases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _client_for_mode(monkeypatch, "legacy") as client:
        for path in ("/legacy", "/legacy/settings", "/legacy/chat"):
            response = client.get(path)
            assert response.status_code == 200
            assert response.headers["cache-control"] == "no-store"


def test_unset_ui_mode_defaults_to_react(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    react_dist = tmp_path / "react-dist"
    _write_valid_react_dist(react_dist)
    monkeypatch.delenv("RAG_STUDIO_UI_MODE", raising=False)
    monkeypatch.setenv("RAG_STUDIO_REACT_DIST", str(react_dist))

    from src.api.react_ui import UiMode, load_ui_serving_configuration

    assert load_ui_serving_configuration().mode is UiMode.REACT


def test_unbuilt_react_preview_is_sanitized_without_breaking_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _client_for_mode(monkeypatch, "legacy") as client:
        response = client.get("/app")

    assert response.status_code == 503
    assert "Traceback" not in response.text
    assert "D:\\" not in response.text


def test_react_mode_serves_canonical_and_preview_routes_from_contained_manifest(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    react_dist = tmp_path / "react-dist"
    _write_valid_react_dist(react_dist)

    with _client_for_mode(monkeypatch, "react", react_dist) as client:
        for path in (
            "/",
            "/settings",
            "/chat",
            "/app",
            "/app/knowledge",
            "/app/settings",
            "/app/chat",
        ):
            response = client.get(path)
            assert response.status_code == 200
            assert 'data-stage2-react="true"' in response.text
            assert response.headers["cache-control"] == "no-store"

        asset = client.get("/react-assets/assets/app-012.js")
        manifest = client.get("/react-assets/.vite/manifest.json")
        traversal = client.get("/react-assets/%2e%2e/index.html")
        health = client.get("/health")
        locale = client.post("/api/ui/locale", json={"locale": "en"})
        legacy_static = client.get("/static/css/style.css")

    assert asset.status_code == 200
    assert asset.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert manifest.status_code == 200
    assert manifest.headers["cache-control"] == "no-store"
    assert traversal.status_code == 404
    assert health.status_code == 200
    assert health.json() == {"status": "ok"}
    assert locale.status_code == 200
    assert locale.json()["locale"] == "en"
    assert legacy_static.status_code == 200


def test_react_mode_does_not_mount_local_legacy_aliases(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    react_dist = tmp_path / "react-dist"
    _write_valid_react_dist(react_dist)

    with _client_for_mode(monkeypatch, "react", react_dist) as client:
        for path in ("/legacy", "/legacy/settings", "/legacy/chat"):
            response = client.get(path)
            assert response.status_code == 404


def test_invalid_ui_mode_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.api.main import create_app

    monkeypatch.setenv("RAG_STUDIO_UI_MODE", "unsupported")
    with pytest.raises(ValueError):
        create_app()


def test_react_mode_missing_manifest_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from src.api.main import create_app

    missing_dist = tmp_path / "missing-react-dist"
    monkeypatch.setenv("RAG_STUDIO_UI_MODE", "react")
    monkeypatch.setenv("RAG_STUDIO_REACT_DIST", str(missing_dist))
    with pytest.raises(RuntimeError):
        create_app()


def test_react_mode_escaping_manifest_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from src.api.main import create_app

    react_dist = tmp_path / "react-dist"
    _write_valid_react_dist(react_dist)
    (react_dist / ".vite" / "manifest.json").write_text(
        json.dumps({"src/main.tsx": {"file": "../index.html"}}), encoding="utf-8"
    )
    monkeypatch.setenv("RAG_STUDIO_UI_MODE", "react")
    monkeypatch.setenv("RAG_STUDIO_REACT_DIST", str(react_dist))
    with pytest.raises(RuntimeError):
        create_app()
