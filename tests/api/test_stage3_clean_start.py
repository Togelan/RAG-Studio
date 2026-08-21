from __future__ import annotations

import hashlib
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

import src.paths as runtime_paths
from src.api.main import create_app
from src.api.saas_runtime import RuntimeMode, load_runtime_configuration


def _write_legacy_sentinels(legacy_root: Path) -> None:
    sentinels = {
        "settings.json": b'{"model":"legacy-local"}',
        "secrets.enc": b"legacy-encrypted-secret-sentinel",
        "checkpoints/checkpoints.db": b"legacy-checkpoint-sentinel",
        "session_titles.json": b'{"legacy-session":"Legacy title"}',
        "feedback.jsonl": b'{"feedback":"legacy-sentinel"}\n',
        "qdrant_storage/collections/rag_studio_docs/storage.sqlite": (
            b"legacy-qdrant-sentinel"
        ),
    }
    for relative_path, contents in sentinels.items():
        destination = legacy_root / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(contents)


def _manifest(root: Path) -> dict[str, str]:
    return {
        file.relative_to(root).as_posix(): hashlib.sha256(file.read_bytes()).hexdigest()
        for file in sorted(root.rglob("*"))
        if file.is_file()
    }


def _configure_saas(monkeypatch: pytest.MonkeyPatch, data_root: Path) -> None:
    monkeypatch.setenv("RAG_STUDIO_UI_MODE", "legacy")
    monkeypatch.setenv("RAG_STUDIO_RUNTIME_MODE", "saas")
    monkeypatch.setenv("RAG_STUDIO_DATA_ROOT", str(data_root))
    monkeypatch.setenv("RAG_STUDIO_SUPABASE_URL", "http://127.0.0.1:9999")
    monkeypatch.setenv(
        "RAG_STUDIO_SUPABASE_JWT_ISSUER", "http://127.0.0.1:8013/auth/v1"
    )
    monkeypatch.setenv("RAG_STUDIO_SUPABASE_JWT_AUDIENCE", "authenticated")
    monkeypatch.setenv(
        "RAG_STUDIO_SUPABASE_DATABASE_URL", "postgresql://local.invalid/postgres"
    )
    monkeypatch.setenv("RAG_STUDIO_SESSION_SIGNING_KEY", "x" * 32)
    monkeypatch.setenv(
        "RAG_STUDIO_SESSION_ENCRYPTION_KEYS",
        "test-v1:AQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQE",
    )
    monkeypatch.setenv("QDRANT_URL", "http://127.0.0.1:6333")
    monkeypatch.setenv("RAG_STUDIO_CORS_ORIGINS", "http://testserver")
    for name in (
        "QDRANT_PATH",
        "RAG_STUDIO_SETTINGS_PATH",
        "RAG_STUDIO_LOGS_PATH",
        "FASTEMBED_CACHE_PATH",
        "FLASHRANK_CACHE_PATH",
    ):
        monkeypatch.delenv(name, raising=False)


def _write_react_build(root: Path) -> None:
    (root / ".vite").mkdir(parents=True)
    (root / "assets").mkdir()
    (root / "index.html").write_text(
        '<main data-stage3-clean-start="react"></main>', encoding="utf-8"
    )
    (root / "assets" / "app.js").write_text("export {};", encoding="utf-8")
    (root / ".vite" / "manifest.json").write_text(
        json.dumps({"src/main.tsx": {"file": "assets/app.js"}}), encoding="utf-8"
    )


