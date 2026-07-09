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
import logging
import shutil
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, cast

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
from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models as qmodels

from src.api.dependencies import get_qdrant_client, log_audit
from src.ingestion.chunker import chunk_csv_rows, chunk_text
from src.ingestion.embedder import (
    COLLECTION_NAME,
    delete_document_points,
    ensure_collection_exists,
    generate_dense_embeddings,
    generate_sparse_embeddings,
    make_document_doc_id,
    upsert_chunks,
)
from src.ingestion.parser import (
    detect_and_parse,
    detect_file_type,
    parse_csv_as_rows,
    validate_file,
)

# Directory for storing raw uploads for re-ingestion
_RAW_UPLOADS_DIR = Path("data/raw_uploads")

# In-memory store of ingested file metadata for duplicate detection (AC-001.8–001.10)
# Key: normalized filename (lowercase), Value: dict with hash, chunk_settings, chunk_count
stored_files: dict[str, dict[str, object]] = {}
stored_files_lock = asyncio.Lock()

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


class DocumentsListResponse(BaseModel):
    """Response from GET /api/ingest/documents."""

    documents: list[DocumentInfo]
    total: int


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
    while candidate.lower() in stored_files:
        candidate = f"{stem} ({counter}){suffix}"
        counter += 1
    return candidate


def _get_current_chunk_settings() -> tuple[int, int]:
    """Read current chunk_size and chunk_overlap from the settings file.

    Returns (512, 64) as defaults if the settings file is not found
    or the keys are missing.

    Returns:
        A tuple of (chunk_size, chunk_overlap).
    """
    import json

    settings_path = Path("data/settings.enc.json")
    try:
        if settings_path.exists():
            data = json.loads(settings_path.read_text(encoding="utf-8"))
            return (
                int(data.get("chunk_size", 512)),
                int(data.get("chunk_overlap", 64)),
            )
    except Exception:
        logger.debug("Could not read current chunk settings, using defaults.")
    return (512, 64)


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
    except ValueError, TypeError:
        return None


async def get_stored_file(filename: str) -> dict[str, object] | None:
    """Get stored metadata for a filename (case-insensitive).

    Args:
        filename: The filename to look up.

    Returns:
        The stored metadata dict, or None if not found.
    """
    async with stored_files_lock:
        return stored_files.get(filename.lower())


