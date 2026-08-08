"""FastAPI routes for document ingestion.

Endpoints:
- POST /api/ingest/upload — upload and ingest a document
- GET /api/ingest/documents — list all ingested documents
- DELETE /api/ingest/documents/{file_id} — delete a document
- DELETE /api/ingest/clear — clear all documents
- GET /api/ingest/progress/{file_id} — get ingestion progress
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import shutil
import tempfile
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    HTTPException,
    Response,
    UploadFile,
)
from pydantic import BaseModel

from src.api.chunking_settings import ChunkingSettings, read_chunking_settings
from src.api.dependencies import get_vector_store, log_audit
from src.ingestion.chunker import chunk_text
from src.ingestion.chunking_dispatch import (
    dispatch_csv,
    dispatch_text,
    settings_payload,
    unit_payload,
)
from src.ingestion.chunking_models import ChunkingLimitExceeded
from src.ingestion.document_admission import (  # noqa: F401
    MAX_PENDING_UPLOADS,
    FilenameReservedError,
    UploadCapacityError,
    _document_locks,
    _document_locks_guard,
    _DocumentLockState,
    _pending_upload_names,
    _raw_uploads_dir,
    _reset_upload_admissions_for_tests,
    document_operation_lock,
    release_upload_name,
    reserve_upload_name,
    stored_files,
    stored_files_lock,
)
from src.ingestion.embedder import (
    get_embedder,
    make_doc_id,
    make_document_doc_id,
)
from src.ingestion.embedding import Embedder
from src.ingestion.parser import (
    UnsupportedCsvEncodingError,
    canonicalize_filename,
    detect_and_parse,
    detect_file_type,
    filename_comparison_key,
    parse_csv_as_rows,
    validate_file,
)
from src.paths import configured_path
from src.vector_store.contracts import VectorStore
from src.vector_store.models import (
    DocumentReplacement,
    JsonValue,
    Payload,
    VectorRecord,
)
from src.vector_store.pagination import CursorError
from src.vector_store.strategy_payloads import schema_version, strategy


def _settings_path() -> Path:
    """Return the same settings location used by the settings API."""
    return configured_path("RAG_STUDIO_SETTINGS_PATH", "settings.enc.json")


# A single document can otherwise fan out into an unbounded embedding batch.
# This limit applies to both uploads and re-ingestion before any embeddings or
# Qdrant writes are attempted.
MAX_CHUNKS_PER_DOCUMENT = 10_000
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ingest", tags=["ingestion"])

# ============================================================
# In-memory progress tracking
# ============================================================

_progress_store: dict[str, dict[str, object]] = {}
_progress_lock = asyncio.Lock()


async def _set_progress(file_id: str, status: str, message: str = "") -> None:
    """Update ingestion progress for a file."""
    async with _progress_lock:
        _progress_store[file_id] = {
            "status": status,
            "message": message,
            "timestamp": time.time(),
        }


async def _get_progress(file_id: str) -> dict[str, object] | None:
    """Get ingestion progress for a file."""
    async with _progress_lock:
        return _progress_store.get(file_id)


# ============================================================
# Response Models
# ============================================================


class UploadResponse(BaseModel):
    """Response from POST /api/ingest/upload."""

    status: str
    file_id: str
    message: str = ""


class ProgressResponse(BaseModel):
    """Response from GET /api/ingest/progress/{file_id}."""

    file_id: str
    status: str  # "processing", "done", "error"
    message: str
    chunks_count: int | None = None
    error: str | None = None


class DocumentInfo(BaseModel):
    """Information about an ingested document."""

    doc_id: str
    filename: str
    chunks_count: int
    chunk_size: int = 0
    chunk_overlap: int = 0
    created_at: str
    strategy: str = "recursive"
    schema_version: int = 1


class DocumentsListResponse(BaseModel):
    """Response from GET /api/ingest/documents."""

    documents: list[DocumentInfo]
    total: int | None
    next_cursor: str | None
    truncated: bool


class ChunkInfo(BaseModel):
    """One chunk returned by the bounded listing API."""

    point_id: str
    chunk_index: int
    text: str
    token_count: int
    page: int | None


class ChunksListResponse(BaseModel):
    """Response from GET /api/ingest/documents/{doc_id}/chunks."""

    chunks: list[ChunkInfo]
    next_cursor: str | None
    truncated: bool


class DeleteResponse(BaseModel):
    """Response from DELETE endpoints."""

    status: str
    message: str
    deleted_count: int


class ErrorResponse(BaseModel):
    """Standard error response."""

    detail: str


class DuplicateResponse(BaseModel):
    """Response from POST /api/ingest/upload when a duplicate is detected (AC-001.8)."""

    status: str  # "duplicate"
    filename: str
    existing_chunks: int
    existing_size: int  # approximate KB of stored file
    stored_chunk_size: int  # chunk_size used for existing file
    stored_chunk_overlap: int  # chunk_overlap used for existing file
    new_file_size: int  # bytes of the uploaded file
    estimated_chunks: int  # chunks the new file would produce with current settings
    chunks_settings_changed: bool
    current_chunk_size: int = 512  # current active chunk_size setting
    current_chunk_overlap: int = 64  # current active chunk_overlap setting


class ReingestRequest(BaseModel):
    """Request schema for POST /api/ingest/reingest."""

    doc_id: str
    filename: str


class ReingestResponse(BaseModel):
    """Response schema for POST /api/ingest/reingest."""

    status: str
    file_id: str
    message: str = ""
    detail: str | None = None


class ChunkLimitExceededError(ValueError):
    """Raised when a document would exceed the ingestion chunk safety limit."""

    def __init__(self, chunk_count: int) -> None:
        super().__init__(
            f"Document produces {chunk_count} chunks, exceeding the maximum of "
            f"{MAX_CHUNKS_PER_DOCUMENT:,}. Reduce the document size or increase "
            "the chunk size and try again."
        )


# ============================================================
# Duplicate detection helpers (AC-001.8–001.10)
# ============================================================


def compute_sha256(content: bytes) -> str:
    """Compute the SHA-256 hex digest of file content.

    Args:
        content: Raw file bytes.

    Returns:
        Lowercase hex-encoded SHA-256 hash string.
    """
    return hashlib.sha256(content).hexdigest()


def generate_unique_filename(original_filename: str) -> str:
    """Generate a unique filename for 'Upload as new' action (AC-001.8).

    Appends (1), (2), etc. before the extension until a name
    not present in stored_files is found.

    Args:
        original_filename: The original filename (e.g., 'report.pdf').

    Returns:
        A unique filename (e.g., 'report (1).pdf').
    """
    stem = Path(original_filename).stem
    suffix = Path(original_filename).suffix
    candidate = original_filename
    counter = 1
    occupied = {
        filename_comparison_key(str(meta.get("original_filename", key)))
        for key, meta in stored_files.items()
    } | _pending_upload_names
    while filename_comparison_key(candidate) in occupied:
        candidate = f"{stem} ({counter}){suffix}"
        counter += 1
    return candidate


def _read_current_chunking_settings() -> ChunkingSettings:
    """Read the normalized chunking contract from persisted application settings."""
    settings_path = _settings_path()
    try:
        if settings_path.exists():
            data = json.loads(settings_path.read_text(encoding="utf-8"))
            return read_chunking_settings(data)
    except AttributeError:
        logger.debug("Could not read current chunk settings, using defaults.")
    except OSError:
        logger.debug("Could not read current chunk settings, using defaults.")
    except UnicodeError:
        logger.debug("Could not read current chunk settings, using defaults.")
    except json.JSONDecodeError:
        logger.debug("Could not read current chunk settings, using defaults.")
    return read_chunking_settings({})


def _get_current_chunk_settings() -> tuple[int, int]:
    """Return the legacy size tuple without discarding normalized settings internally."""
    settings = _read_current_chunking_settings()
    return settings.chunk_size, settings.chunk_overlap


_default_get_current_chunk_settings = _get_current_chunk_settings
_default_chunk_text = chunk_text


def _safe_int(value: object) -> int | None:
    """Convert to int, returning None for falsy/missing values.

    Args:
        value: Any value that might be an integer.

    Returns:
        The integer value if > 0, otherwise None.
    """
    if value is None:
        return None
    try:
        v = int(str(value))
        return v if v > 0 else None
    except (ValueError, TypeError):  # fmt: skip
        return None


def _normalized_durable_identity(
    strategy_name: str, persisted_schema: int
) -> tuple[str, int]:
    if persisted_schema != 1:
        return "recursive", 1
    return strategy({"strategy": strategy_name}), 1


def _listed_strategy(payload: Payload) -> str:
    if schema_version(payload) != 1:
        return "recursive"
    return strategy(payload)


def _listed_schema_version(payload: Payload) -> int:
    del payload
    return 1


async def get_stored_file(filename: str) -> dict[str, object] | None:
    """Get stored metadata for a filename (case-insensitive).

    Args:
        filename: The filename to look up.

    Returns:
        The stored metadata dict, or None if not found.
    """
    async with stored_files_lock:
        key = filename_comparison_key(filename)
        direct = stored_files.get(key)
        if direct is not None:
            return direct
        for legacy_key, metadata in stored_files.items():
            legacy_name = str(metadata.get("original_filename", legacy_key))
            if filename_comparison_key(legacy_name) == key:
                return metadata
        return None


async def store_file_metadata(
    filename: str,
    file_hash: str,
    chunk_count: int,
    chunk_size: int,
    chunk_overlap: int,
    doc_id: str | None = None,
    chunking_settings: ChunkingSettings | None = None,
    strategy_name: str | None = None,
    schema: int = 1,
    chunking_fingerprint: str | None = None,
    durable_settings: dict[str, JsonValue] | None = None,
) -> None:
    """Store metadata for an ingested file in the tracking dict.

    Args:
        filename: Original filename (preserves case for UUID generation).
        file_hash: SHA-256 hash of the file content.
        chunk_count: Number of chunks produced.
        chunk_size: Chunk size setting used during ingestion.
        chunk_overlap: Chunk overlap setting used during ingestion.
    """
    async with stored_files_lock:
        key = filename_comparison_key(filename)
        existing = stored_files.get(key)
        preserved_doc_id = doc_id or (
            str(existing["doc_id"])
            if existing is not None and "doc_id" in existing
            else str(make_document_doc_id(filename))
        )
        metadata: dict[str, object] = {
            "original_filename": filename,
            "doc_id": preserved_doc_id,
            "file_hash": file_hash,
            "chunk_count": chunk_count,
            "chunk_size": chunk_size,
            "chunk_overlap": chunk_overlap,
        }
        if chunking_settings is not None:
            metadata["chunking_strategy"] = chunking_settings.strategy
            metadata["chunking_fingerprint"] = chunking_settings.fingerprint
            metadata["chunking_settings"] = settings_payload(chunking_settings)
            metadata["schema_version"] = chunking_settings.schema_version
        if strategy_name is not None:
            metadata["chunking_strategy"] = strategy_name
        if chunking_fingerprint is not None:
            metadata["chunking_fingerprint"] = chunking_fingerprint
        if durable_settings is not None:
            metadata["chunking_settings"] = durable_settings
        metadata["schema_version"] = schema
        stored_files[key] = metadata


async def remove_stored_file(filename: str) -> bool:
    """Remove a file from the metadata tracking dict.

    Args:
        filename: The filename to remove.

    Returns:
        True if the file was found and removed, False otherwise.
    """
    async with stored_files_lock:
        key = filename_comparison_key(filename)
        if key in stored_files:
            del stored_files[key]
            return True
        for legacy_key, metadata in tuple(stored_files.items()):
            legacy_name = str(metadata.get("original_filename", legacy_key))
            if filename_comparison_key(legacy_name) == key:
                del stored_files[legacy_key]
                return True
        return False


async def get_document_info_from_store(
    vector_store: VectorStore,
    filename: str,
) -> dict[str, object] | None:
    """Read persisted duplicate metadata through the vector capability."""
    metadata = await vector_store.find_document(filename)
    if metadata is None:
        return None
    durable_strategy, durable_schema = _normalized_durable_identity(
        metadata.strategy, metadata.schema_version
    )
    durable_fingerprint = (
        metadata.chunking_fingerprint if metadata.schema_version == 1 else None
    )
    durable_settings = (
        dict(metadata.chunking_settings) if metadata.schema_version == 1 else {}
    )
    info: dict[str, object] = {
        "original_filename": metadata.filename,
        "doc_id": metadata.doc_id,
        "file_hash": metadata.file_hash,
        "chunk_count": metadata.chunk_count,
        "chunk_size": metadata.chunk_size,
        "chunk_overlap": metadata.chunk_overlap,
        "chunking_strategy": durable_strategy,
        "schema_version": durable_schema,
        "chunking_fingerprint": durable_fingerprint,
        "chunking_settings": durable_settings,
    }
    await store_file_metadata(
        filename=metadata.filename,
        file_hash=metadata.file_hash,
        chunk_count=metadata.chunk_count,
        chunk_size=metadata.chunk_size or 512,
        chunk_overlap=metadata.chunk_overlap or 64,
        doc_id=metadata.doc_id,
        strategy_name=durable_strategy,
        schema=durable_schema,
        chunking_fingerprint=durable_fingerprint,
        durable_settings=durable_settings,
    )
    return info


async def _record_ingestion_failure(
    file_id: str,
    code: str,
    stage: str,
    *,
    error_type: str | None = None,
) -> None:
    """Record a stable ingestion failure without user or exception text."""
    await _set_progress(file_id, "error", code)
    metadata: dict[str, object] = {"error": code, "stage": stage}
    if error_type is not None:
        metadata["error_type"] = error_type
    log_audit("upload", success=False, extra=metadata)
    logger.warning(
        "ingestion_failed stage=%s code=%s error_type=%s",
        stage,
        code,
        error_type or "none",
    )


# ============================================================
# Background ingestion task
# ============================================================


async def _ingest_file(
    file_id: str,
    file_path: str,
    original_filename: str,
    content_type: str | None,
    client: VectorStore,
    *,
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
    chunking_settings: ChunkingSettings | None = None,
    file_hash: str = "",
    doc_id: str | None = None,
    reservation_key: str | None = None,
    staged_raw_path: str | None = None,
    embedder: Embedder | None = None,
) -> None:
    """Background task entry point serialized by parent document ID.

    The lock spans parsing through metadata updates, not just the Qdrant
    request.  This keeps the final vectors and ``stored_files`` metadata from
    the same completed ingestion when upload and re-ingest overlap.
    """
    preserved_doc_id = doc_id or str(make_document_doc_id(original_filename))
    try:
        async with document_operation_lock(preserved_doc_id):
            await _ingest_file_locked(
                file_id=file_id,
                file_path=file_path,
                original_filename=original_filename,
                content_type=content_type,
                client=client,
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
                chunking_settings=chunking_settings,
                file_hash=file_hash,
                doc_id=preserved_doc_id,
                staged_raw_path=staged_raw_path,
                embedder=embedder,
            )
    finally:
        if reservation_key is not None:
            await release_upload_name(reservation_key)


async def _ingest_file_locked(
    file_id: str,
    file_path: str,
    original_filename: str,
    content_type: str | None,
    client: VectorStore,
    *,
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
    chunking_settings: ChunkingSettings | None = None,
    file_hash: str = "",
    doc_id: str | None = None,
    staged_raw_path: str | None = None,
    embedder: Embedder | None = None,
) -> None:
    """Parse, chunk, embed, and replace a document while its lock is held.

    Args:
        file_id: UUID for this ingestion job.
        file_path: Path to the temporary uploaded file.
        original_filename: Original filename from the upload.
        content_type: MIME type from HTTP upload.
        client: Qdrant async client.
        chunk_size: Maximum characters per chunk (from settings).
            If None, reads from current settings file.
        chunk_overlap: Character overlap between chunks (from settings).
            If None, reads from current settings file.
        file_hash: SHA-256 hex digest of the file content (for duplicate tracking).
    """
    chunking_settings = chunking_settings or _read_current_chunking_settings()
    if chunk_size is not None or chunk_overlap is not None:
        chunking_settings = chunking_settings.model_copy(
            update={
                "chunk_size": chunk_size or chunking_settings.chunk_size,
                "chunk_overlap": chunk_overlap
                if chunk_overlap is not None
                else chunking_settings.chunk_overlap,
            }
        )
    chunk_size = chunking_settings.chunk_size
    chunk_overlap = chunking_settings.chunk_overlap

    try:
        await _set_progress(file_id, "processing", "Parsing document...")

        preserved_doc_id = doc_id or str(make_document_doc_id(original_filename))

        # Detect file type
        ext = detect_file_type(original_filename, content_type)

        # Parse the file
        if ext == ".csv":
            await _set_progress(file_id, "processing", "Parsing CSV rows...")
            row_texts, row_metadata = parse_csv_as_rows(file_path)
            batch = dispatch_csv(row_texts, chunking_settings, preserved_doc_id)
            csv_meta = row_metadata  # Pass row metadata to upsert
            extra_payload: list[dict[str, object]] | None = csv_meta
        else:
            await _set_progress(file_id, "processing", "Parsing document text...")
            text, _ = detect_and_parse(file_path, original_filename, content_type)
            if (
                chunking_settings.strategy == "recursive"
                and chunk_text is not _default_chunk_text
            ):
                compatibility_chunks = chunk_text(
                    text, chunk_size=chunk_size, chunk_overlap=chunk_overlap
                )
                if len(compatibility_chunks) > MAX_CHUNKS_PER_DOCUMENT:
                    raise ChunkLimitExceededError(len(compatibility_chunks))
            batch = dispatch_text(text, chunking_settings, preserved_doc_id)
            extra_payload = None

        chunks = list(batch.texts)

        if not chunks:
            await _set_progress(
                file_id, "error", "No text chunks generated from document."
            )
            log_audit(
                "upload",
                filename=original_filename,
                success=False,
                extra={"error": "no_chunks"},
            )
            return

        if len(chunks) > MAX_CHUNKS_PER_DOCUMENT:
            raise ChunkLimitExceededError(len(chunks))

        await _set_progress(
            file_id, "processing", f"Generating embeddings for {len(chunks)} chunks..."
        )

        selected_embedder = embedder or get_embedder()
        dense_vectors = selected_embedder.embed_dense(chunks)
        sparse_vectors = selected_embedder.embed_sparse(chunks)
        created_at = datetime.now(UTC).isoformat()
        records: list[VectorRecord] = []
        for index, chunk in enumerate(chunks):
            payload: dict[str, JsonValue] = {
                "text": chunk,
                "source": original_filename,
                "chunk_index": index,
                "total_chunks": len(chunks),
                "doc_id": preserved_doc_id,
                "created_at": created_at,
                "file_hash": file_hash,
                "chunk_size": chunk_size,
                "chunk_overlap": chunk_overlap,
            }
            payload.update(unit_payload(batch, batch.units[index]))
            if extra_payload is not None and index < len(extra_payload):
                csv_metadata = extra_payload[index]
                csv_headers = csv_metadata.get("csv_headers")
                if isinstance(csv_headers, list):
                    payload["csv_headers"] = [str(value) for value in csv_headers]
                csv_row_data = csv_metadata.get("csv_row_data")
                if isinstance(csv_row_data, dict):
                    payload["csv_row_data"] = {
                        str(key): None if value is None else str(value)
                        for key, value in csv_row_data.items()
                    }
                row_index = csv_metadata.get("row_index")
                if isinstance(row_index, (str, int, float, bool)):
                    payload["row_index"] = row_index
            records.append(
                VectorRecord(
                    point_id=make_doc_id(original_filename, index),
                    dense=dense_vectors[index],
                    sparse=sparse_vectors[index],
                    payload=payload,
                )
            )
        await client.replace_document(
            DocumentReplacement(
                doc_id=preserved_doc_id,
                filename=original_filename,
                records=tuple(records),
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
                created_at=created_at,
                strategy=batch.strategy,
                schema_version=chunking_settings.schema_version,
                file_hash=file_hash,
                chunking_fingerprint=chunking_settings.fingerprint,
                chunking_settings=settings_payload(chunking_settings),
            )
        )
        if staged_raw_path is not None:
            raw_path = _raw_uploads_dir() / (
                f"{preserved_doc_id}{Path(original_filename).suffix}"
            )
            Path(staged_raw_path).replace(raw_path)

        await _set_progress(
            file_id,
            "done",
            f"Ingested {len(chunks)} chunks from '{original_filename}'",
        )

        # Add chunks_count to progress for easy retrieval
        async with _progress_lock:
            if file_id in _progress_store:
                _progress_store[file_id]["chunks_count"] = len(chunks)

        log_audit(
            "upload",
            filename=original_filename,
            success=True,
            extra={"chunks": len(chunks), "file_id": file_id},
        )

        # Store file metadata for duplicate detection (AC-001.8–001.10)
        if file_hash:
            await store_file_metadata(
                filename=original_filename,
                file_hash=file_hash,
                chunk_count=len(chunks),
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
                doc_id=preserved_doc_id,
                chunking_settings=chunking_settings,
                strategy_name=batch.strategy,
            )

        logger.info("ingestion_completed chunk_count=%d", len(chunks))

    except UnsupportedCsvEncodingError:
        await _record_ingestion_failure(
            file_id, "unsupported_csv_encoding", "csv_decode"
        )
    except ChunkLimitExceededError as error:
        await _record_ingestion_failure(file_id, str(error), "chunk_limit")
    except ChunkingLimitExceeded as error:
        limit_error = ChunkLimitExceededError(error.max_units + 1)
        await _record_ingestion_failure(file_id, str(limit_error), "chunk_limit")
    except ValueError:
        await _record_ingestion_failure(file_id, "ingestion_invalid_document", "parse")
    except asyncio.CancelledError:
        raise
    except Exception as error:  # noqa: BLE001 -- background boundary records safe metadata
        await _record_ingestion_failure(
            file_id,
            "ingestion_failed",
            "background",
            error_type=type(error).__name__,
        )
    finally:
        # Clean up temp file (raw copy persists in data/raw_uploads/)
        try:
            Path(file_path).unlink(missing_ok=True)
            if staged_raw_path is not None:
                Path(staged_raw_path).unlink(missing_ok=True)
        except OSError as exc:
            logger.warning(
                "Could not remove ingestion temp file (%s)", type(exc).__name__
            )


# ============================================================
# Routes
# ============================================================


@router.post(
    "/upload",
    responses={
        202: {"description": "File accepted for ingestion"},
        200: {"description": "Upload cancelled or file unchanged"},
        409: {"model": DuplicateResponse, "description": "Duplicate file detected"},
    },
)
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),  # noqa: B008 - FastAPI declaration marker, not an eager application call
    action: str = "default",
    client: VectorStore = Depends(get_vector_store),  # noqa: B008 - FastAPI dependency marker
    embedder: Embedder = Depends(get_embedder),  # noqa: B008
) -> Response:
    """Upload a document for ingestion (AC-001.1, AC-001.5, AC-001.6, AC-001.7, AC-001.8–001.10).

    Accepts .txt, .md, .pdf, .docx, .csv files up to 50 MB.
    Returns 202 Accepted immediately; processing happens in the background.

    Query Parameters:
        action: One of 'default', 'replace', 'cancel', 'rename' (AC-001.8).
            - 'default': Normal upload; returns 409 Conflict if duplicate detected.
            - 'replace': Delete existing and re-ingest with current settings.
            - 'cancel': Acknowledge cancellation, no ingestion performed.
            - 'rename': Auto-generate unique filename and ingest as new document.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided.")

    try:
        original_filename = canonicalize_filename(file.filename)
    except ValueError:
        log_audit(
            "upload",
            success=False,
            extra={"error": "invalid_filename"},
        )
        raise HTTPException(status_code=400, detail="Invalid filename") from None

    # Read file content
    content = await file.read()

    # Validate file (AC-001.7)
    try:
        validate_file(
            filename=original_filename,
            file_size=len(content),
            content=content,
        )
    except ValueError as e:
        log_audit(
            "upload",
            filename=original_filename,
            success=False,
            extra={"error": str(e)},
        )
        raise HTTPException(status_code=400, detail=str(e))

    # Validate file type
    try:
        detect_file_type(original_filename, file.content_type)
    except ValueError as e:
        log_audit(
            "upload",
            filename=original_filename,
            success=False,
            extra={"error": str(e)},
        )
        raise HTTPException(status_code=400, detail=str(e))

    new_hash = compute_sha256(content)
    stored = await get_stored_file(original_filename)
    logger.info("duplicate_check memory_hit=%s", stored is not None)

    # Fallback: if not in memory (e.g., after server restart), check Qdrant
    in_memory_before_fallback = stored is not None
    if stored is None:
        stored = await get_document_info_from_store(client, original_filename)
        logger.info("duplicate_check persistent_hit=%s", stored is not None)

    logger.info("duplicate_check in_memory=%s", in_memory_before_fallback)

    # --- Handle action parameter (AC-001.8) ---

    if action == "cancel":
        # User chose "Cancel Upload" from the duplicate modal
        logger.info("upload_decision action=cancel")
        log_audit(
            "upload",
            filename=original_filename,
            success=True,
            extra={"action": "cancel", "reason": "duplicate_cancelled"},
        )
        return Response(
            content=UploadResponse(
                status="cancelled",
                file_id="",
                message=f"Upload of '{original_filename}' cancelled by user.",
            ).model_dump_json(),
            status_code=200,
            media_type="application/json",
        )

    if action == "replace" and stored is not None:
        # The background operation deletes and upserts while holding the
        # per-document lock.  Deleting here would race that operation (or a
        # concurrent re-ingest) and can leave the document temporarily empty.
        logger.info("upload_decision action=replace")

    current_chunking = _read_current_chunking_settings()
    if _get_current_chunk_settings is not _default_get_current_chunk_settings:
        compatibility_size, compatibility_overlap = _get_current_chunk_settings()
        current_chunking = current_chunking.model_copy(
            update={
                "chunk_size": compatibility_size,
                "chunk_overlap": compatibility_overlap,
            }
        )

    # --- Duplicate detection (AC-001.8) ---
    if action == "default" and stored is not None:
        # If the stored entry has chunk_count == 0, it's a stale placeholder
        # from a previous failed upload. Treat as not a duplicate — proceed.
        stored_chunk_count = int(str(stored.get("chunk_count", 0)))
        if stored_chunk_count == 0:
            logger.info("duplicate_check stale_entry=true")
            await remove_stored_file(original_filename)
            stored = None  # Clear the stale reference so no duplicate logic fires

    if action == "default" and stored is not None:
        existing_hash = str(stored.get("file_hash", ""))

        # Read raw stored values and normalize: treat None/0 as unknown (use defaults).
        # Old stored_files entries may have chunk_size=0 from before the _safe_int fix.
        stored_chunk_size_raw = stored.get("chunk_size")
        stored_chunk_overlap_raw = stored.get("chunk_overlap")
        stored_has_chunk_settings = (
            _safe_int(stored_chunk_size_raw) is not None
            and _safe_int(stored_chunk_overlap_raw) is not None
        )
        stored_chunk_size = (
            int(stored_chunk_size_raw)
            if isinstance(stored_chunk_size_raw, (int, float, str))
            and int(stored_chunk_size_raw) > 0
            else 512
        )
        stored_chunk_overlap = (
            int(stored_chunk_overlap_raw)
            if isinstance(stored_chunk_overlap_raw, (int, float, str))
            and int(stored_chunk_overlap_raw) > 0
            else 64
        )

        current_cs = current_chunking.chunk_size
        current_co = current_chunking.chunk_overlap
        stored_fingerprint = stored.get("chunking_fingerprint")
        settings_changed = (
            stored_fingerprint != current_chunking.fingerprint
            if isinstance(stored_fingerprint, str) and stored_fingerprint
            else stored_has_chunk_settings
            and (stored_chunk_size != current_cs or stored_chunk_overlap != current_co)
        )
        logger.info(
            "SETTINGS COMPARISON: stored=(cs=%s, co=%s), current=(cs=%s, co=%s), changed=%s",
            stored_chunk_size,
            stored_chunk_overlap,
            current_cs,
            current_co,
            settings_changed,
        )

        # Same filename exists — check if hash matches for fast path
        if existing_hash == new_hash and not settings_changed:
            # Byte-for-byte identical AND settings unchanged — skip ingestion (AC-001.10)
            logger.info("duplicate_check outcome=unchanged")
            return Response(
                content=UploadResponse(
                    status="unchanged",
                    file_id="",
                    message="File content is identical; no re-ingestion needed.",
                ).model_dump_json(),
                status_code=200,
                media_type="application/json",
            )

        # Populate duplicate response for the modal
        existing_chunks = int(str(stored.get("chunk_count", 0)))

        # Estimate chunks the new file would produce with current settings
        # by running the chunker without storing results (AC-001.9)
        estimated_chunks = 0
        try:
            estimate_id = str(uuid.uuid4())
            est_suffix = Path(original_filename).suffix
            estimate_path = (
                Path(tempfile.gettempdir()) / f"rag-est-{estimate_id}{est_suffix}"
            )
            estimate_path.write_bytes(content)
            try:
                text, _ = detect_and_parse(
                    str(estimate_path), original_filename, file.content_type
                )
                if text.strip():
                    temp_chunks = chunk_text(
                        text, chunk_size=current_cs, chunk_overlap=current_co
                    )
                    estimated_chunks = len(temp_chunks)
            finally:
                estimate_path.unlink(missing_ok=True)
        except OSError:
            estimated_chunks = 0
        except UnicodeError:
            estimated_chunks = 0
        except ValueError:
            estimated_chunks = 0

        # Approximate existing file size (not stored; use 0 if unknown)
        existing_size = int(str(stored.get("file_size", 0)))

        logger.info("duplicate_check outcome=conflict")
        return Response(
            content=DuplicateResponse(
                status="duplicate",
                filename=original_filename,
                existing_chunks=existing_chunks,
                existing_size=existing_size,
                stored_chunk_size=stored_chunk_size,
                stored_chunk_overlap=stored_chunk_overlap,
                new_file_size=len(content),
                estimated_chunks=estimated_chunks,
                chunks_settings_changed=settings_changed,
                current_chunk_size=current_cs,
                current_chunk_overlap=current_co,
            ).model_dump_json(),
            status_code=409,
            media_type="application/json",
        )

    logger.info("duplicate_check outcome=processing action=%s", action)

    # Generate a unique file_id for this ingestion job
    file_id = str(uuid.uuid4())
    await _set_progress(file_id, "processing", "File received for admission.")
    try:
        original_filename = await reserve_upload_name(
            original_filename,
            rename=action == "rename",
            allow_stored=action == "replace",
        )
    except FilenameReservedError:
        raise HTTPException(
            status_code=409,
            detail="A document with this filename is already pending or stored.",
        ) from None
    except UploadCapacityError:
        raise HTTPException(
            status_code=429,
            detail="Upload capacity reached. Retry after a pending upload completes.",
        ) from None

    reservation_key = filename_comparison_key(original_filename)

    # Write file to temp location
    suffix = Path(original_filename).suffix
    tmp_path = Path(tempfile.gettempdir()) / f"rag-studio-{file_id}{suffix}"
    preserved_doc_id = (
        str(
            stored.get(
                "doc_id",
                make_document_doc_id(
                    str(stored.get("original_filename", original_filename))
                ),
            )
        )
        if action == "replace" and stored is not None
        else str(make_document_doc_id(original_filename))
    )
    raw_uploads_dir = _raw_uploads_dir()
    staged_raw_path = raw_uploads_dir / f".{file_id}.pending"
    try:
        tmp_path.write_bytes(content)
        raw_uploads_dir.mkdir(parents=True, exist_ok=True)
        staged_raw_path.write_bytes(content)
    except OSError as error:
        tmp_path.unlink(missing_ok=True)
        staged_raw_path.unlink(missing_ok=True)
        await release_upload_name(reservation_key)
        raise HTTPException(
            status_code=500, detail="Could not stage upload."
        ) from error

    # Schedule background ingestion — pass current chunk settings
    background_tasks.add_task(
        _ingest_file,
        file_id=file_id,
        file_path=str(tmp_path),
        original_filename=original_filename,
        content_type=file.content_type,
        client=client,
        file_hash=new_hash,
        chunking_settings=current_chunking,
        doc_id=preserved_doc_id,
        reservation_key=reservation_key,
        staged_raw_path=str(staged_raw_path),
        embedder=embedder,
    )

    logger.info("upload_admitted action=%s size_bytes=%d", action, len(content))

    return Response(
        content=UploadResponse(
            status="processing",
            file_id=file_id,
            message=f"File '{original_filename}' accepted. Check progress at /api/ingest/progress/{file_id}",
        ).model_dump_json(),
        status_code=202,
        media_type="application/json",
    )


