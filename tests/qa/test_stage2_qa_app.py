from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path

from fastapi.testclient import TestClient

from scripts.qa.stage2_qa_app import create_qa_app
from scripts.qa.stage2_qa_state import Stage2QaState

ROOT = Path(__file__).resolve().parents[2]


class _AssetUrlParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.urls: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "script" and (source := values.get("src")):
            self.urls.append(source)
        if tag == "link" and (href := values.get("href")):
            self.urls.append(href)


def _client(tmp_path: Path) -> TestClient:
    state = Stage2QaState("rag-studio-stage2-qa-1234abcd", tmp_path)
    app = create_qa_app(
        state,
        dist_root=ROOT / "frontend" / "dist",
        locale_root=ROOT / "src" / "api" / "locales",
    )
    return TestClient(app)


def _upload_ready(client: TestClient, name: str, content: bytes = b"alpha beta") -> str:
    upload = client.post(
        "/api/ingest/upload", files={"file": (name, content, "text/plain")}
    )
    assert upload.status_code == 202
    job_id = upload.json()["file_id"]
    assert client.get(f"/api/ingest/progress/{job_id}").json()["status"] == "processing"
    terminal = client.get(f"/api/ingest/progress/{job_id}")
    assert terminal.json()["status"] == "done"
    return job_id


def test_react_settings_locale_and_credential_free_api(tmp_path: Path) -> None:
    client = _client(tmp_path)

    assert client.get("/app/settings").status_code == 200
    assert client.get("/health").json()["mode"] == "stage2-isolated-qa"
    settings = client.get("/api/settings").json()
    assert settings["api_key"] is None
    assert settings["model"] == "qa-model"
    assert client.get("/api/settings/models/deepseek").json()["models"] == ["qa-model"]
    validation = client.post(
        "/api/settings/validate-key",
        json={"provider": "deepseek", "api_key": "anything"},
    )
    assert validation.json()["valid"] is False
    locale = client.post("/api/ui/locale", json={"locale": "ru"})
    assert locale.status_code == 200
    assert locale.json()["locale"] == "ru"


def test_react_index_asset_urls_serve_static_bytes_and_cache_contract(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)
    index = client.get("/app/settings")
    parser = _AssetUrlParser()
    parser.feed(index.text)

    assert {Path(url).suffix for url in parser.urls} == {".css", ".js"}
    for url in parser.urls:
        response = client.get(url)
        bundle_path = ROOT / "frontend" / "dist" / url.removeprefix("/react-assets/")
        expected_mime = "text/css" if url.endswith(".css") else "text/javascript"

        assert response.status_code == 200
        assert response.headers["content-type"].startswith(expected_mime)
        assert response.content == bundle_path.read_bytes()
        assert response.headers["etag"]
        cached = client.get(url, headers={"If-None-Match": response.headers["etag"]})
        assert cached.status_code == 304
        assert cached.content == b""

    missing = client.get("/react-assets/assets/missing.js")
    assert missing.status_code == 404
    assert not missing.headers["content-type"].startswith("text/html")
    assert not missing.content.startswith(b"<!doctype html>")


def test_full_ingestion_decision_reingest_delete_and_clear_journey(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)
    _upload_ready(client, "sample.txt")
    documents = client.get("/api/ingest/documents").json()
    assert documents["total"] == 1
    doc_id = documents["documents"][0]["doc_id"]
    assert client.get(f"/api/ingest/documents/{doc_id}/chunks").json()["chunks"]

    duplicate = client.post(
        "/api/ingest/upload", files={"file": ("sample.txt", b"new", "text/plain")}
    )
    assert (duplicate.status_code, duplicate.json()["status"]) == (409, "duplicate")
    cancel = client.post(
        "/api/ingest/upload?action=cancel",
        files={"file": ("sample.txt", b"new", "text/plain")},
    )
    assert cancel.json()["status"] == "cancelled"
    rename = client.post(
        "/api/ingest/upload?action=rename",
        files={"file": ("sample.txt", b"new", "text/plain")},
    )
    rename_job = rename.json()["file_id"]
    client.get(f"/api/ingest/progress/{rename_job}")
    client.get(f"/api/ingest/progress/{rename_job}")
    assert client.get("/api/ingest/documents").json()["total"] == 2

    replace = client.post(
        "/api/ingest/upload?action=replace",
        files={"file": ("sample.txt", b"replacement", "text/plain")},
    )
    replace_job = replace.json()["file_id"]
    client.get(f"/api/ingest/progress/{replace_job}")
    client.get(f"/api/ingest/progress/{replace_job}")
    assert client.get("/api/ingest/documents").json()["total"] == 2

    current = client.get("/api/ingest/documents").json()["documents"]
    original = next(item for item in current if item["filename"] == "sample.txt")
    settings = client.get("/api/settings").json()
    settings.pop("api_key")
    settings["chunk_size"] = 1024
    settings["chunk_overlap"] = 128
    settings["chunking"]["chunk_size"] = 1024
    settings["chunking"]["chunk_overlap"] = 128
    assert client.post("/api/settings", json=settings).status_code == 200
    reingest = client.post(
        "/api/ingest/reingest",
        json={"doc_id": original["doc_id"], "filename": original["filename"]},
    )
    job_id = reingest.json()["file_id"]
    client.get(f"/api/ingest/progress/{job_id}")
    assert client.get(f"/api/ingest/progress/{job_id}").json()["status"] == "done"
    updated = client.get("/api/ingest/documents").json()["documents"]
    reindexed = next(item for item in updated if item["doc_id"] == original["doc_id"])
    assert (reindexed["chunk_size"], reindexed["chunk_overlap"]) == (1024, 128)
    assert (
        client.delete(f"/api/ingest/documents/{original['doc_id']}").json()[
            "deleted_count"
        ]
        == 1
    )
    assert client.delete("/api/ingest/clear").json()["deleted_count"] == 1