def test_saas_mode_rejects_implicit_or_overlapping_legacy_data_roots(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Given: a project-default legacy root and otherwise complete SaaS identity config.
    project_root = tmp_path / "project"
    monkeypatch.setattr(runtime_paths, "PROJECT_ROOT", project_root)
    _configure_saas(monkeypatch, project_root / "saas-data")

    # When/Then: SaaS cannot silently use its implicit or legacy data root.
    monkeypatch.delenv("RAG_STUDIO_DATA_ROOT")
    with pytest.raises(ValueError, match="RAG_STUDIO_DATA_ROOT"):
        create_app()

    monkeypatch.setenv("RAG_STUDIO_DATA_ROOT", str(project_root / "rag-data"))
    with pytest.raises(ValueError, match="legacy data"):
        create_app()


@pytest.mark.parametrize(
    ("environment_variable", "error_pattern"),
    (
        ("QDRANT_PATH", "persistent path"),
        ("FASTEMBED_CACHE_PATH", "model cache"),
        ("FLASHRANK_CACHE_PATH", "model cache"),
    ),
)
def test_saas_mode_rejects_legacy_persistence_path_overrides(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    environment_variable: str,
    error_pattern: str,
) -> None:
    # Given: a task-owned SaaS root with an explicit persistence override into legacy data.
    project_root = tmp_path / "project"
    legacy_root = project_root / "rag-data"
    monkeypatch.setattr(runtime_paths, "PROJECT_ROOT", project_root)
    _configure_saas(monkeypatch, project_root / "saas-data")
    monkeypatch.setenv(environment_variable, str(legacy_root / "legacy-cache"))

    # When/Then: configuration fails before Qdrant can open the legacy collection.
    with pytest.raises(ValueError, match=error_pattern):
        create_app()


def test_saas_mode_allows_nonlegacy_model_cache_paths(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Given: model caches separate from both the SaaS root and the legacy root.
    project_root = tmp_path / "project"
    monkeypatch.setattr(runtime_paths, "PROJECT_ROOT", project_root)
    _configure_saas(monkeypatch, project_root / "saas-data")
    monkeypatch.setenv("FASTEMBED_CACHE_PATH", str(project_root / "model-cache"))
    monkeypatch.setenv("FLASHRANK_CACHE_PATH", str(project_root / "rerank-cache"))

    # When: the SaaS runtime validates its persistence boundary.
    configuration = load_runtime_configuration()

    # Then: static model caches are allowed without making legacy data readable.
    assert configuration.mode is RuntimeMode.SAAS


def test_saas_boot_and_rollback_leave_legacy_sentinels_unchanged(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Given: all characterized legacy persistence classes and an empty SaaS root.
    project_root = tmp_path / "project"
    legacy_root = project_root / "rag-data"
    saas_root = project_root / "stage3-saas-data"
    monkeypatch.setattr(runtime_paths, "PROJECT_ROOT", project_root)
    _write_legacy_sentinels(legacy_root)
    before = _manifest(legacy_root)
    _configure_saas(monkeypatch, saas_root)
    react_dist = project_root / "react-dist"
    _write_react_build(react_dist)
    monkeypatch.setenv("RAG_STUDIO_UI_MODE", "react")
    monkeypatch.setenv("RAG_STUDIO_REACT_DIST", str(react_dist))

    # When: SaaS boots and probes both canonical and adversarial legacy endpoints.
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
        route_statuses = {
            path: client.get(path).status_code for path in ("/", "/app", "/legacy")
        }
        forbidden_statuses = {
            path: client.get(path).status_code
            for path in ("/api/settings", "/api/chat/sessions", "/api/ingest/documents")
        }
        import_attempt = client.post("/api/ingest/documents")

    # Then: rollback APIs exist but fail closed without a current BFF session.
    assert route_statuses == {"/": 200, "/app": 200, "/legacy": 200}
    assert forbidden_statuses == {
        "/api/settings": 401,
        "/api/chat/sessions": 401,
        "/api/ingest/documents": 401,
    }
    assert import_attempt.status_code == 403
    assert _manifest(legacy_root) == before

    # And: reverting the mode requires no data migration and retains legacy bytes.
    monkeypatch.setenv("RAG_STUDIO_RUNTIME_MODE", "local")
    monkeypatch.setenv("RAG_STUDIO_DATA_ROOT", str(legacy_root))
    assert load_runtime_configuration().mode is RuntimeMode.LOCAL
    assert _manifest(legacy_root) == before