@router.get("/progress/{file_id}", response_model=ProgressResponse)
async def get_ingestion_progress(file_id: str) -> ProgressResponse:
    """Get the ingestion progress for a file (AC-001.1 progress bar).

    Args:
        file_id: The file ID returned by POST /api/ingest/upload.

    Returns:
        Current progress status with optional chunks_count and error.
    """
    progress = await _get_progress(file_id)
    if progress is None:
        raise HTTPException(
            status_code=404, detail=f"No ingestion job found for file_id: {file_id}"
        )

    chunks_count_raw = progress.get("chunks_count")
    chunks_count: int | None = (
        int(chunks_count_raw) if isinstance(chunks_count_raw, (int, float)) else None
    )

    return ProgressResponse(
        file_id=file_id,
        status=str(progress.get("status", "unknown")),
        message=str(progress.get("message", "")),
        chunks_count=chunks_count,
        error=str(progress.get("message", ""))
        if progress.get("status") == "error"
        else None,
    )


@router.get("/documents", response_model=DocumentsListResponse)
async def list_documents(
    cursor: str | None = None,
    client: VectorStore = Depends(get_vector_store),  # noqa: B008
) -> DocumentsListResponse:
    """List one bounded snapshot page of ingested documents."""
    try:
        page = await client.list_documents(cursor)
    except CursorError:
        raise HTTPException(
            status_code=422, detail="Invalid or expired cursor"
        ) from None
    documents = [
        DocumentInfo(
            doc_id=str(point.payload.get("doc_id", "")),
            filename=str(point.payload.get("source", "unknown")),
            chunks_count=int(str(point.payload.get("total_chunks", 0))),
            chunk_size=int(str(point.payload.get("chunk_size", 0))),
            chunk_overlap=int(str(point.payload.get("chunk_overlap", 0))),
            created_at=str(point.payload.get("created_at", "")),
            strategy=_listed_strategy(point.payload),
            schema_version=_listed_schema_version(point.payload),
        )
        for point in page.items
    ]
    return DocumentsListResponse(
        documents=documents,
        total=None if page.truncated else page.matched_items,
        next_cursor=page.next_cursor,
        truncated=page.truncated,
    )


