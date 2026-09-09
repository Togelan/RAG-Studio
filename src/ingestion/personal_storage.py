"""Atomic raw-upload and metadata storage for one Personal Lab scope."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from src.api.personal_lab_scope import PersonalLabScope
from src.ingestion.parser import canonicalize_filename, validate_file

_MANIFEST_NAME: Final = "knowledge.json"
_UPLOAD_DIRECTORY: Final = "uploads"


class PersonalKnowledgeStorageError(RuntimeError):
    """Sanitized Personal Knowledge persistence failure."""

    def __init__(self) -> None:
        super().__init__("personal_knowledge_storage_unavailable")


class PersonalKnowledgeDuplicateError(ValueError):
    """Signal a duplicate filename or content within one Personal Lab."""

    def __init__(self, document: StoredPersonalDocument) -> None:
        super().__init__("personal_knowledge_duplicate")
        self.document = document


class PersonalKnowledgeSourceError(ValueError):
    """Signal an unsupported or invalid Personal source upload."""

    def __init__(self) -> None:
        super().__init__("personal_knowledge_source_invalid")


class StoredPersonalDocument(BaseModel):
    """Validated metadata for one committed Personal source."""

    model_config = ConfigDict(frozen=True)

    doc_id: UUID
    file_id: UUID
    filename: str
    content_type: str | None
    file_hash: str
    raw_name: str
    chunk_count: int = Field(ge=1, le=10_000)
    file_size: int = Field(default=0, ge=0)
    chunk_size: int = Field(default=512, ge=1)
    chunk_overlap: int = Field(default=64, ge=0)
    strategy: str = "recursive"


class PersonalIngestionProgress(BaseModel):
    """Scope-local progress value safe for API serialization."""

    model_config = ConfigDict(frozen=True)

    file_id: UUID
    status: Literal["processing", "complete", "error"]
    code: str | None = None


class _Manifest(BaseModel):
    model_config = ConfigDict(frozen=True)

    documents: tuple[StoredPersonalDocument, ...] = ()
    progress: tuple[PersonalIngestionProgress, ...] = ()


@dataclass(frozen=True, slots=True)
class StagedPersonalUpload:
    """One validated source staged below its resolved Personal root."""

    file_id: UUID
    filename: str
    content_type: str | None
    file_hash: str
    path: Path
    replaces: StoredPersonalDocument | None = None


@dataclass(frozen=True, slots=True)
class PersonalKnowledgeStorage:
    """Persist source bytes and metadata without accepting a scope selector."""

    def stage(
        self,
        scope: PersonalLabScope,
        filename: str,
        content_type: str | None,
        content: bytes,
        action: Literal["default", "rename", "replace"] = "default",
    ) -> StagedPersonalUpload:
        """Validate and stage one unique upload under the trusted scope root."""
        return stage_personal_upload(scope, filename, content_type, content, action)

    def commit(
        self,
        scope: PersonalLabScope,
        staged: StagedPersonalUpload,
        doc_id: UUID,
        chunk_count: int,
        chunk_size: int,
        chunk_overlap: int,
        strategy: str,
    ) -> StoredPersonalDocument:
        """Publish source bytes and completed metadata atomically."""
        suffix = Path(staged.filename).suffix.casefold()
        raw_name = f"{staged.file_id.hex}{suffix}"
        target = _uploads(scope) / raw_name
        document = StoredPersonalDocument(
            doc_id=doc_id,
            file_id=staged.file_id,
            filename=staged.filename,
            content_type=staged.content_type,
            file_hash=staged.file_hash,
            raw_name=raw_name,
            chunk_count=chunk_count,
            file_size=staged.path.stat().st_size,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            strategy=strategy,
        )
        try:
            manifest = _load(scope)
            os.replace(staged.path, target)
            documents = tuple(
                item for item in manifest.documents if item.doc_id != doc_id
            )
            _save(
                scope,
                _Manifest(
                    documents=(*documents, document),
                    progress=_replace_progress(manifest, staged.file_id, "complete"),
                ),
            )
            if staged.replaces is not None:
                try:
                    (_uploads(scope) / staged.replaces.raw_name).unlink(missing_ok=True)
                except OSError:
                    pass
        except OSError, ValidationError:
            raise PersonalKnowledgeStorageError from None
        return document

    def fail(self, scope: PersonalLabScope, staged: StagedPersonalUpload) -> None:
        """Remove staged bytes and retain only a sanitized failed progress code."""
        staged.path.unlink(missing_ok=True)
        try:
            manifest = _load(scope)
            _save(
                scope,
                manifest.model_copy(
                    update={
                        "progress": _replace_progress(manifest, staged.file_id, "error")
                    }
                ),
            )
        except OSError, ValidationError:
            raise PersonalKnowledgeStorageError from None

    def documents(self, scope: PersonalLabScope) -> tuple[StoredPersonalDocument, ...]:
        """Return committed documents from this scope only."""
        return _load(scope).documents

    def document(
        self, scope: PersonalLabScope, doc_id: UUID
    ) -> StoredPersonalDocument | None:
        """Return one scope-local document by opaque identifier."""
        return next(
            (item for item in _load(scope).documents if item.doc_id == doc_id),
            None,
        )

    def progress(
        self, scope: PersonalLabScope, file_id: UUID
    ) -> PersonalIngestionProgress | None:
        """Return one scope-local progress item."""
        return next(
            (item for item in _load(scope).progress if item.file_id == file_id),
            None,
        )

    def raw_path(
        self, scope: PersonalLabScope, document: StoredPersonalDocument
    ) -> Path:
        """Resolve a committed raw source below its trusted scope root."""
        return _uploads(scope) / document.raw_name

    def update_chunks(
        self,
        scope: PersonalLabScope,
        doc_id: UUID,
        chunk_count: int,
        chunk_size: int,
        chunk_overlap: int,
        strategy: str,
    ) -> StoredPersonalDocument:
        """Publish revised chunk metadata after a successful re-index."""
        manifest = _load(scope)
        current = next(
            (item for item in manifest.documents if item.doc_id == doc_id), None
        )
        if current is None:
            raise PersonalKnowledgeStorageError
        updated = current.model_copy(
            update={
                "chunk_count": chunk_count,
                "chunk_size": chunk_size,
                "chunk_overlap": chunk_overlap,
                "strategy": strategy,
            }
        )
        _save(
            scope,
            manifest.model_copy(
                update={
                    "documents": tuple(
                        updated if item.doc_id == doc_id else item
                        for item in manifest.documents
                    )
                }
            ),
        )
        return updated

    def remove(self, scope: PersonalLabScope, doc_id: UUID) -> None:
        """Remove one committed source after vector deletion succeeds."""
        manifest = _load(scope)
        document = next(
            (item for item in manifest.documents if item.doc_id == doc_id), None
        )
        if document is None:
            return
        try:
            (_uploads(scope) / document.raw_name).unlink(missing_ok=True)
            _save(
                scope,
                _Manifest(
                    documents=tuple(
                        item for item in manifest.documents if item.doc_id != doc_id
                    ),
                    progress=tuple(
                        item
                        for item in manifest.progress
                        if item.file_id != document.file_id
                    ),
                ),
            )
        except OSError, ValidationError:
            raise PersonalKnowledgeStorageError from None

    def clear(self, scope: PersonalLabScope) -> None:
        """Remove this scope's committed raw sources and manifest records."""
        manifest = _load(scope)
        try:
            for document in manifest.documents:
                (_uploads(scope) / document.raw_name).unlink(missing_ok=True)
            _save(scope, _Manifest())
        except OSError, ValidationError:
            raise PersonalKnowledgeStorageError from None


