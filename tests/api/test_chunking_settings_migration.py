from __future__ import annotations

import json
from collections.abc import Generator
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from src.api.chunking_settings import (
    ChunkingSettings,
    chunking_for_persistence,
    read_chunking_settings,
)


@pytest.fixture(name="client")
def fixture_client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Generator[TestClient]:
    monkeypatch.setenv("RAG_STUDIO_SETTINGS_PATH", str(tmp_path / "settings.enc.json"))
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

        with TestClient(create_app()) as test_client:
            yield test_client


def test_read_chunking_settings_migrates_legacy_flat_fields() -> None:
    # Given: persisted settings from before strategy selection existed.
    legacy = {"chunk_size": 1024, "chunk_overlap": 128}

    # When: a consumer reads through the shared adapter.
    chunking = read_chunking_settings(legacy)

    # Then: legacy data receives the compatible recursive default.
    assert chunking == ChunkingSettings(
        strategy="recursive", chunk_size=1024, chunk_overlap=128
    )


def test_read_chunking_settings_preserves_valid_legacy_nonpreset_values() -> None:
    chunking = read_chunking_settings({"chunk_size": 128, "chunk_overlap": 0})

    assert chunking == ChunkingSettings(
        strategy="recursive", chunk_size=128, chunk_overlap=0
    )


def test_chunking_for_persistence_keeps_nested_and_compatibility_fields() -> None:
    # Given: a strategy-specific normalized snapshot.
    chunking = ChunkingSettings(
        strategy="parent_document",
        chunk_size=512,
        chunk_overlap=64,
        parent_size=2048,
    )

    # When: persistence representation is produced.
    persisted = chunking_for_persistence(chunking)

    # Then: future readers get the versioned object and legacy readers keep working.
    assert persisted["chunk_size"] == 512
    assert persisted["chunk_overlap"] == 64
    assert persisted["chunking"]["schema_version"] == 1
    assert persisted["chunking"]["strategy"] == "parent_document"


@pytest.mark.parametrize(
    ("chunking_payload", "expected_chunking"),
    [
        (
            {
                "schema_version": 1,
                "strategy": "static",
                "chunk_size": 256,
                "chunk_overlap": 32,
            },
            {
                "schema_version": 1,
                "strategy": "static",
                "chunk_size": 256,
                "chunk_overlap": 32,
                "parent_size": None,
                "window_sentences": None,
            },
        ),
        (
            {
                "schema_version": 1,
                "strategy": "recursive",
                "chunk_size": 1024,
                "chunk_overlap": 128,
            },
            {
                "schema_version": 1,
                "strategy": "recursive",
                "chunk_size": 1024,
                "chunk_overlap": 128,
                "parent_size": None,
                "window_sentences": None,
            },
        ),
        (
            {
                "schema_version": 1,
                "strategy": "parent_document",
                "child_size": 512,
                "child_overlap": 64,
                "parent_size": 2048,
            },
            {
                "schema_version": 1,
                "strategy": "parent_document",
                "chunk_size": 512,
                "chunk_overlap": 64,
                "parent_size": 2048,
                "window_sentences": None,
            },
        ),
        (
            {
                "schema_version": 1,
                "strategy": "sentence_window",
                "chunk_size": 512,
                "chunk_overlap": 64,
                "window_sentences": 3,
            },
            {
                "schema_version": 1,
                "strategy": "sentence_window",
                "chunk_size": 512,
                "chunk_overlap": 64,
                "parent_size": None,
                "window_sentences": 3,
            },
        ),
    ],
)
def test_settings_api_round_trips_each_chunking_strategy(
    client: TestClient,
    chunking_payload: dict[str, int | str],
    expected_chunking: dict[str, int | str | None],
) -> None:
    # Given: one supported strategy payload from the public contract.
    payload = {"chunking": chunking_payload}

    # When: the payload is saved and read back through the HTTP API.
    saved = client.post("/api/settings", json=payload)
    loaded = client.get("/api/settings")

    # Then: clients retain flat compatibility fields and receive normalized nested data.
    assert saved.status_code == 200
    assert loaded.status_code == 200
    response = loaded.json()
    assert response["chunk_size"] == expected_chunking["chunk_size"]
    assert response["chunk_overlap"] == expected_chunking["chunk_overlap"]
    assert response["chunking"] == expected_chunking


def test_seeded_legacy_settings_remain_stable_across_reads_and_persistence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # Given: an actual pre-strategy settings file.
    settings_path = tmp_path / "settings.enc.json"
    settings_path.write_text(
        json.dumps({"chunk_size": 1024, "chunk_overlap": 128}),
        encoding="utf-8",
    )
    monkeypatch.setenv("RAG_STUDIO_SETTINGS_PATH", str(settings_path))

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

        with TestClient(create_app()) as test_client:
            # When: legacy data is read repeatedly, persisted through the public API,
            # and read once more from disk.
            first = test_client.get("/api/settings")
            second = test_client.get("/api/settings")
            saved = test_client.post("/api/settings", json=second.json())
            persisted = json.loads(settings_path.read_text(encoding="utf-8"))

    # Then: every read is recursive and persistence adds the nested contract.
    assert first.status_code == 200
    assert second.status_code == 200
    assert saved.status_code == 200
    assert first.json()["chunking"] == second.json()["chunking"]
    assert first.json()["chunking"]["strategy"] == "recursive"
    assert read_chunking_settings(persisted) == ChunkingSettings(
        strategy="recursive", chunk_size=1024, chunk_overlap=128
    )
    assert persisted["chunking"]["strategy"] == "recursive"


def test_settings_api_rejects_invalid_nested_relation(client: TestClient) -> None:
    # Given: a parent smaller than its child search unit.
    payload = {
        "chunking": {
            "schema_version": 1,
            "strategy": "parent_document",
            "child_size": 1024,
            "child_overlap": 64,
            "parent_size": 512,
        }
    }

    # When: it crosses the route boundary.
    response = client.post("/api/settings", json=payload)

    # Then: FastAPI returns the validation status.
    assert response.status_code == 422