def test_sanitized_failures_and_snapshot_controls(tmp_path: Path) -> None:
    client = _client(tmp_path)
    failed = client.post(
        "/api/ingest/upload",
        files={"file": ("stage2_sample_upload_fail.txt", b"secret body", "text/plain")},
    )
    assert failed.status_code == 503
    assert failed.json() == {"detail": "Upload is temporarily unavailable."}
    assert client.get("/api/ingest/documents?cursor=raw-path").status_code == 400
    assert client.get("/api/ingest/progress/missing").status_code == 404

    progress_failure = client.post(
        "/api/ingest/upload",
        files={"file": ("stage2_sample_progress_fail.txt", b"bounded", "text/plain")},
    )
    failure_job = progress_failure.json()["file_id"]
    client.get(f"/api/ingest/progress/{failure_job}")
    terminal_failure = client.get(f"/api/ingest/progress/{failure_job}")
    assert terminal_failure.json()["status"] == "error"

    _upload_ready(client, "snapshot.txt", b"private document content")
    snapshot = client.get("/__qa/snapshot").json()
    serialized = str(snapshot)
    assert "private document content" not in serialized
    assert str(tmp_path) not in serialized
    loaded = client.post("/__qa/load", json=snapshot)
    assert loaded.status_code == 200
    assert len(loaded.json()["sha256"]) == 64


def test_deterministic_chat_commit_stream_cancel_and_rate_contract(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)

    created = client.post("/api/chat/sessions", json={"title": "load session"})
    assert created.status_code == 201
    session_id = created.json()["id"]
    committed = client.post(
        f"/api/chat/sessions/{session_id}/messages",
        json={"content": "first", "message_id": "client-message"},
    )
    competitor = client.post(
        f"/api/chat/sessions/{session_id}/messages",
        json={"content": "different", "message_id": "client-message"},
    )
    streamed = client.post(
        "/api/chat/send",
        json={
            "content": "bounded stream",
            "session_id": session_id,
            "message_id": "stream-message",
        },
    )

    assert committed.status_code == 201
    assert competitor.status_code == 409
    assert streamed.status_code == 200
    assert "event: start" in streamed.text
    assert "event: done" in streamed.text
    assert client.post(f"/api/chat/sessions/{session_id}/cancel").status_code == 200

    rate_responses = [client.get("/api/chat/sessions") for _ in range(31)]
    assert [response.status_code for response in rate_responses[:30]] == [200] * 30
    assert rate_responses[30].status_code == 429
    assert rate_responses[30].headers["Retry-After"] == "1"


def test_live_thousand_document_cursor_pagination_contract(tmp_path: Path) -> None:
    client = _client(tmp_path)

    seeded = client.post("/__qa/seed-documents", json={"count": 1_000})
    cursor: str | None = None
    documents: list[dict[str, str]] = []
    for _ in range(10):
        query = "?limit=100"
        if cursor is not None:
            query += f"&cursor={cursor}"
        page = client.get(f"/api/ingest/documents{query}").json()
        documents.extend(page["documents"])
        cursor = page["next_cursor"]

    assert seeded.status_code == 200
    assert len(documents) == 1_000
    assert len({document["doc_id"] for document in documents}) == 1_000
    assert cursor is None


def test_server_owned_deadline_emits_terminal_error_and_releases_slot(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)
    created = client.post("/api/chat/sessions", json={"title": "deadline session"})
    session_id = created.json()["id"]

    response = client.post(
        "/__qa/chat/deadline",
        json={
            "content": "server deadline probe",
            "session_id": session_id,
            "message_id": "deadline-message",
        },
    )

    assert response.status_code == 200
    assert "event: error" in response.text
    assert '"code":"deadline_exceeded"' in response.text
    assert "event: done" not in response.text
    assert client.get("/__qa/chat-metrics").json()["active_streams"] == 0
