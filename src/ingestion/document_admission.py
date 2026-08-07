"""Bounded upload admission and per-document operation coordination."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import anyio

from src.ingestion.parser import canonicalize_filename, filename_comparison_key
from src.paths import data_path

MAX_PENDING_UPLOADS: Final = 10

# In-memory store of ingested file metadata for duplicate detection (AC-001.8–001.10)
# Key: normalized filename (lowercase), Value: dict with hash, chunk_settings, chunk_count
stored_files: dict[str, dict[str, object]] = {}
stored_files_lock = anyio.Lock()
_pending_upload_names: set[str] = set()


def _raw_uploads_dir() -> Path:
    """Return the persistent raw-upload directory under the data root."""
    return data_path("raw_uploads")


class FilenameReservedError(Exception):
    """Raised when a canonical filename already has an active admission."""


class UploadCapacityError(Exception):
    """Raised when all bounded upload slots are occupied."""


async def reserve_upload_name(
    filename: str,
    *,
    rename: bool,
    allow_stored: bool = False,
) -> str:
    """Atomically choose and reserve a canonical upload display name."""
    canonical = canonicalize_filename(filename)
    stem = Path(canonical).stem
    suffix = Path(canonical).suffix
    async with stored_files_lock:
        stored_keys = {
            filename_comparison_key(str(meta.get("original_filename", key)))
            for key, meta in stored_files.items()
        }
        candidate = canonical
        counter = 1
        while rename and filename_comparison_key(candidate) in (
            stored_keys | _pending_upload_names
        ):
            candidate = f"{stem} ({counter}){suffix}"
            counter += 1
        key = filename_comparison_key(candidate)
        if key in _pending_upload_names or (not allow_stored and key in stored_keys):
            raise FilenameReservedError
        if len(_pending_upload_names) >= MAX_PENDING_UPLOADS:
            raise UploadCapacityError
        _pending_upload_names.add(key)
        return candidate


async def release_upload_name(filename_or_key: str) -> None:
    """Release an upload reservation without waiting for capacity."""
    key = filename_comparison_key(filename_or_key)
    async with stored_files_lock:
        _pending_upload_names.discard(key)


async def _reset_upload_admissions_for_tests() -> None:
    """Clear upload reservations used by admission behavior tests."""
    async with stored_files_lock:
        _pending_upload_names.clear()


@dataclass(slots=True)
class _DocumentLockState:
    """Mutable lock state tracks active and queued operations for cleanup."""

    lock: anyio.Lock
    users: int = 0


# A replacement consists of a delete followed by an upsert. Those operations
# must be serialized per doc_id. The reference count discards unused locks.
_document_locks: dict[str, _DocumentLockState] = {}
_document_locks_guard = anyio.Lock()


@asynccontextmanager
async def document_operation_lock(doc_id: str) -> AsyncIterator[None]:
    """Serialize vector-changing operations for one document."""
    async with _document_locks_guard:
        state = _document_locks.get(doc_id)
        if state is None:
            state = _DocumentLockState(lock=anyio.Lock())
            _document_locks[doc_id] = state
        state.users += 1

    acquired = False
    try:
        await state.lock.acquire()
        acquired = True
        yield
    finally:
        with anyio.CancelScope(shield=True):
            if acquired:
                state.lock.release()
            async with _document_locks_guard:
                state.users -= 1
                if state.users == 0 and _document_locks.get(doc_id) is state:
                    del _document_locks[doc_id]
