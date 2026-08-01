"""Regression tests for deterministic runtime data paths."""

from __future__ import annotations

from pathlib import Path

from src.api.dependencies import get_secrets_path
from src.paths import PROJECT_ROOT, data_path, data_root, resolve_project_path


def test_default_data_root_is_absolute_and_independent_of_cwd(
    monkeypatch, tmp_path: Path
) -> None:
    """The default must not be affected by where the process was started."""
    monkeypatch.delenv("RAG_STUDIO_DATA_ROOT", raising=False)
    monkeypatch.chdir(tmp_path)

    assert data_root() == PROJECT_ROOT / "rag-data"
    assert data_path("checkpoints", "checkpoints.db") == (
        PROJECT_ROOT / "rag-data" / "checkpoints" / "checkpoints.db"
    )


def test_data_root_override_and_relative_component_overrides(
    monkeypatch, tmp_path: Path
) -> None:
    """One root controls defaults while established overrides still win."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RAG_STUDIO_DATA_ROOT", "runtime-data")
    monkeypatch.setenv("RAG_STUDIO_SETTINGS_PATH", "config/settings.json")
    monkeypatch.setenv("QDRANT_PATH", str(tmp_path / "qdrant"))

    from src.api.routes.model_fetcher import _models_cache_path
    from src.api.routes.settings import _get_settings_path
    from src.ingestion.embedder import _get_cache_dir
    from src.ingestion.router import _raw_uploads_dir, _settings_path
    from src.retrieve.orchestrator import _flashrank_cache_dir
    from src.vector_store.client import _qdrant_path

    root = PROJECT_ROOT / "runtime-data"
    assert data_root() == root
    assert _raw_uploads_dir() == root / "raw_uploads"
    assert _models_cache_path() == root / "models_cache.json"
    assert Path(_get_cache_dir()) == root / "models" / "fastembed_cache"
    assert Path(_flashrank_cache_dir()) == root / "models" / "flashrank"
    assert _get_settings_path() == PROJECT_ROOT / "config" / "settings.json"
    assert _settings_path() == PROJECT_ROOT / "config" / "settings.json"
    assert _qdrant_path() == tmp_path / "qdrant"


def test_relative_paths_are_anchored_at_project_root(monkeypatch, tmp_path: Path) -> None:
    """Relative values never resolve from the mutable process CWD."""
    monkeypatch.chdir(tmp_path)

    assert resolve_project_path("rag-data") == PROJECT_ROOT / "rag-data"


def test_default_secrets_path_uses_the_unified_data_root(
    monkeypatch, tmp_path: Path
) -> None:
    """Secrets remain with the Docker-compatible application data volume."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("RAG_STUDIO_DATA_ROOT", raising=False)
    monkeypatch.delenv("RAG_STUDIO_SECRETS_PATH", raising=False)

    assert get_secrets_path() == PROJECT_ROOT / "rag-data" / "secrets.enc"
