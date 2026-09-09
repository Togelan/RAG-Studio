from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from pytest import MonkeyPatch

from src.api.main import create_app


def test_versioned_widget_artifact_is_served_from_configured_dist(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    artifact = tmp_path / "rag-studio-widget.v1.js"
    sentinel = tmp_path / "sentinel.txt"
    artifact.write_text(
        "customElements.define('rag-studio-widget', class {});", encoding="utf-8"
    )
    monkeypatch.setenv("RAG_STUDIO_WIDGET_DIST", str(tmp_path))
    sentinel.write_text("must remain private", encoding="utf-8")

    client = TestClient(create_app())
    response = client.get("/widget/rag-studio-widget.v1.js")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/javascript")
    assert response.content == artifact.read_bytes()
    assert response.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert client.get("/widget/sentinel.txt").status_code == 404
    assert "must remain private" not in client.get("/widget/sentinel.txt").text