def stage_personal_upload(
    scope: PersonalLabScope,
    filename: str,
    content_type: str | None,
    content: bytes,
    action: Literal["default", "rename", "replace"],
) -> StagedPersonalUpload:
    """Atomically reserve and stage one scoped upload action."""
    try:
        canonical = canonicalize_filename(filename)
        validate_file(canonical, len(content), content)
        manifest = _load(scope)
    except OSError, UnicodeError, ValueError, ValidationError:
        raise PersonalKnowledgeSourceError from None
    digest = hashlib.sha256(content).hexdigest()
    canonical, duplicate = _admit_name(manifest, canonical, digest, action)
    file_id = uuid4()
    staged_path = _uploads(scope) / f".{file_id.hex}.upload"
    try:
        staged_path.parent.mkdir(parents=True, exist_ok=True)
        staged_path.write_bytes(content)
        progress = PersonalIngestionProgress(file_id=file_id, status="processing")
        _save(
            scope,
            manifest.model_copy(update={"progress": (*manifest.progress, progress)}),
        )
    except OSError:
        staged_path.unlink(missing_ok=True)
        raise PersonalKnowledgeStorageError from None
    return StagedPersonalUpload(
        file_id,
        canonical,
        content_type,
        digest,
        staged_path,
        duplicate if action == "replace" else None,
    )


