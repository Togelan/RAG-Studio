from __future__ import annotations

from collections.abc import Generator, Sequence
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from qdrant_client import AsyncQdrantClient

from src.api.chunking_settings import ChunkingSettings, read_chunking_settings
from src.api.dependencies import get_vector_store
from src.ingestion.embedder import get_embedder
from src.ingestion.router import compute_sha256, stored_files
from src.vector_store.adapter import QdrantVectorStore
from src.vector_store.models import DenseVector, SparseVector


class _FakeEmbedder:
    def embed_dense(self, texts: Sequence[str]) -> tuple[DenseVector, ...]:
        return tuple(DenseVector((0.0,) * 384) for _ in texts)

    def embed_sparse(self, texts: Sequence[str]) -> tuple[SparseVector, ...]:
        return tuple(SparseVector((0,), (1.0,)) for _ in texts)


@pytest.fixture(name="client")
def fixture_client(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> Generator[TestClient]:
    monkeypatch.setenv("RAG_STUDIO_SETTINGS_PATH", str(tmp_path / "settings.json"))
    monkeypatch.setenv("RAG_STUDIO_DATA_ROOT", str(tmp_path / "data"))
    vector_store = AsyncMock()
    vector_store.find_document.return_value = None

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
        patch("src.api.routes.settings.load_secrets", return_value={}),
    ):
        from src.api.main import create_app

        app: FastAPI = create_app()
        app.dependency_overrides[get_vector_store] = lambda: vector_store
        app.dependency_overrides[get_embedder] = _FakeEmbedder
        stored_files.clear()
        with TestClient(app, raise_server_exceptions=False) as test_client:
            yield test_client
        stored_files.clear()


def _save_static_settings(client: TestClient) -> ChunkingSettings:
    payload = {
        "chunking": {
            "schema_version": 1,
            "strategy": "static",
            "chunk_size": 512,
            "chunk_overlap": 64,
        }
    }
    response = client.post("/api/settings", json=payload)
    assert response.status_code == 200
    return read_chunking_settings(response.json())


def test_upload_records_normalized_strategy_snapshot(client: TestClient) -> None:
    # Given: static settings whose sizes equal the legacy recursive defaults.
    expected = _save_static_settings(client)
    legacy = ChunkingSettings(strategy="recursive", chunk_size=512, chunk_overlap=64)

    # When: a document is uploaded through the public ingestion route.
    response = client.post(
        "/api/ingest/upload",
        files={"file": ("snapshot.txt", b"snapshot integration", "text/plain")},
    )

    # Then: upload metadata exposes the normalized strategy fingerprint.
    assert response.status_code == 202
    metadata = stored_files["snapshot.txt"]
    assert metadata["chunking_strategy"] == "static"
    assert metadata["chunking_fingerprint"] == expected.fingerprint
    assert metadata["chunking_fingerprint"] != legacy.fingerprint


def test_duplicate_compares_normalized_strategy_fingerprint(client: TestClient) -> None:
    # Given: identical bytes indexed with legacy recursive settings and current static settings.
    expected = _save_static_settings(client)
    legacy = ChunkingSettings(strategy="recursive", chunk_size=512, chunk_overlap=64)
    content = b"same bytes and sizes, different strategy"
    stored_files["duplicate.txt"] = {
        "original_filename": "duplicate.txt",
        "file_hash": compute_sha256(content),
        "chunk_count": 1,
        "chunk_size": 512,
        "chunk_overlap": 64,
        "chunking_strategy": legacy.strategy,
        "chunking_fingerprint": legacy.fingerprint,
    }

    # When: the same file is uploaded without an explicit duplicate action.
    response = client.post(
        "/api/ingest/upload",
        files={"file": ("duplicate.txt", content, "text/plain")},
    )

    # Then: the strategy-only fingerprint change is observable as a conflict.
    assert response.status_code == 409
    assert response.json()["chunks_settings_changed"] is True
    assert expected.fingerprint != legacy.fingerprint


def test_persisted_strategy_fingerprint_survives_cache_clear(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # Given: a real vector store containing a static-strategy upload.
    monkeypatch.setenv("RAG_STUDIO_SETTINGS_PATH", str(tmp_path / "settings.json"))
    monkeypatch.setenv("RAG_STUDIO_DATA_ROOT", str(tmp_path / "data"))
    raw_client = AsyncQdrantClient(path=str(tmp_path / "qdrant"))
    vector_store = QdrantVectorStore(raw_client)
    content = b"restart-safe strategy fingerprint"

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
        patch("src.api.routes.settings.load_secrets", return_value={}),
    ):
        from src.api.main import create_app

        app: FastAPI = create_app()
        app.dependency_overrides[get_vector_store] = lambda: vector_store
        app.dependency_overrides[get_embedder] = _FakeEmbedder
        with TestClient(app, raise_server_exceptions=False) as test_client:
            static = _save_static_settings(test_client)
            first = test_client.post(
                "/api/ingest/upload",
                files={"file": ("restart.txt", content, "text/plain")},
            )
            assert first.status_code == 202
            progress = test_client.get(
                f"/api/ingest/progress/{first.json()['file_id']}"
            )
            assert progress.json()["status"] == "done"
            stored_files.clear()
            recursive_response = test_client.post(
                "/api/settings",
                json={
                    "chunking": {
                        "schema_version": 1,
                        "strategy": "recursive",
                        "chunk_size": 512,
                        "chunk_overlap": 64,
                    }
                },
            )
            recursive = read_chunking_settings(recursive_response.json())

            # When: identical bytes are uploaded after the process-local cache is lost.
            duplicate = test_client.post(
                "/api/ingest/upload",
                files={"file": ("restart.txt", content, "text/plain")},
            )

    # Then: durable recovery observes the strategy-only fingerprint change.
    assert static.fingerprint != recursive.fingerprint
    assert duplicate.status_code == 409
    assert duplicate.json()["chunks_settings_changed"] is True


def test_reingest_records_same_normalized_strategy_snapshot(
    client: TestClient,
    tmp_path: Path,
) -> None:
    # Given: a persisted source and non-default static settings.
    expected = _save_static_settings(client)
    doc_id = "snapshot-reingest"
    raw_path = tmp_path / "data" / "raw_uploads" / f"{doc_id}.txt"
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_text("reingest snapshot integration", encoding="utf-8")

    # When: re-ingestion runs through its public endpoint.
    response = client.post(
        "/api/ingest/reingest",
        json={"doc_id": doc_id, "filename": "reingest.txt"},
    )

    # Then: completed metadata contains the same normalized strategy and fingerprint.
    assert response.status_code == 202
    metadata = stored_files["reingest.txt"]
    assert metadata["chunking_strategy"] == expected.strategy
    assert metadata["chunking_fingerprint"] == expected.fingerprint


def test_malformed_nested_settings_fail_consistently_for_api_and_ingestion(
    client: TestClient,
    tmp_path: Path,
) -> None:
    # Given: persisted nested settings that violate the validated preset contract.
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(
        '{"chunking":{"strategy":"static","chunk_size":999,"chunk_overlap":64}}',
        encoding="utf-8",
    )

    # When: settings and ingestion read the same malformed persisted snapshot.
    settings_response = client.get("/api/settings")
    upload_response = client.post(
        "/api/ingest/upload",
        files={"file": ("malformed.txt", b"malformed settings", "text/plain")},
    )

    # Then: neither reader silently substitutes recursive defaults.
    assert settings_response.status_code == 500
    assert upload_response.status_code == 500
    assert settings_response.text == upload_response.text