@router.get("/documents/{doc_id}/chunks", response_model=ChunksListResponse)
async def get_document_chunks(
    doc_id: str,
    cursor: str | None = None,
    client: VectorStore = Depends(get_vector_store),  # noqa: B008
) -> ChunksListResponse:
    """Get one bounded snapshot page of chunks for a document."""
    try:
        result = await client.list_chunks(doc_id, cursor)
    except CursorError:
        raise HTTPException(
            status_code=422, detail="Invalid or expired cursor"
        ) from None
    if not result.items and cursor is None:
        raise HTTPException(status_code=404, detail="No chunks found for document")
    chunks: list[ChunkInfo] = []
    for point in result.items:
        text_value = str(point.payload.get("text", ""))
        raw_page = point.payload.get("page")
        chunks.append(
            ChunkInfo(
                point_id=point.point_id,
                chunk_index=int(str(point.payload.get("chunk_index", 0))),
                text=text_value,
                token_count=int(
                    str(point.payload.get("token_count", len(text_value.split())))
                ),
                page=int(str(raw_page)) if raw_page is not None else None,
            )
        )
    return ChunksListResponse(
        chunks=chunks,
        next_cursor=result.next_cursor,
        truncated=result.truncated,
    )


@router.delete("/documents/{file_id}", response_model=DeleteResponse)
async def delete_document(
    file_id: str,
    client: VectorStore = Depends(get_vector_store),  # noqa: B008
) -> DeleteResponse:
    """Delete all chunks for a specific document by domain ID."""
    async with document_operation_lock(file_id):
        deleted = await client.delete_document(file_id)
        filenames_to_remove: list[str] = []
        async with stored_files_lock:
            for key, meta in stored_files.items():
                original_name = str(meta.get("original_filename", key))
                if str(make_document_doc_id(original_name)) == file_id:
                    filenames_to_remove.append(key)
        for key in filenames_to_remove:
            await remove_stored_file(key)
    log_audit("delete_document", success=True, extra={"deleted_count": deleted})
    return DeleteResponse(
        status="ok",
        message=f"Deleted {deleted} chunks for document",
        deleted_count=deleted,
    )