def _admit_name(
    manifest: _Manifest,
    canonical: str,
    digest: str,
    action: Literal["default", "rename", "replace"],
) -> tuple[str, StoredPersonalDocument | None]:
    duplicate = next(
        (
            item
            for item in manifest.documents
            if item.filename.casefold() == canonical.casefold()
            or item.file_hash == digest
        ),
        None,
    )
    if duplicate is not None and action == "default":
        raise PersonalKnowledgeDuplicateError(duplicate)
    if action == "rename":
        canonical = _unique_filename(canonical, manifest.documents)
    return canonical, duplicate


def personal_duplicate_payload(
    existing: StoredPersonalDocument,
    *,
    content_size: int,
    current_chunk_size: int,
    current_chunk_overlap: int,
) -> dict[str, object]:
    """Return sanitized duplicate metadata used by the Personal HTTP contract."""
    return {
        "status": "duplicate",
        "filename": existing.filename,
        "existing_chunks": existing.chunk_count,
        "existing_size": existing.file_size,
        "stored_chunk_size": existing.chunk_size,
        "stored_chunk_overlap": existing.chunk_overlap,
        "new_file_size": content_size,
        "estimated_chunks": max(
            1, (content_size + current_chunk_size - 1) // current_chunk_size
        ),
        "chunks_settings_changed": existing.chunk_size != current_chunk_size
        or existing.chunk_overlap != current_chunk_overlap,
        "current_chunk_size": current_chunk_size,
        "current_chunk_overlap": current_chunk_overlap,
    }


def _load(scope: PersonalLabScope) -> _Manifest:
    path = scope.data_root / _MANIFEST_NAME
    if not path.exists():
        return _Manifest()
    try:
        return _Manifest.model_validate_json(path.read_text(encoding="utf-8"))
    except OSError, ValidationError:
        raise PersonalKnowledgeStorageError from None


def _save(scope: PersonalLabScope, manifest: _Manifest) -> None:
    scope.data_root.mkdir(parents=True, exist_ok=True)
    target = scope.data_root / _MANIFEST_NAME
    temporary = scope.data_root / f".{_MANIFEST_NAME}.{uuid4().hex}.tmp"
    try:
        temporary.write_text(manifest.model_dump_json(), encoding="utf-8")
        os.replace(temporary, target)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def _uploads(scope: PersonalLabScope) -> Path:
    return scope.data_root / _UPLOAD_DIRECTORY


def _unique_filename(
    filename: str, documents: tuple[StoredPersonalDocument, ...]
) -> str:
    occupied = {item.filename.casefold() for item in documents}
    path = Path(filename)
    counter = 1
    candidate = filename
    while candidate.casefold() in occupied:
        candidate = f"{path.stem} ({counter}){path.suffix}"
        counter += 1
    return candidate


def _replace_progress(
    manifest: _Manifest,
    file_id: UUID,
    status: Literal["complete", "error"],
) -> tuple[PersonalIngestionProgress, ...]:
    retained = tuple(item for item in manifest.progress if item.file_id != file_id)
    return (*retained, PersonalIngestionProgress(file_id=file_id, status=status))


def discard_personal_upload(
    scope: PersonalLabScope,
    staged: StagedPersonalUpload,
    doc_id: UUID | None,
) -> None:
    """Remove every local artifact of an upload that did not commit."""
    try:
        staged.path.unlink(missing_ok=True)
        if doc_id is not None:
            suffix = Path(staged.filename).suffix.casefold()
            (_uploads(scope) / f"{staged.file_id.hex}{suffix}").unlink(missing_ok=True)
        manifest = _load(scope)
        _save(
            scope,
            _Manifest(
                documents=tuple(
                    item
                    for item in manifest.documents
                    if not (item.doc_id == doc_id and item.file_id == staged.file_id)
                ),
                progress=tuple(
                    item for item in manifest.progress if item.file_id != staged.file_id
                ),
            ),
        )
    except OSError, ValidationError, PersonalKnowledgeStorageError:
        raise PersonalKnowledgeStorageError from None
