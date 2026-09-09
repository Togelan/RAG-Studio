"""Authenticated Personal Knowledge HTTP and ingestion boundary."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType
from typing import Final, Literal
from uuid import UUID

import anyio
from fastapi import APIRouter, HTTPException, Request, UploadFile, status
from fastapi.responses import JSONResponse
from qdrant_client import AsyncQdrantClient

from src.api.chunking_settings import ChunkingSettings
from src.api.personal_lab_registry import PersonalLabRouteDependencies
from src.api.personal_lab_scope import PersonalLabScope
from src.api.personal_lab_settings import (
    PersonalLabSettingsStore,
    PersonalSettingsPersistenceError,
)
from src.ingestion.chunking_dispatch import (
    ChunkingBatch,
    dispatch_csv,
    dispatch_text,
    settings_payload,
    unit_payload,
)
from src.ingestion.embedder import (
    get_embedder,
    make_personal_chunk_id,
    make_personal_document_id,
)
from src.ingestion.embedding import Embedder, EmbeddingError
from src.ingestion.parser import detect_and_parse, parse_csv_as_rows
from src.ingestion.personal_storage import (
    PersonalKnowledgeDuplicateError,
    PersonalKnowledgeSourceError,
    PersonalKnowledgeStorage,
    PersonalKnowledgeStorageError,
    StagedPersonalUpload,
    StoredPersonalDocument,
    discard_personal_upload,
    personal_duplicate_payload,
)
from src.vector_store.client import get_qdrant_client
from src.vector_store.contracts import VectorStoreError
from src.vector_store.models import (
    DocumentReplacement,
    JsonValue,
    PersonalVectorScope,
    VectorRecord,
)
from src.vector_store.pagination import CursorError
from src.vector_store.personal_store import (
    PersonalRagStore,
    personal_chunks_response,
    personal_documents_response,
)

_MAX_UPLOAD_BYTES: Final = 50 * 1024 * 1024
type PersonalClientProvider = Callable[[], Awaitable[AsyncQdrantClient]]


@dataclass(frozen=True, slots=True)
class _PersonalKnowledgeService:
    dependencies: PersonalLabRouteDependencies
    client_provider: PersonalClientProvider
    embedder: Embedder
    storage: PersonalKnowledgeStorage
    settings: PersonalLabSettingsStore
    write_lock: anyio.Lock

    async def upload(
        self,
        request: Request,
        file: UploadFile,
        action: Literal["default", "rename", "replace", "cancel"] = "default",
    ) -> dict[str, object] | JSONResponse:
        scope = await _scope(request, self.dependencies)
        content = await file.read(_MAX_UPLOAD_BYTES + 1)
        if action == "cancel":
            return JSONResponse(
                status_code=200,
                content={
                    "status": "cancelled",
                    "file_id": "",
                    "message": "Upload cancelled.",
                },
            )
        async with self.write_lock:
            try:
                staged = await _stage_upload(
                    self.storage,
                    scope,
                    file.filename or "",
                    file.content_type,
                    content,
                    action,
                )
            except PersonalKnowledgeDuplicateError as duplicate:
                settings = await anyio.to_thread.run_sync(self.settings.load, scope)
                current = settings.settings.chunking
                return JSONResponse(
                    status_code=409,
                    content=personal_duplicate_payload(
                        duplicate.document,
                        content_size=len(content),
                        current_chunk_size=current.chunk_size,
                        current_chunk_overlap=current.chunk_overlap,
                    ),
                )
            return await _publish_staged(self, scope, staged)

    async def documents(
        self, request: Request, cursor: str | None = None
    ) -> dict[str, object]:
        scope = await _scope(request, self.dependencies)
        store = await self._store(scope)
        try:
            return personal_documents_response(await store.list_documents(cursor))
        except CursorError:
            raise HTTPException(status_code=400, detail="Invalid cursor.") from None
        except VectorStoreError:
            raise HTTPException(
                status_code=503, detail="Personal Knowledge is unavailable."
            ) from None

    async def chunks(
        self, request: Request, doc_id: UUID, cursor: str | None = None
    ) -> dict[str, object]:
        scope = await _scope(request, self.dependencies)
        if await anyio.to_thread.run_sync(self.storage.document, scope, doc_id) is None:
            raise HTTPException(status_code=404, detail="Document not found.")
        try:
            store = await self._store(scope)
            return personal_chunks_response(
                await store.list_chunks(str(doc_id), cursor)
            )
        except CursorError:
            raise HTTPException(status_code=400, detail="Invalid cursor.") from None
        except VectorStoreError:
            raise HTTPException(
                status_code=503, detail="Personal Knowledge is unavailable."
            ) from None

    async def progress(self, request: Request, file_id: UUID) -> dict[str, object]:
        scope = await _scope(request, self.dependencies)
        item = await anyio.to_thread.run_sync(self.storage.progress, scope, file_id)
        if item is None:
            raise HTTPException(status_code=404, detail="Progress not found.")
        documents = await anyio.to_thread.run_sync(self.storage.documents, scope)
        document = next(
            (entry for entry in documents if entry.file_id == file_id), None
        )
        return {
            "file_id": str(item.file_id),
            "status": "done" if item.status == "complete" else item.status,
            "message": "Upload complete."
            if item.status == "complete"
            else "Upload pending.",
            "chunks_count": document.chunk_count if document else None,
            "error": item.code if item.status == "error" else None,
        }

    async def reindex(self, request: Request, doc_id: UUID) -> dict[str, object]:
        scope = await _scope(request, self.dependencies)
        document = await anyio.to_thread.run_sync(self.storage.document, scope, doc_id)
        if document is None:
            raise HTTPException(status_code=404, detail="Document not found.")
        staged = StagedPersonalUpload(
            document.file_id,
            document.filename,
            document.content_type,
            document.file_hash,
            self.storage.raw_path(scope, document),
        )
        try:
            replacement = await self._replacement(scope, staged, doc_id=doc_id)
            store = await self._store(scope, replacement)
            async def commit_metadata() -> None:
                await anyio.to_thread.run_sync(
                    self.storage.update_chunks,
                    scope,
                    doc_id,
                    len(replacement.records),
                    replacement.chunk_size,
                    replacement.chunk_overlap,
                    replacement.strategy,
                )

            await store.replace_document(replacement, after_publish=commit_metadata)
            updated = document.model_copy(
                update={
                    "chunk_count": len(replacement.records),
                    "chunk_size": replacement.chunk_size,
                    "chunk_overlap": replacement.chunk_overlap,
                    "strategy": replacement.strategy,
                }
            )
        except (
            EmbeddingError,
            PersonalKnowledgeSourceError,
            PersonalKnowledgeStorageError,
            PersonalSettingsPersistenceError,
            VectorStoreError,
        ):
            raise HTTPException(
                status_code=503, detail="Personal re-index could not be completed."
            ) from None
        return _upload_response(updated)

    async def delete(self, request: Request, doc_id: UUID) -> dict[str, int]:
        scope = await _scope(request, self.dependencies)
        if await anyio.to_thread.run_sync(self.storage.document, scope, doc_id) is None:
            raise HTTPException(status_code=404, detail="Document not found.")
        store = await self._store(scope)
        try:
            deleted = await store.delete_document(str(doc_id))
            await anyio.to_thread.run_sync(self.storage.remove, scope, doc_id)
        except PersonalKnowledgeStorageError, VectorStoreError:
            raise HTTPException(
                status_code=503, detail="Personal Knowledge is unavailable."
            ) from None
        return {"deleted": deleted}

    async def clear(self, request: Request) -> dict[str, int]:
        scope = await _scope(request, self.dependencies)
        store = await self._store(scope)
        try:
            deleted = await store.clear_documents()
            await anyio.to_thread.run_sync(self.storage.clear, scope)
        except PersonalKnowledgeStorageError, VectorStoreError:
            raise HTTPException(
                status_code=503, detail="Personal Knowledge is unavailable."
            ) from None
        return {"deleted": deleted}

    async def _replacement(
        self,
        scope: PersonalLabScope,
        staged: StagedPersonalUpload,
        *,
        doc_id: UUID | None = None,
    ) -> DocumentReplacement:
        settings = await anyio.to_thread.run_sync(self.settings.load, scope)
        return await anyio.to_thread.run_sync(
            _build_replacement,
            scope,
            staged,
            doc_id,
            settings.settings.chunking,
            self.embedder,
        )

    async def _store(
        self, scope: PersonalLabScope, replacement: DocumentReplacement | None = None
    ) -> PersonalRagStore:
        client = await self.client_provider()
        store = PersonalRagStore(
            client, PersonalVectorScope(scope.id, scope.collection_name)
        )
        dense_size = 384
        if replacement is not None and replacement.records:
            dense_size = len(replacement.records[0].dense.values)
        await store.ensure_ready(dense_size=dense_size)
        return store


def create_personal_knowledge_router(
    dependencies: PersonalLabRouteDependencies,
    *,
    client_provider: PersonalClientProvider = get_qdrant_client,
    embedder: Embedder | None = None,
    storage: PersonalKnowledgeStorage | None = None,
    settings: PersonalLabSettingsStore | None = None,
) -> APIRouter:
    """Create Personal Knowledge routes from server-owned authorities."""
    service = _PersonalKnowledgeService(
        dependencies,
        client_provider,
        embedder or get_embedder(),
        storage or PersonalKnowledgeStorage(),
        settings or PersonalLabSettingsStore(),
        anyio.Lock(),
    )
    router = APIRouter(prefix="/api/personal/knowledge", tags=["personal-knowledge"])
    router.add_api_route(
        "/upload",
        service.upload,
        methods=["POST"],
        response_model=None,
        status_code=status.HTTP_201_CREATED,
    )
    router.add_api_route("/documents", service.documents, methods=["GET"])
    router.add_api_route("/documents/{doc_id}/chunks", service.chunks, methods=["GET"])
    router.add_api_route("/progress/{file_id}", service.progress, methods=["GET"])
    router.add_api_route(
        "/documents/{doc_id}/reindex", service.reindex, methods=["POST"]
    )
    router.add_api_route("/documents/{doc_id}", service.delete, methods=["DELETE"])
    router.add_api_route("/clear", service.clear, methods=["DELETE"])
    return router


async def _scope(
    request: Request, dependencies: PersonalLabRouteDependencies
) -> PersonalLabScope:
    if request.headers.get("X-API-Key"):
        raise HTTPException(
            status_code=400, detail="Browser API key headers are not accepted."
        )
    trusted = await dependencies.auth_context.resolve(request, require_workspace=False)
    return await dependencies.scopes.resolve(trusted.claims.user_id)


async def _publish_staged(
    service: _PersonalKnowledgeService,
    scope: PersonalLabScope,
    staged: StagedPersonalUpload,
) -> dict[str, object]:
    store: PersonalRagStore | None = None
    doc_id: UUID | None = None
    published = False
    try:
        replacement = await service._replacement(scope, staged)
        doc_id = staged.replaces.doc_id if staged.replaces else UUID(replacement.doc_id)
        if staged.replaces is not None:
            replacement = replace(replacement, doc_id=str(doc_id))
        store = await service._store(scope, replacement)
        await store.replace_document(replacement)
        published = True
        document = await anyio.to_thread.run_sync(
            service.storage.commit,
            scope,
            staged,
            doc_id,
            len(replacement.records),
            replacement.chunk_size,
            replacement.chunk_overlap,
            replacement.strategy,
        )
    except anyio.get_cancelled_exc_class():
        await _abort_upload(service, scope, staged, store, doc_id, published)
        raise
    except PersonalKnowledgeSourceError:
        await _abort_upload(service, scope, staged, store, doc_id, published)
        raise HTTPException(status_code=415, detail="Unsupported source.") from None
    except (
        EmbeddingError,
        PersonalKnowledgeStorageError,
        PersonalSettingsPersistenceError,
        VectorStoreError,
    ):
        await _abort_upload(service, scope, staged, store, doc_id, published)
        raise HTTPException(
            status_code=503, detail="Personal Knowledge is unavailable."
        ) from None
    return _upload_response(document)


async def _abort_upload(
    service: _PersonalKnowledgeService,
    scope: PersonalLabScope,
    staged: StagedPersonalUpload,
    store: PersonalRagStore | None,
    doc_id: UUID | None,
    published: bool,
) -> None:
    with anyio.move_on_after(5, shield=True):
        if published and store is not None and doc_id is not None:
            try:
                if staged.replaces is None:
                    await store.delete_document(str(doc_id))
                else:
                    previous = staged.replaces
                    previous_upload = StagedPersonalUpload(
                        previous.file_id,
                        previous.filename,
                        previous.content_type,
                        previous.file_hash,
                        service.storage.raw_path(scope, previous),
                    )
                    rollback = await service._replacement(
                        scope, previous_upload, doc_id=previous.doc_id
                    )
                    await store.replace_document(rollback)
            except (
                EmbeddingError,
                PersonalKnowledgeSourceError,
                PersonalSettingsPersistenceError,
                VectorStoreError,
            ):
                pass
        try:
            await anyio.to_thread.run_sync(
                discard_personal_upload, scope, staged, doc_id
            )
        except PersonalKnowledgeStorageError:
            pass


async def _stage_upload(
    storage: PersonalKnowledgeStorage,
    scope: PersonalLabScope,
    filename: str,
    content_type: str | None,
    content: bytes,
    action: Literal["default", "rename", "replace"],
) -> StagedPersonalUpload:
    try:
        return await anyio.to_thread.run_sync(
            storage.stage, scope, filename, content_type, content, action
        )
    except PersonalKnowledgeSourceError:
        raise HTTPException(status_code=415, detail="Unsupported source.") from None
    except PersonalKnowledgeStorageError:
        raise HTTPException(
            status_code=503, detail="Personal Knowledge is unavailable."
        ) from None


def _build_replacement(
    scope: PersonalLabScope,
    staged: StagedPersonalUpload,
    doc_id: UUID | None,
    chunking: ChunkingSettings,
    embedder: Embedder,
) -> DocumentReplacement:
    resolved_doc_id = doc_id or UUID(
        make_personal_document_id(str(scope.id), staged.filename)
    )
    try:
        batch, csv_metadata = _parse_batch(staged, chunking, str(resolved_doc_id))
    except OSError, UnicodeError, ValueError:
        raise PersonalKnowledgeSourceError from None
    if not batch.units or len(batch.units) > 10_000:
        raise PersonalKnowledgeSourceError
    dense = embedder.embed_dense(batch.texts)
    sparse = embedder.embed_sparse(batch.texts)
    created_at = datetime.now(UTC).isoformat()
    records = tuple(
        VectorRecord(
            point_id=make_personal_chunk_id(str(scope.id), str(resolved_doc_id), index),
            dense=dense[index],
            sparse=sparse[index],
            payload=MappingProxyType(
                {
                    "text": text,
                    "source": staged.filename,
                    "chunk_index": index,
                    **unit_payload(batch, batch.units[index]),
                    **csv_metadata[index],
                }
            ),
        )
        for index, text in enumerate(batch.texts)
    )
    return DocumentReplacement(
        doc_id=str(resolved_doc_id),
        filename=staged.filename,
        records=records,
        chunk_size=chunking.chunk_size,
        chunk_overlap=chunking.chunk_overlap,
        created_at=created_at,
        strategy=batch.strategy,
        schema_version=chunking.schema_version,
        file_hash=staged.file_hash,
        chunking_fingerprint=chunking.fingerprint,
        chunking_settings=settings_payload(chunking),
    )


def _parse_batch(
    staged: StagedPersonalUpload,
    chunking: ChunkingSettings,
    source_id: str,
) -> tuple[ChunkingBatch, tuple[dict[str, JsonValue], ...]]:
    if Path(staged.filename).suffix.casefold() == ".csv":
        rows, metadata = parse_csv_as_rows(staged.path)
        return dispatch_csv(rows, chunking, source_id), tuple(
            _csv_payload(index, item) for index, item in enumerate(metadata)
        )
    text, _ = detect_and_parse(staged.path, staged.filename, staged.content_type)
    batch = dispatch_text(text, chunking, source_id)
    return batch, tuple({} for _ in batch.units)


def _csv_payload(index: int, raw: dict[str, object]) -> dict[str, JsonValue]:
    headers: list[JsonValue]
    match raw.get("csv_headers"):
        case list() as header_values:
            headers = [str(value) for value in header_values]
        case _:
            headers = []
    row_data: dict[str, JsonValue]
    match raw.get("csv_row_data"):
        case dict() as row_values:
            row_data = {str(key): str(value) for key, value in row_values.items()}
        case _:
            row_data = {}
    return {"csv_row": index, "csv_headers": headers, "csv_row_data": row_data}


def _upload_response(document: StoredPersonalDocument) -> dict[str, object]:
    return {
        "status": "processing",
        "file_id": str(document.file_id),
        "message": "Upload accepted.",
        "doc_id": str(document.doc_id),
        "filename": document.filename,
        "chunk_count": document.chunk_count,
        "chunk_size": document.chunk_size,
        "chunk_overlap": document.chunk_overlap,
        "strategy": document.strategy,
    }
