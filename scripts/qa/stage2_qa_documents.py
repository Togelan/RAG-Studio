"""Deterministic document transformations for the Stage 2 QA state façade."""

from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass, replace
from pathlib import Path

from scripts.qa.stage2_qa_schema import ChunkSnapshot, DocumentSnapshot
from scripts.qa.stage2_qa_types import (
    ChunkInfo,
    DocumentInfo,
    DuplicateResponse,
    SettingsPayload,
)

CREATED_AT = "2026-08-15T00:00:00Z"
NAMESPACE = uuid.UUID("d62cb62a-256f-4db3-bb3b-c1775017e7cf")


@dataclass(frozen=True, slots=True)
class QaChunk:
    point_id: str
    chunk_index: int
    text: str
    token_count: int
    page: int | None
    text_sha256: str


@dataclass(frozen=True, slots=True)
class QaDocument:
    doc_id: str
    filename: str
    content_sha256: str
    size_bytes: int
    chunk_size: int
    chunk_overlap: int
    strategy: str
    chunks: tuple[QaChunk, ...]


@dataclass(slots=True)
class QaJob:
    document: QaDocument
    polls: int = 0


class QaCapacityError(RuntimeError):
    """Raised when the fixed QA document workload is full."""


def parse_cursor(cursor: str | None) -> int:
    if cursor is None:
        return 0
    if not cursor.isdigit():
        raise ValueError("invalid cursor")
    return int(cursor)


def safe_filename(filename: str) -> str:
    name = Path(filename).name
    if name != filename or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._ -]{0,199}", name):
        raise ValueError("invalid filename")
    if Path(name).suffix.lower() not in {".txt", ".md", ".csv", ".pdf", ".docx"}:
        raise ValueError("unsupported file type")
    return name


def find_filename(documents: dict[str, QaDocument], filename: str) -> QaDocument | None:
    return next(
        (item for item in documents.values() if item.filename == filename), None
    )


def renamed_filename(documents: dict[str, QaDocument], filename: str) -> str:
    path = Path(filename)
    candidate = f"{path.stem} (qa-copy){path.suffix}"
    index = 2
    while find_filename(documents, candidate) is not None:
        candidate = f"{path.stem} (qa-copy-{index}){path.suffix}"
        index += 1
    return candidate


def make_document(
    filename: str, content: bytes, settings: SettingsPayload
) -> QaDocument:
    digest = hashlib.sha256(content).hexdigest()
    doc_id = f"qa-doc-{uuid.uuid5(NAMESPACE, filename + digest).hex[:16]}"
    text = content.decode("utf-8", errors="replace")[:20_000] or "Empty QA fixture"
    lines = [line for line in text.splitlines() if line.strip()] or [text]
    pieces = (
        lines[:20]
        if filename.lower().endswith(".csv")
        else [text[index : index + 240] for index in range(0, len(text), 240)][:20]
    )
    chunks = tuple(
        make_chunk(doc_id, index, value) for index, value in enumerate(pieces)
    )
    strategy = (
        "csv_row"
        if filename.lower().endswith(".csv")
        else settings["chunking"]["strategy"]
    )
    return QaDocument(
        doc_id=doc_id,
        filename=filename,
        content_sha256=digest,
        size_bytes=len(content),
        chunk_size=settings["chunk_size"],
        chunk_overlap=settings["chunk_overlap"],
        strategy=strategy,
        chunks=chunks,
    )


def make_chunk(doc_id: str, index: int, text: str) -> QaChunk:
    digest = hashlib.sha256(text.encode()).hexdigest()
    return QaChunk(
        point_id=f"{doc_id}-chunk-{index}",
        chunk_index=index,
        text=text,
        token_count=max(1, len(text.split())),
        page=None,
        text_sha256=digest,
    )


def document_info(document: QaDocument) -> DocumentInfo:
    return {
        "doc_id": document.doc_id,
        "filename": document.filename,
        "chunks_count": len(document.chunks),
        "chunk_size": document.chunk_size,
        "chunk_overlap": document.chunk_overlap,
        "created_at": CREATED_AT,
        "strategy": document.strategy,
        "schema_version": 1,
    }


def reingested_document(document: QaDocument, settings: SettingsPayload) -> QaDocument:
    strategy = (
        "csv_row"
        if document.filename.lower().endswith(".csv")
        else settings["chunking"]["strategy"]
    )
    return replace(
        document,
        chunk_size=settings["chunk_size"],
        chunk_overlap=settings["chunk_overlap"],
        strategy=strategy,
    )


def chunk_info(chunk: QaChunk) -> ChunkInfo:
    return {
        "point_id": chunk.point_id,
        "chunk_index": chunk.chunk_index,
        "text": chunk.text,
        "token_count": chunk.token_count,
        "page": chunk.page,
    }


def duplicate_response(
    document: QaDocument,
    content: bytes,
    settings: SettingsPayload,
) -> DuplicateResponse:
    estimated = max(1, (len(content) + document.chunk_size - 1) // document.chunk_size)
    return {
        "status": "duplicate",
        "filename": document.filename,
        "existing_chunks": len(document.chunks),
        "existing_size": document.size_bytes,
        "stored_chunk_size": document.chunk_size,
        "stored_chunk_overlap": document.chunk_overlap,
        "new_file_size": len(content),
        "estimated_chunks": estimated,
        "chunks_settings_changed": False,
        "current_chunk_size": settings["chunk_size"],
        "current_chunk_overlap": settings["chunk_overlap"],
    }


def snapshot_document(document: QaDocument) -> DocumentSnapshot:
    chunks = tuple(
        ChunkSnapshot(
            chunk_index=item.chunk_index,
            page=item.page,
            token_count=item.token_count,
            text_sha256=item.text_sha256,
        )
        for item in document.chunks
    )
    return DocumentSnapshot(
        doc_id=document.doc_id,
        filename=document.filename,
        content_sha256=document.content_sha256,
        size_bytes=document.size_bytes,
        chunk_size=document.chunk_size,
        chunk_overlap=document.chunk_overlap,
        strategy=document.strategy,
        chunks=chunks,
    )


def restore_document(snapshot: DocumentSnapshot) -> QaDocument:
    chunks = tuple(
        QaChunk(
            point_id=f"{snapshot.doc_id}-chunk-{item.chunk_index}",
            chunk_index=item.chunk_index,
            text=f"[redacted QA chunk {item.text_sha256[:12]}]",
            token_count=item.token_count,
            page=item.page,
            text_sha256=item.text_sha256,
        )
        for item in snapshot.chunks
    )
    return QaDocument(
        doc_id=snapshot.doc_id,
        filename=snapshot.filename,
        content_sha256=snapshot.content_sha256,
        size_bytes=snapshot.size_bytes,
        chunk_size=snapshot.chunk_size,
        chunk_overlap=snapshot.chunk_overlap,
        strategy=snapshot.strategy,
        chunks=chunks,
    )
