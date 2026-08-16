"""Thread-safe state façade for the isolated Stage 2 QA runtime."""

from __future__ import annotations

import threading
import uuid
from pathlib import Path
from typing import Literal

from scripts.qa.stage2_qa_documents import (
    NAMESPACE,
    QaCapacityError,
    QaDocument,
    QaJob,
    chunk_info,
    document_info,
    duplicate_response,
    find_filename,
    make_document,
    parse_cursor,
    reingested_document,
    renamed_filename,
    restore_document,
    safe_filename,
    snapshot_document,
)
from scripts.qa.stage2_qa_schema import LogicalSnapshot, WorkloadProfile
from scripts.qa.stage2_qa_settings import (
    default_settings,
    restore_settings,
    save_settings,
    settings_response,
    snapshot_settings,
)
from scripts.qa.stage2_qa_types import (
    ChunksPage,
    DocumentInfo,
    DocumentsPage,
    DuplicateResponse,
    ProgressResponse,
    ReingestResponse,
    SavedSettings,
    SettingsPayload,
    SettingsResponse,
    UploadResponse,
)

__all__ = ["QaCapacityError", "Stage2QaState"]


class Stage2QaState:
    """Coordinate deterministic settings, document jobs, and snapshots."""

    def __init__(self, project_id: str, root: Path) -> None:
        self.project_id = project_id
        self.root = root
        self.workload = WorkloadProfile()
        self._documents: dict[str, QaDocument] = {}
        self._jobs: dict[str, QaJob] = {}
        self._seeded_document_count = 0
        self._lock = threading.RLock()
        self._settings = default_settings()
        self._system_prompt_sha256: str | None = None

    @staticmethod
    def default_settings() -> SettingsPayload:
        """Return credential-free settings in the production API shape."""
        return default_settings()

    def settings_response(self) -> SettingsResponse:
        """Return settings without credential material."""
        with self._lock:
            return settings_response(self._settings)

    def save_settings(self, payload: SettingsPayload) -> SavedSettings:
        """Replace the logical settings and report chunking changes."""
        with self._lock:
            response = save_settings(self._settings, payload)
            self._settings = payload
            self._system_prompt_sha256 = None
            return response

    def list_documents(self, cursor: str | None, limit: int) -> DocumentsPage:
        """Return one stable bounded document page."""
        offset = parse_cursor(cursor)
        with self._lock:
            stored = sorted(self._documents.values(), key=lambda item: item.filename)
            synthetic: list[DocumentInfo] = [
                {
                    "doc_id": f"qa-seeded-{index:04d}",
                    "filename": f"qa-seeded-{index:04d}.txt",
                    "chunks_count": 1,
                    "chunk_size": 512,
                    "chunk_overlap": 64,
                    "created_at": "2026-01-01T00:00:00Z",
                    "strategy": "recursive",
                    "schema_version": 1,
                }
                for index in range(self._seeded_document_count)
            ]
            documents = synthetic + [document_info(item) for item in stored]
            page = documents[offset : offset + limit]
            next_offset = offset + len(page)
            next_cursor = str(next_offset) if next_offset < len(documents) else None
            return {
                "documents": page,
                "total": len(documents),
                "next_cursor": next_cursor,
                "truncated": next_cursor is not None,
            }

    def seed_documents(self, count: int) -> int:
        """Set the virtual document count used by the 1,000-row load probe."""
        with self._lock:
            self._seeded_document_count = count
            return count

    def list_chunks(self, doc_id: str, cursor: str | None, limit: int) -> ChunksPage:
        """Return one stable bounded chunk page."""
        offset = parse_cursor(cursor)
        with self._lock:
            document = self._documents.get(doc_id)
            if document is None:
                raise KeyError(doc_id)
            page = document.chunks[offset : offset + limit]
            next_offset = offset + len(page)
            next_cursor = (
                str(next_offset) if next_offset < len(document.chunks) else None
            )
            return {
                "chunks": [chunk_info(item) for item in page],
                "next_cursor": next_cursor,
                "truncated": next_cursor is not None,
            }

    def upload(
        self,
        filename: str,
        content: bytes,
        action: str,
    ) -> tuple[Literal[202, 409], UploadResponse | DuplicateResponse]:
        """Admit an upload or return a deterministic duplicate decision."""
        safe_name = safe_filename(filename)
        with self._lock:
            existing = find_filename(self._documents, safe_name)
            if existing is not None and action == "default":
                return 409, duplicate_response(existing, content, self._settings)
            if existing is not None and action == "cancel":
                return 202, {
                    "status": "cancelled",
                    "file_id": "",
                    "message": "Cancelled",
                }
            if existing is not None and action == "rename":
                safe_name = renamed_filename(self._documents, safe_name)
            if existing is not None and action == "replace":
                self._documents.pop(existing.doc_id, None)
            if existing is None and len(self._documents) >= self.workload.max_documents:
                raise QaCapacityError("QA document capacity reached")
            document = make_document(safe_name, content, self._settings)
            job_id = f"qa-job-{uuid.uuid5(NAMESPACE, document.doc_id).hex[:12]}"
            self._jobs[job_id] = QaJob(document=document)
            return 202, {
                "status": "processing",
                "file_id": job_id,
                "message": "Uploading…",
            }

    def progress(self, job_id: str) -> ProgressResponse:
        """Advance a deterministic upload job to a terminal state."""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise KeyError(job_id)
            job.polls += 1
            if job.polls < self.workload.progress_polls_to_ready:
                return {
                    "file_id": job_id,
                    "status": "processing",
                    "message": "Waiting for the next progress update…",
                }
            if job.document.filename.startswith("stage2_sample_progress_fail"):
                return {"file_id": job_id, "status": "error", "message": "QA failure"}
            self._documents[job.document.doc_id] = job.document
            return {
                "file_id": job_id,
                "status": "done",
                "message": "Ready",
                "chunks_count": len(job.document.chunks),
            }

    def reingest(self, doc_id: str) -> ReingestResponse:
        """Queue deterministic re-ingestion for one document."""
        with self._lock:
            document = self._documents.get(doc_id)
            if document is None:
                raise KeyError(doc_id)
            if document.filename.startswith("stage2_sample_reingest_fail"):
                raise RuntimeError("injected reingestion failure")
            job_id = f"qa-job-{uuid.uuid5(NAMESPACE, doc_id + ':reingest').hex[:12]}"
            self._jobs[job_id] = QaJob(
                document=reingested_document(document, self._settings)
            )
            return {"status": "processing", "file_id": job_id, "message": "Queued"}

    def delete(self, doc_id: str) -> int:
        """Delete one logical document."""
        with self._lock:
            return 1 if self._documents.pop(doc_id, None) is not None else 0

    def clear(self) -> int:
        """Delete every logical document."""
        with self._lock:
            count = len(self._documents) + self._seeded_document_count
            self._documents.clear()
            self._seeded_document_count = 0
            return count

    def snapshot(self) -> LogicalSnapshot:
        """Create a canonical snapshot without raw text, paths, or secrets."""
        with self._lock:
            documents = tuple(
                snapshot_document(item)
                for item in sorted(
                    self._documents.values(), key=lambda value: value.doc_id
                )
            )
            settings = snapshot_settings(self._settings, self._system_prompt_sha256)
        return LogicalSnapshot(
            project_id=self.project_id,
            settings=settings,
            documents=documents,
            workload=self.workload,
        )

    def load_snapshot(self, snapshot: LogicalSnapshot) -> None:
        """Load redacted logical state using deterministic synthetic previews."""
        documents = {item.doc_id: restore_document(item) for item in snapshot.documents}
        with self._lock:
            self._documents = documents
            self._jobs.clear()
            self._settings = restore_settings(snapshot.settings)
            self._system_prompt_sha256 = snapshot.settings.system_prompt_sha256
