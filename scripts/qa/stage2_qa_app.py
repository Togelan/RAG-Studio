"""Standalone composition root for the deterministic Stage 2 QA app."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from scripts.qa.stage2_qa_chat import register_chat
from scripts.qa.stage2_qa_routes import (
    register_health_locale,
    register_ingestion_mutations,
    register_ingestion_reads,
    register_qa_controls,
    register_settings,
    register_spa,
    register_upload,
)
from scripts.qa.stage2_qa_state import Stage2QaState


def create_qa_app(
    state: Stage2QaState,
    *,
    dist_root: Path,
    locale_root: Path,
) -> FastAPI:
    """Create an isolated API and serve the already-built React bundle."""
    index_path = dist_root / "index.html"
    assets_path = dist_root / "assets"
    if not index_path.is_file() or not assets_path.is_dir():
        raise RuntimeError(
            "React production bundle is missing; run the frontend build first"
        )
    if not all((locale_root / f"{locale}.json").is_file() for locale in ("en", "ru")):
        raise RuntimeError("authoritative locale files are missing")

    app = FastAPI(title="RAG-Studio Stage 2 isolated QA", docs_url=None, redoc_url=None)
    app.mount(
        "/react-assets/assets",
        StaticFiles(directory=assets_path),
        name="react-assets",
    )
    app.mount("/assets", StaticFiles(directory=assets_path), name="assets")
    register_health_locale(app, state, locale_root)
    register_settings(app, state)
    register_ingestion_reads(app, state)
    register_upload(app, state)
    register_ingestion_mutations(app, state)
    register_qa_controls(app, state)
    register_chat(app, state.workload)
    register_spa(app, index_path)
    return app