@router.delete("/clear", response_model=DeleteResponse)
async def clear_all_documents(
    client: VectorStore = Depends(get_vector_store),  # noqa: B008
) -> DeleteResponse:
    """Clear all document vectors through the application capability."""
    try:
        count = await client.clear_documents()
    except asyncio.CancelledError:
        raise
    except Exception as error:  # noqa: BLE001 -- HTTP boundary maps safe stable failure
        logger.warning("clear_documents_failed error_type=%s", type(error).__name__)
        raise HTTPException(
            status_code=500, detail="Failed to clear collection"
        ) from None
    async with stored_files_lock:
        stored_files.clear()
    log_audit("clear_all", success=True, extra={"deleted_count": count})
    return DeleteResponse(
        status="ok",
        message=f"Cleared all documents. Deleted {count} chunks.",
        deleted_count=count,
    )


@router.post("/reingest", response_model=ReingestResponse, status_code=202)
async def reingest_document(
    request: ReingestRequest,
    background_tasks: BackgroundTasks,
    response: Response,
    client: VectorStore = Depends(get_vector_store),  # noqa: B008 - FastAPI dependency marker
    embedder: Embedder = Depends(get_embedder),  # noqa: B008
) -> ReingestResponse:
    """Re-ingest a document from the raw uploads store (AC-010.4).

    Reads the stored file from data/raw_uploads/ using the original file's
    extension from the filename, re-processes it with the current chunk
    settings, and returns a new file_id for progress tracking.

    Args:
        request: ReingestRequest with doc_id and filename.
        background_tasks: FastAPI background tasks for async ingestion.
        client: Qdrant async client.

    Returns:
        ReingestResponse with new file_id and status.
    """
    try:
        canonical_filename = canonicalize_filename(request.filename)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid filename") from None

    # Read the current normalized contract while preserving legacy size callers.
    current_chunking = _read_current_chunking_settings()

    # Find the stored file in data/raw_uploads/ by doc_id.
    # Files are stored as {doc_id}{suffix} during upload (BUG-010-1 fix).
    suffix = Path(canonical_filename).suffix
    raw_path = _raw_uploads_dir() / f"{request.doc_id}{suffix}"

    if not raw_path.exists():
        logger.warning("reingest_source_missing")
        response.status_code = 200
        return ReingestResponse(
            status="skipped",
            file_id=request.doc_id,
            message=f"Source file for '{canonical_filename}' no longer available. Skipping.",
            detail=f"Stored file no longer exists: {raw_path.name}",
        )

    # Generate a new file_id for this ingestion job
    file_id = str(uuid.uuid4())

    # Copy the raw file to temp location for processing
    tmp_path = Path(tempfile.gettempdir()) / f"rag-studio-reingest-{file_id}{suffix}"
    shutil.copy2(str(raw_path), str(tmp_path))

    # Initialize progress
    await _set_progress(file_id, "processing", "Re-ingestion started...")

    # Preserve accurate duplicate metadata after re-ingestion.  Without the
    # hash, a completed re-ingest could leave metadata from an older upload.
    file_hash = compute_sha256(raw_path.read_bytes())

    # Schedule background ingestion with current chunk settings
    background_tasks.add_task(
        _ingest_file,
        file_id=file_id,
        file_path=str(tmp_path),
        original_filename=canonical_filename,
        content_type=None,
        client=client,
        chunking_settings=current_chunking,
        file_hash=file_hash,
        embedder=embedder,
    )

    logger.info(
        "reingest_queued chunk_size=%d chunk_overlap=%d",
        current_chunking.chunk_size,
        current_chunking.chunk_overlap,
    )

    return ReingestResponse(
        status="processing",
        file_id=file_id,
        message=f"Re-ingestion of '{canonical_filename}' started. Check progress at /api/ingest/progress/{file_id}",
    )