async def store_file_metadata(
    filename: str,
    file_hash: str,
    chunk_count: int,
    chunk_size: int,
    chunk_overlap: int,
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
        stored_files[filename.lower()] = {
            "original_filename": filename,
            "file_hash": file_hash,
            "chunk_count": chunk_count,
            "chunk_size": chunk_size,
            "chunk_overlap": chunk_overlap,
        }


async def remove_stored_file(filename: str) -> bool:
    """Remove a file from the metadata tracking dict.

    Args:
        filename: The filename to remove.

    Returns:
        True if the file was found and removed, False otherwise.
    """
    async with stored_files_lock:
        key = filename.lower()
        if key in stored_files:
            del stored_files[key]
            return True
        return False


async def get_document_info_from_qdrant(
    client: AsyncQdrantClient,
    filename: str,
) -> dict[str, object] | None:
    """Query Qdrant for existing document metadata (fallback when stored_files is cold).

    Used after server restart when the in-memory stored_files dict is empty
    but documents exist in Qdrant.

    Args:
        client: AsyncQdrantClient instance.
        filename: Original filename to look up.

    Returns:
        Dict with file_hash, chunk_count, chunk_size, chunk_overlap,
        or None if no points found for this doc_id.
    """
    await ensure_collection_exists(client)
    doc_id = make_document_doc_id(filename)

    try:
        count_result = await client.count(
            collection_name=COLLECTION_NAME,
            count_filter=qmodels.Filter(
                must=[
                    qmodels.FieldCondition(
                        key="doc_id",
                        match=qmodels.MatchValue(value=doc_id),
                    ),
                ],
            ),
            exact=True,
        )
    except Exception:
        logger.debug("Qdrant count failed for doc_id=%s", doc_id)
        return None

    if count_result.count == 0:
        return None

    # Fetch one point to get chunk metadata
    scroll_result, _ = await client.scroll(
        collection_name=COLLECTION_NAME,
        scroll_filter=qmodels.Filter(
            must=[
                qmodels.FieldCondition(
                    key="doc_id",
                    match=qmodels.MatchValue(value=doc_id),
                ),
            ],
        ),
        limit=1,
        with_payload=True,
        with_vectors=False,
    )

    if not scroll_result:
        return None

    payload = scroll_result[0].payload or {}

    # Use _safe_int to treat missing/zero chunk settings as unknown (None).
    # Old documents in Qdrant may lack chunk_size/chunk_overlap fields.
    cs_val = _safe_int(payload.get("chunk_size"))
    co_val = _safe_int(payload.get("chunk_overlap"))

    info: dict[str, object] = {
        "original_filename": filename,
        "file_hash": str(payload.get("file_hash", "")),
        "chunk_count": payload.get("total_chunks", count_result.count),
        "chunk_size": cs_val if cs_val is not None else 0,
        "chunk_overlap": co_val if co_val is not None else 0,
    }

    # Cache in stored_files with normalized defaults for unknown values.
    # This prevents stale 0-values from triggering false chunk-settings-changed warnings.
    await store_file_metadata(
        filename=filename,
        file_hash=str(info["file_hash"]),
        chunk_count=int(str(info["chunk_count"])),
        chunk_size=cs_val if cs_val is not None else 512,
        chunk_overlap=co_val if co_val is not None else 64,
    )

    return info


# ============================================================
# Background ingestion task
# ============================================================


async def _ingest_file(
    file_id: str,
    file_path: str,
    original_filename: str,
    content_type: str | None,
    client: AsyncQdrantClient,
    *,
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
    file_hash: str = "",
) -> None:
    """Background task: parse, chunk, embed, and upsert a file.

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
    # Read current settings if not explicitly provided
    if chunk_size is None or chunk_overlap is None:
        _cs, _co = _get_current_chunk_settings()
        if chunk_size is None:
            chunk_size = _cs
        if chunk_overlap is None:
            chunk_overlap = _co

    try:
        await _set_progress(file_id, "processing", "Parsing document...")

        # Ensure collection exists
        await ensure_collection_exists(client)

        # Generate document UUID5
        doc_id = make_document_doc_id(original_filename)

        # Detect file type
        ext = detect_file_type(original_filename, content_type)

        # Parse the file
        if ext == ".csv":
            await _set_progress(file_id, "processing", "Parsing CSV rows...")
            row_texts, row_metadata = parse_csv_as_rows(file_path)
            chunks = chunk_csv_rows(row_texts, chunk_size=chunk_size)
            csv_meta = row_metadata  # Pass row metadata to upsert
            extra_payload: list[dict[str, object]] | None = csv_meta
        else:
            await _set_progress(file_id, "processing", "Parsing document text...")
            text, _ = detect_and_parse(file_path, original_filename, content_type)
            chunks = chunk_text(
                text, chunk_size=chunk_size, chunk_overlap=chunk_overlap
            )
            extra_payload = None

        if not chunks:
            await _set_progress(
                file_id, "error", "No text chunks generated from document."
            )
            # Remove stale stored_files entry so re-upload is not blocked
            await remove_stored_file(original_filename)
            log_audit(
                "upload",
                filename=original_filename,
                success=False,
                extra={"error": "no_chunks"},
            )
            return

        await _set_progress(
            file_id, "processing", f"Generating embeddings for {len(chunks)} chunks..."
        )

        # Generate embeddings
        dense_vectors = generate_dense_embeddings(chunks)
        sparse_vectors = generate_sparse_embeddings(chunks)

        await _set_progress(file_id, "processing", "Storing vectors in Qdrant...")

        # Upsert to Qdrant
        await upsert_chunks(
            client=client,
            filename=original_filename,
            doc_id=doc_id,
            chunks=chunks,
            dense_vectors=dense_vectors,
            sparse_vectors=sparse_vectors,
            extra_payloads=extra_payload,
            file_hash=file_hash,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )

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
            )

        logger.info(
            "Successfully ingested '%s': %d chunks, doc_id=%s",
            original_filename,
            len(chunks),
            doc_id,
        )

    except ValueError as e:
        error_msg = str(e)
        await _set_progress(file_id, "error", error_msg)
        # Remove stale stored_files entry so re-upload is not blocked
        await remove_stored_file(original_filename)
        log_audit(
            "upload",
            filename=original_filename,
            success=False,
            extra={"error": error_msg},
        )
        logger.warning("Ingestion failed for '%s': %s", original_filename, error_msg)

    except Exception as e:
        error_msg = f"Unexpected error: {e}"
        await _set_progress(file_id, "error", error_msg)
        # Remove stale stored_files entry so re-upload is not blocked
        await remove_stored_file(original_filename)
        log_audit(
            "upload",
            filename=original_filename,
            success=False,
            extra={"error": str(e)},
        )
        logger.exception("Ingestion failed for '%s'", original_filename)

    finally:
        # Clean up temp file (raw copy persists in data/raw_uploads/)
        try:
            Path(file_path).unlink(missing_ok=True)
        except Exception:
            pass


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
    file: UploadFile = File(...),
    action: str = "default",
    client: AsyncQdrantClient = Depends(get_qdrant_client),
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

    original_filename = file.filename

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
    logger.info(
        "Duplicate check: get_stored_file('%s') → %s",
        original_filename,
        "found" if stored else "NOT FOUND",
    )

    # Fallback: if not in memory (e.g., after server restart), check Qdrant
    in_memory_before_fallback = stored is not None
    if stored is None:
        stored = await get_document_info_from_qdrant(client, original_filename)
        logger.info(
            "Duplicate check: get_document_info_from_qdrant('%s') → %s",
            original_filename,
            "found" if stored else "NOT FOUND",
        )

    logger.info(
        "DUPLICATE CHECK: filename='%s', in_memory=%s, hash=%s",
        original_filename,
        in_memory_before_fallback,
        new_hash[:12],
    )

    # --- Handle action parameter (AC-001.8) ---

    if action == "cancel":
        # User chose "Cancel Upload" from the duplicate modal
        logger.info("Upload decision: action=cancel for filename=%s", original_filename)
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

    if action == "rename":
        # User chose "Upload as new" — generate a unique name
        original_filename = generate_unique_filename(original_filename)
        logger.info("Renamed duplicate file to: %s", original_filename)

    if action == "replace" and stored is not None:
        # User chose "Replace" — delete existing points first
        doc_id = make_document_doc_id(original_filename)
        deleted = await delete_document_points(client, doc_id)
        await remove_stored_file(original_filename)
        logger.info(
            "Replace action: deleted %d existing points for doc_id=%s", deleted, doc_id
        )

    # --- Duplicate detection (AC-001.8) ---
    if action == "default" and stored is not None:
        # If the stored entry has chunk_count == 0, it's a stale placeholder
        # from a previous failed upload. Treat as not a duplicate — proceed.
        stored_chunk_count = int(str(stored.get("chunk_count", 0)))
        if stored_chunk_count == 0:
            logger.info(
                "DUPLICATE CHECK: stale entry (chunk_count=0) for '%s' — "
                "removing and proceeding with fresh upload",
                original_filename,
            )
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

        # Read current chunk settings to detect changes
        current_cs, current_co = _get_current_chunk_settings()
        settings_changed = stored_has_chunk_settings and (
            stored_chunk_size != current_cs or stored_chunk_overlap != current_co
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
            logger.info(
                "DUPLICATE CHECK: 200 UNCHANGED — filename='%s', hash=%s matches existing",
                original_filename,
                new_hash[:12],
            )
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
        except Exception:
            estimated_chunks = 0

        # Approximate existing file size (not stored; use 0 if unknown)
        existing_size = int(str(stored.get("file_size", 0)))

        logger.info(
            "DUPLICATE CHECK: 409 CONFLICT — filename='%s', existing_chunks=%d, "
            "stored_chunk_size=%d, stored_chunk_overlap=%d, settings_changed=%s",
            original_filename,
            existing_chunks,
            stored_chunk_size,
            stored_chunk_overlap,
            settings_changed,
        )
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

    logger.info(
        "DUPLICATE CHECK: 202 PROCESSING — filename='%s', action=%s, "
        "hash=%s, no duplicate detected",
        original_filename,
        action,
        new_hash[:12],
    )

    # Generate a unique file_id for this ingestion job
    file_id = str(uuid.uuid4())

    # Store file metadata NOW (synchronously) so duplicate detection works
    # on subsequent uploads (AC-001.8–001.10). The chunk_count is updated
    # in _ingest_file after background processing completes.
    # Read current chunk settings for metadata storage
    _cs, _co = _get_current_chunk_settings()
    await store_file_metadata(
        filename=original_filename,
        file_hash=new_hash,
        chunk_count=0,  # placeholder — updated after background ingestion
        chunk_size=_cs,
        chunk_overlap=_co,
    )

    # Write file to temp location
    suffix = Path(original_filename).suffix
    tmp_path = Path(tempfile.gettempdir()) / f"rag-studio-{file_id}{suffix}"
    tmp_path.write_bytes(content)

    # Also store a persistent copy in data/raw_uploads/ for re-ingestion (AC-010.4).
    doc_id = make_document_doc_id(original_filename)
    _RAW_UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    raw_path = _RAW_UPLOADS_DIR / f"{doc_id}{suffix}"
    raw_path.write_bytes(content)
    logger.debug("Raw upload saved for re-ingestion: %s (doc_id=%s)", raw_path, doc_id)

    # Initialize progress
    await _set_progress(file_id, "processing", "File received, queued for ingestion.")

    # Schedule background ingestion — pass current chunk settings
    background_tasks.add_task(
        _ingest_file,
        file_id=file_id,
        file_path=str(tmp_path),
        original_filename=original_filename,
        content_type=file.content_type,
        client=client,
        file_hash=new_hash,
        chunk_size=_cs,
        chunk_overlap=_co,
    )

    logger.info(
        "File '%s' accepted for ingestion: file_id=%s, size=%d bytes, action=%s",
        original_filename,
        file_id,
        len(content),
        action,
    )

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
    client: AsyncQdrantClient = Depends(get_qdrant_client),
) -> DocumentsListResponse:
    """List all ingested documents with their chunk counts.

    Returns:
        List of documents with filenames, doc_ids, and chunk counts.
    """
    # Ensure collection exists
    await ensure_collection_exists(client)

    try:
        # Get all unique doc_ids using scroll with payload
        seen_docs: dict[str, dict[str, object]] = {}

        offset: Any | None = None
        while True:
            points, next_offset = await client.scroll(
                collection_name=COLLECTION_NAME,
                limit=100,
                with_payload=[
                    "doc_id",
                    "source",
                    "created_at",
                    "chunk_index",
                    "total_chunks",
                    "chunk_size",
                    "chunk_overlap",
                ],
                with_vectors=False,
                offset=offset,
            )

            for point in points:
                if point.payload:
                    doc_id = str(point.payload.get("doc_id", ""))
                    if doc_id and doc_id not in seen_docs:
                        seen_docs[doc_id] = {
                            "doc_id": doc_id,
                            "filename": point.payload.get("source", "unknown"),
                            "chunks_count": point.payload.get("total_chunks", 0),
                            "chunk_size": point.payload.get("chunk_size", 0),
                            "chunk_overlap": point.payload.get("chunk_overlap", 0),
                            "created_at": point.payload.get("created_at", ""),
                        }

            if next_offset is None:
                break
            offset = next_offset

        documents = [
            DocumentInfo(
                doc_id=str(d["doc_id"]),
                filename=str(d["filename"]),
                chunks_count=int(str(d["chunks_count"])),
                chunk_size=int(str(d.get("chunk_size", 0))),
                chunk_overlap=int(str(d.get("chunk_overlap", 0))),
                created_at=str(d["created_at"]),
            )
            for d in seen_docs.values()
        ]

        return DocumentsListResponse(
            documents=documents,
            total=len(documents),
        )

    except Exception as e:
        logger.warning("Failed to list documents: %s", e)
        return DocumentsListResponse(documents=[], total=0)


@router.get("/documents/{doc_id}/chunks")
async def get_document_chunks(
    doc_id: str,
    client: AsyncQdrantClient = Depends(get_qdrant_client),
) -> list[dict[str, object]]:
    """Get all chunks for a specific document, sorted by chunk_index.

    Returns a list of chunk objects with: chunk_index, text, token_count, page.
    """
    await ensure_collection_exists(client)

    # Scroll all points with matching doc_id
    chunks: list[dict[str, object]] = []
    offset: int | str | None = None

    try:
        while True:
            points, next_offset = await client.scroll(
                collection_name=COLLECTION_NAME,
                scroll_filter=qmodels.Filter(
                    must=[
                        qmodels.FieldCondition(
                            key="doc_id",
                            match=qmodels.MatchValue(value=doc_id),
                        ),
                    ],
                ),
                limit=100,
                with_payload=True,
                with_vectors=False,
                offset=offset,
            )

            for point in points:
                if point.payload:
                    text = str(point.payload.get("text", ""))
                    chunks.append(
                        {
                            "chunk_index": point.payload.get("chunk_index", 0),
                            "text": text,
                            "token_count": point.payload.get(
                                "token_count", len(text.split())
                            ),
                            "page": point.payload.get("page"),
                        }
                    )

            if next_offset is None:
                break
            # next_offset is grpc.PointId | None (int | str | uuid.UUID).
            # The scroll() method accepts int | str | None at runtime, and
            # UUID values work as opaque offset identifiers. The type stubs
            # for qdrant-client do not include UUID in the offset parameter
            # union, so we use cast() to acknowledge this boundary.
            offset = cast("int | str | None", next_offset)

    except Exception as e:
        logger.warning("Failed to fetch chunks for doc_id=%s: %s", doc_id, e)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch chunks: {e}",
        )

    if not chunks:
        raise HTTPException(
            status_code=404,
            detail=f"No chunks found for document: {doc_id}",
        )

    # Sort by chunk_index
    chunks.sort(key=lambda c: int(str(c["chunk_index"])))

    return chunks


@router.delete("/documents/{file_id}", response_model=DeleteResponse)
async def delete_document(
    file_id: str,
    client: AsyncQdrantClient = Depends(get_qdrant_client),
) -> DeleteResponse:
    """Delete all chunks for a specific document by doc_id.

    Args:
        file_id: The document's UUID5 doc_id.

    Returns:
        Confirmation with count of deleted points.
    """
    from src.ingestion.embedder import delete_document_points

    await ensure_collection_exists(client)

    deleted = await delete_document_points(client, file_id)
    if deleted == 0:
        logger.warning("No points found for doc_id=%s", file_id)

    # Also remove matching entries from the in-memory stored_files dict
    # so re-uploading the same file doesn't trigger a false 409 duplicate.
    filenames_to_remove: list[str] = []
    async with stored_files_lock:
        for key, meta in list(stored_files.items()):
            # Use original_filename for UUID comparison — stored_files keys
            # are lowercased, but make_document_doc_id is case-sensitive.
            original_name = str(meta.get("original_filename", key))
            if str(make_document_doc_id(original_name)) == file_id:
                filenames_to_remove.append(key)
    for key in filenames_to_remove:
        await remove_stored_file(key)
        logger.info("Removed stored_file metadata for '%s' after deletion", key)

    log_audit(
        "delete_document",
        filename=file_id,
        success=True,
        extra={"deleted_count": deleted},
    )

    return DeleteResponse(
        status="ok",
        message=f"Deleted {deleted} chunks for document {file_id}",
        deleted_count=deleted,
    )


@router.delete("/clear", response_model=DeleteResponse)
async def clear_all_documents(
    client: AsyncQdrantClient = Depends(get_qdrant_client),
) -> DeleteResponse:
    """Clear all documents from the rag_studio_docs collection.

    Returns:
        Confirmation with count of deleted points.
    """
    await ensure_collection_exists(client)

    # Get count before deletion
    count: int = 0
    try:
        info = await client.count(collection_name=COLLECTION_NAME)
        count = info.count or 0
    except Exception:
        count = 0

    # Delete the collection and recreate it
    try:
        await client.delete_collection(collection_name=COLLECTION_NAME)
        await ensure_collection_exists(client)
    except Exception as e:
        logger.warning("Error clearing collection: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to clear collection: {e}")

    # Clear the in-memory stored_files dict (AC-001.8 cleanup)
    async with stored_files_lock:
        stored_files.clear()
    logger.info("Cleared stored_files in-memory dict")

    log_audit(
        "clear_all",
        success=True,
        extra={"deleted_count": count},
    )

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
    client: AsyncQdrantClient = Depends(get_qdrant_client),
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
    import json

    # Read current chunk settings from saved settings
    _cur_chunk_size = 512
    _cur_chunk_overlap = 64
    settings_path = Path("data/settings.enc.json")
    if settings_path.exists():
        try:
            with open(settings_path, encoding="utf-8") as f:
                saved: dict[str, object] = json.load(f)
            _cur_chunk_size = int(str(saved.get("chunk_size", 512)))
            _cur_chunk_overlap = int(str(saved.get("chunk_overlap", 64)))
        except json.JSONDecodeError, OSError, ValueError:
            pass

    # Find the stored file in data/raw_uploads/ by doc_id.
    # Files are stored as {doc_id}{suffix} during upload (BUG-010-1 fix).
    suffix = Path(request.filename).suffix
    raw_path = _RAW_UPLOADS_DIR / f"{request.doc_id}{suffix}"

    if not raw_path.exists():
        logger.warning(
            "Stored file no longer exists for re-ingestion: %s (doc_id=%s, filename=%s)",
            raw_path,
            request.doc_id,
            request.filename,
        )
        response.status_code = 200
        return ReingestResponse(
            status="skipped",
            file_id=request.doc_id,
            message=f"Source file for '{request.filename}' no longer available. Skipping.",
            detail=f"Stored file no longer exists: {raw_path.name}",
        )

    # Generate a new file_id for this ingestion job
    file_id = str(uuid.uuid4())

    # Copy the raw file to temp location for processing
    tmp_path = Path(tempfile.gettempdir()) / f"rag-studio-reingest-{file_id}{suffix}"
    shutil.copy2(str(raw_path), str(tmp_path))

    # Initialize progress
    await _set_progress(file_id, "processing", "Re-ingestion started...")

    # Schedule background ingestion with current chunk settings
    background_tasks.add_task(
        _ingest_file,
        file_id=file_id,
        file_path=str(tmp_path),
        original_filename=request.filename,
        content_type=None,
        client=client,
        chunk_size=_cur_chunk_size,
        chunk_overlap=_cur_chunk_overlap,
    )

    logger.info(
        "Re-ingestion queued for '%s': new file_id=%s, source=%s, "
        "chunk_size=%d, chunk_overlap=%d",
        request.filename,
        file_id,
        raw_path.name,
        _cur_chunk_size,
        _cur_chunk_overlap,
    )

    return ReingestResponse(
        status="processing",
        file_id=file_id,
        message=f"Re-ingestion of '{request.filename}' started. Check progress at /api/ingest/progress/{file_id}",
    )
