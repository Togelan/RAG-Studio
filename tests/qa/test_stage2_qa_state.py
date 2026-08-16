from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.qa.stage2_qa_schema import WorkloadProfile
from scripts.qa.stage2_qa_state import QaCapacityError, Stage2QaState


def _ready_document(state: Stage2QaState, name: str = "sample.txt") -> str:
    status, upload = state.upload(name, b"alpha beta gamma", "default")
    assert status == 202
    job_id = str(upload["file_id"])
    assert state.progress(job_id)["status"] == "processing"
    assert state.progress(job_id)["status"] == "done"
    page = state.list_documents(None, 50)
    documents = page["documents"]
    assert isinstance(documents, list)
    return str(documents[0]["doc_id"])


def test_fixed_workload_and_happy_document_lifecycle(tmp_path: Path) -> None:
    state = Stage2QaState("rag-studio-stage2-qa-1234abcd", tmp_path)
    doc_id = _ready_document(state)

    assert state.workload == WorkloadProfile()
    assert state.workload.status_oracles == (200, 202, 400, 404, 409, 422, 429, 503)
    assert state.list_chunks(doc_id, None, 1)["chunks"]
    reingest = state.reingest(doc_id)
    assert reingest["status"] == "processing"
    job_id = str(reingest["file_id"])
    state.progress(job_id)
    assert state.progress(job_id)["status"] == "done"
    assert state.delete(doc_id) == 1
    assert state.clear() == 0


def test_reingest_applies_current_chunk_settings_to_document_metadata(
    tmp_path: Path,
) -> None:
    state = Stage2QaState("rag-studio-stage2-qa-1234abcd", tmp_path)
    doc_id = _ready_document(state)
    settings = state.default_settings()
    settings["chunk_size"] = 1024
    settings["chunk_overlap"] = 128
    settings["chunking"] = {
        **settings["chunking"],
        "chunk_size": 1024,
        "chunk_overlap": 128,
    }
    state.save_settings(settings)

    reingest = state.reingest(doc_id)
    job_id = str(reingest["file_id"])
    state.progress(job_id)
    assert state.progress(job_id)["status"] == "done"

    document = state.list_documents(None, 50)["documents"][0]
    assert document["chunk_size"] == 1024
    assert document["chunk_overlap"] == 128


def test_duplicate_cancel_rename_and_replace_are_deterministic(tmp_path: Path) -> None:
    state = Stage2QaState("rag-studio-stage2-qa-1234abcd", tmp_path)
    _ready_document(state)

    status, duplicate = state.upload("sample.txt", b"changed", "default")
    assert (status, duplicate["status"]) == (409, "duplicate")
    status, cancelled = state.upload("sample.txt", b"changed", "cancel")
    assert (status, cancelled["status"]) == (202, "cancelled")
    _, renamed = state.upload("sample.txt", b"changed", "rename")
    state.progress(str(renamed["file_id"]))
    state.progress(str(renamed["file_id"]))
    assert state.list_documents(None, 50)["total"] == 2
    _, replaced = state.upload("sample.txt", b"replacement", "replace")
    state.progress(str(replaced["file_id"]))
    state.progress(str(replaced["file_id"]))
    assert state.list_documents(None, 50)["total"] == 2


def test_snapshot_is_redacted_transferable_and_diff_sensitive(tmp_path: Path) -> None:
    first = Stage2QaState("rag-studio-stage2-qa-1234abcd", tmp_path / "first")
    _ready_document(first, "evidence.txt")
    snapshot = first.snapshot()
    serialized = snapshot.canonical_bytes().decode()

    assert "alpha beta gamma" not in serialized
    assert str(tmp_path) not in serialized
    assert '"api_key":' not in serialized

    twin = Stage2QaState("rag-studio-stage2-qa-deadbeef", tmp_path / "twin")
    twin.load_snapshot(snapshot)
    assert twin.snapshot().sha256(ignore_project=True) == snapshot.sha256(
        ignore_project=True
    )

    injected = snapshot.model_copy(
        update={"settings": snapshot.settings.model_copy(update={"top_k": 6})}
    )
    assert injected.sha256(ignore_project=True) != snapshot.sha256(ignore_project=True)
    assert json.loads(serialized)["workload"]["duration_seconds"] == 30


def test_document_workload_refuses_more_than_twenty_ready_documents(
    tmp_path: Path,
) -> None:
    state = Stage2QaState("rag-studio-stage2-qa-1234abcd", tmp_path)
    for index in range(20):
        _ready_document(state, f"sample-{index}.txt")

    with pytest.raises(QaCapacityError, match="capacity"):
        state.upload("overflow.txt", b"bounded", "default")
