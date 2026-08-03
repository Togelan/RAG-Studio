from __future__ import annotations

import asyncio
from importlib import import_module
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.ingestion.parser import canonicalize_filename


@pytest.mark.parametrize(
    ("raw", "canonical"),
    [("report\uff0etxt", "report.txt"), ("\uff21\uff22\uff23.txt", "ABC.txt")],
)
def test_filename_is_nfkc_canonicalized_when_valid(raw: str, canonical: str) -> None:
    # Given a compatibility-equivalent upload name
    # When it crosses the filename trust boundary
    result = canonicalize_filename(raw)
    # Then the display name is the NFKC form
    assert result == canonical


@pytest.mark.parametrize(
    "filename",
    ["report\x00.txt", "report\x85.txt", "safe\u202eevil.txt", "safe\u2066.txt"],
)
def test_filename_is_rejected_when_it_contains_control_or_bidi(filename: str) -> None:
    # Given a filename capable of altering paths or logs
    # When it crosses the filename trust boundary, Then it is rejected
    with pytest.raises(ValueError, match="Invalid filename"):
        canonicalize_filename(filename)


@pytest.mark.asyncio
async def test_equivalent_names_have_one_atomic_admission() -> None:
    router = import_module("src.ingestion.router")
    await router._reset_upload_admissions_for_tests()
    start = asyncio.Event()

    async def reserve(name: str) -> str:
        await start.wait()
        return await router.reserve_upload_name(name, rename=False)

    names = ["Report.txt", "REPORT.txt", "\uff32eport.txt"] * 3 + ["report.txt"]
    tasks = [asyncio.create_task(reserve(name)) for name in names]
    start.set()
    results = await asyncio.gather(*tasks, return_exceptions=True)

    assert sum(isinstance(result, str) for result in results) == 1
    assert (
        sum(isinstance(result, router.FilenameReservedError) for result in results) == 9
    )
    await router.release_upload_name("report.txt")


@pytest.mark.asyncio
async def test_pending_limit_rejects_without_queueing() -> None:
    router = import_module("src.ingestion.router")
    await router._reset_upload_admissions_for_tests()
    for index in range(router.MAX_PENDING_UPLOADS):
        await router.reserve_upload_name(f"doc-{index}.txt", rename=False)

    with pytest.raises(router.UploadCapacityError):
        await asyncio.wait_for(
            router.reserve_upload_name("overflow.txt", rename=False), timeout=0.1
        )
    await router._reset_upload_admissions_for_tests()


@pytest.mark.asyncio
async def test_concurrent_rename_reserves_unique_canonical_names() -> None:
    router = import_module("src.ingestion.router")
    await router._reset_upload_admissions_for_tests()
    start = asyncio.Event()

    async def rename(name: str) -> str:
        await start.wait()
        return await router.reserve_upload_name(name, rename=True)

    tasks = [
        asyncio.create_task(rename(name))
        for name in ("report.txt", "REPORT.txt", "\uff52eport.txt")
    ]
    start.set()
    results = await asyncio.gather(*tasks)

    assert set(results) == {"report.txt", "REPORT (1).txt", "report (2).txt"}
    assert len({router.filename_comparison_key(name) for name in results}) == 3
    await router._reset_upload_admissions_for_tests()


def test_multipart_filename_admission_scenarios(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    router = import_module("src.ingestion.router")
    dependencies = import_module("src.api.dependencies")
    asyncio.run(router._reset_upload_admissions_for_tests())
    router.stored_files.clear()
    monkeypatch.setenv("RAG_STUDIO_LOGS_PATH", str(tmp_path / "logs"))
    monkeypatch.setattr(dependencies, "_audit_logger", None)
    monkeypatch.setattr(router, "_raw_uploads_dir", lambda: tmp_path / "raw")
    monkeypatch.setattr(
        router,
        "get_document_info_from_store",
        AsyncMock(return_value=None),
    )

    async def complete_upload(**kwargs: object) -> None:
        filename = str(kwargs["original_filename"])
        router.log_audit("upload", filename=filename, success=True)
        Path(str(kwargs["file_path"])).unlink(missing_ok=True)
        Path(str(kwargs["staged_raw_path"])).unlink(missing_ok=True)
        await router.release_upload_name(str(kwargs["reservation_key"]))

    monkeypatch.setattr(router, "_ingest_file", complete_upload)
    app = FastAPI()
    app.include_router(router.router)

    async def client_dependency() -> AsyncMock:
        return AsyncMock()

    app.dependency_overrides[router.get_vector_store] = client_dependency
    client = TestClient(app)

    valid = client.post(
        "/api/ingest/upload",
        files={"file": ("report\uff0etxt", b"valid", "text/plain")},
    )
    rejected = client.post(
        "/api/ingest/upload",
        files={"file": ("unsafe\u202e.txt", b"invalid", "text/plain")},
    )
    router.stored_files["report.txt"] = {
        "original_filename": "report.txt",
        "doc_id": "legacy-id",
        "file_hash": "old",
        "chunk_count": 1,
        "chunk_size": 512,
        "chunk_overlap": 64,
    }
    duplicate = client.post(
        "/api/ingest/upload",
        files={"file": ("REPORT.txt", b"changed", "text/plain")},
    )
    cancelled = client.post(
        "/api/ingest/upload?action=cancel",
        files={"file": ("report.txt", b"changed", "text/plain")},
    )
    renamed = client.post(
        "/api/ingest/upload?action=rename",
        files={"file": ("REPORT.txt", b"changed", "text/plain")},
    )

    assert [
        valid.status_code,
        rejected.status_code,
        duplicate.status_code,
        cancelled.status_code,
        renamed.status_code,
    ] == [202, 400, 409, 200, 202]
    assert "report.txt" in valid.json()["message"]
    assert "REPORT (1).txt" in renamed.json()["message"]
    audit_text = (tmp_path / "logs" / "audit.json").read_text(encoding="utf-8")
    assert "\u202e" not in audit_text
    assert "report.txt" in audit_text
