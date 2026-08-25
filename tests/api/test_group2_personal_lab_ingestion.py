from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI, HTTPException, Request
from qdrant_client import AsyncQdrantClient

from src.api.personal_lab_registry import PersonalLabRouteDependencies
from src.api.personal_lab_scope import PersonalLabScopeResolver
from src.api.routes.personal_settings import create_personal_settings_router
from src.api.saas_security import SaasCsrfMiddleware
from src.ingestion.embedding import Embedder
from src.ingestion.personal_router import create_personal_knowledge_router
from src.vector_store.models import DenseVector, SparseVector


@dataclass(frozen=True, slots=True)
class _Claims:
    user_id: UUID


@dataclass(frozen=True, slots=True)
class _AuthResult:
    claims: _Claims


@dataclass(frozen=True, slots=True)
class _CookieAuth:
    identities: dict[str, UUID]

    async def resolve(
        self, request: Request, *, require_workspace: bool
    ) -> _AuthResult:
        del require_workspace
        user_id = self.identities.get(request.cookies.get("identity", ""))
        if user_id is None:
            raise HTTPException(status_code=401, detail="Authentication required.")
        return _AuthResult(_Claims(user_id))


class _ScopeRegistry:
    def __init__(self, scopes: dict[UUID, UUID]) -> None:
        self._scopes = scopes

    async def resolve(self, user_id: UUID) -> UUID:
        return self._scopes[user_id]


class _Embedder(Embedder):
    def embed_dense(self, texts) -> tuple[DenseVector, ...]:
        return tuple(DenseVector((1.0, 0.0, 0.0)) for _ in texts)

    def embed_sparse(self, texts) -> tuple[SparseVector, ...]:
        return tuple(SparseVector((1,), (1.0,)) for _ in texts)


def _build_app(
    tmp_path: Path,
    identities: dict[str, UUID],
    scopes: dict[UUID, UUID],
    *,
    include_settings: bool = False,
    provider_delay: float = 0.0,
) -> tuple[FastAPI, AsyncQdrantClient]:
    dependencies = PersonalLabRouteDependencies(
        _CookieAuth(identities),
        PersonalLabScopeResolver(_ScopeRegistry(scopes), tmp_path / "personal"),
    )
    qdrant = AsyncQdrantClient(location=":memory:")

    async def client_provider() -> AsyncQdrantClient:
        await asyncio.sleep(provider_delay)
        return qdrant

    app = FastAPI()
    app.add_middleware(
        SaasCsrfMiddleware,
        trusted_origins=("https://testserver",),
        protected_roots=("/api/personal",),
    )
    if include_settings:
        app.include_router(create_personal_settings_router(dependencies))
    app.include_router(
        create_personal_knowledge_router(
            dependencies, client_provider=client_provider, embedder=_Embedder()
        )
    )
    return app, qdrant


async def _exercise_private_lifecycle(
    client: httpx.AsyncClient, headers: dict[str, str]
) -> tuple[httpx.Response, ...]:
    client.cookies.set("__Host-ragstudio-csrf", "proof")
    client.cookies.set("identity", "a")
    uploaded = await client.post(
        "/api/personal/knowledge/upload",
        headers=headers,
        files={"file": ("same.txt", b"alpha private facts", "text/plain")},
    )
    duplicate = await client.post(
        "/api/personal/knowledge/upload",
        headers=headers,
        files={"file": ("same.txt", b"alpha private facts", "text/plain")},
    )
    cancelled, renamed, replaced = await _duplicate_actions(client, headers)
    first_list = await client.get("/api/personal/knowledge/documents")
    doc_id, file_id = uploaded.json()["doc_id"], uploaded.json()["file_id"]
    chunks = await client.get(f"/api/personal/knowledge/documents/{doc_id}/chunks")
    progress = await client.get(f"/api/personal/knowledge/progress/{file_id}")
    client.cookies.set("identity", "b")
    second_list = await client.get("/api/personal/knowledge/documents")
    foreign_doc = await client.get(f"/api/personal/knowledge/documents/{doc_id}/chunks")
    foreign_progress = await client.get(f"/api/personal/knowledge/progress/{file_id}")
    unsupported = await client.post(
        "/api/personal/knowledge/upload",
        headers=headers,
        files={"file": ("bad.exe", b"nope", "application/octet-stream")},
    )
    return (
        uploaded,
        duplicate,
        cancelled,
        renamed,
        replaced,
        first_list,
        chunks,
        progress,
        second_list,
        foreign_doc,
        foreign_progress,
        unsupported,
    )


async def _duplicate_actions(
    client: httpx.AsyncClient, headers: dict[str, str]
) -> tuple[httpx.Response, httpx.Response, httpx.Response]:
    async def upload(action: str, content: bytes) -> httpx.Response:
        return await client.post(
            f"/api/personal/knowledge/upload?action={action}",
            headers=headers,
            files={"file": ("same.txt", content, "text/plain")},
        )

    cancelled = await upload("cancel", b"alpha private facts")
    renamed = await upload("rename", b"alpha private facts")
    replaced = await upload("replace", b"replacement private facts")
    return cancelled, renamed, replaced


async def _exercise_reindex_lifecycle(
    client: httpx.AsyncClient, headers: dict[str, str]
) -> tuple[httpx.Response, ...]:
    client.cookies.set("__Host-ragstudio-csrf", "proof")
    client.cookies.set("identity", "a")
    uploaded = await client.post(
        "/api/personal/knowledge/upload",
        headers=headers,
        files={"file": ("source.csv", b"name,value\na,1\nb,2\n", "text/csv")},
    )
    text_upload = await client.post(
        "/api/personal/knowledge/upload",
        headers=headers,
        files={"file": ("notes.txt", b"scoped strategy text", "text/plain")},
    )
    saved = await client.post(
        "/api/personal/settings",
        headers=headers,
        json={
            "chunking": {"strategy": "static", "chunk_size": 256, "chunk_overlap": 32}
        },
    )
    text_id, csv_id = text_upload.json()["doc_id"], uploaded.json()["doc_id"]
    reindexed = await client.post(
        f"/api/personal/knowledge/documents/{text_id}/reindex", headers=headers
    )
    csv_chunks = await client.get(f"/api/personal/knowledge/documents/{csv_id}/chunks")
    text_chunks = await client.get(
        f"/api/personal/knowledge/documents/{text_id}/chunks"
    )
    deleted = await client.delete(
        f"/api/personal/knowledge/documents/{csv_id}", headers=headers
    )
    cleared = await client.delete("/api/personal/knowledge/clear", headers=headers)
    return (
        uploaded,
        text_upload,
        saved,
        reindexed,
        csv_chunks,
        text_chunks,
        deleted,
        cleared,
    )


def _assert_private_results(results: tuple[httpx.Response, ...]) -> None:
    uploaded, duplicate, cancelled, renamed, replaced = results[:5]
    first_list, chunks, progress, second_list = results[5:9]
    foreign_doc, foreign_progress, unsupported = results[9:]
    assert (uploaded.status_code, duplicate.status_code) == (201, 409)
    duplicate_body = duplicate.json()
    assert (duplicate_body["status"], duplicate_body["filename"]) == (
        "duplicate",
        "same.txt",
    )
    keys = (
        "existing_chunks",
        "existing_size",
        "stored_chunk_size",
        "stored_chunk_overlap",
        "new_file_size",
        "estimated_chunks",
        "chunks_settings_changed",
        "current_chunk_size",
        "current_chunk_overlap",
    )
    assert all(key in duplicate_body for key in keys)
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
    assert renamed.status_code == replaced.status_code == 201
    assert uploaded.json()["status"] == renamed.json()["status"] == "processing"
    assert renamed.json()["filename"] == "same (1).txt"
    assert replaced.json()["doc_id"] == uploaded.json()["doc_id"]
    assert len(first_list.json()["documents"]) == 2
    assert chunks.status_code == 200 and progress.json()["status"] == "done"
    assert chunks.json()["chunks"][0]["text"] == "replacement private facts"
    assert second_list.json()["documents"] == [] and unsupported.status_code == 415
    assert foreign_doc.status_code == foreign_progress.status_code == 404
    assert "alpha private facts" not in second_list.text


@pytest.mark.asyncio
async def test_personal_knowledge_http_lifecycle_is_private_and_scoped(
    tmp_path: Path,
) -> None:
    # Given: two cookie identities, CSRF protection, and a real in-memory Qdrant.
    first_user, second_user = uuid4(), uuid4()
    scopes = {first_user: uuid4(), second_user: uuid4()}
    app, qdrant = _build_app(
        tmp_path,
        {"a": first_user, "b": second_user},
        scopes,
    )
    headers = {"X-CSRF-Token": "proof", "Origin": "https://testserver"}
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(
            transport=transport, base_url="https://testserver"
        ) as client:
            results = await _exercise_private_lifecycle(client, headers)
        # Then: A sees the document; B sees neither IDs nor progress; failures are stable.
        _assert_private_results(results)
    finally:
        await qdrant.close()


@pytest.mark.asyncio
async def test_reindex_uses_only_personal_settings_and_delete_clear_are_scoped(
    tmp_path: Path,
) -> None:
    # Given: a Personal route with one document and caller-scoped chunk settings.
    first_user = uuid4()
    app, qdrant = _build_app(
        tmp_path,
        {"a": first_user},
        {first_user: uuid4()},
        include_settings=True,
    )
    transport = httpx.ASGITransport(app=app)
    headers = {"X-CSRF-Token": "proof", "Origin": "https://testserver"}
    try:
        async with httpx.AsyncClient(
            transport=transport, base_url="https://testserver"
        ) as client:
            results = await _exercise_reindex_lifecycle(client, headers)
        uploaded, text_upload, saved, reindexed = results[:4]
        csv_chunks, text_chunks, deleted, cleared = results[4:]

        # Then: CSV stays row-atomic and lifecycle mutations complete in one scope.
        assert uploaded.status_code == text_upload.status_code == 201
        assert saved.status_code == reindexed.status_code == 200
        assert [chunk["csv_row"] for chunk in csv_chunks.json()["chunks"]] == [0, 1]
        assert all(
            chunk["strategy"] == "csv_row" for chunk in csv_chunks.json()["chunks"]
        )
        assert all(
            chunk["strategy"] == "static" for chunk in text_chunks.json()["chunks"]
        )
        assert (deleted.json()["deleted"], cleared.json()["deleted"]) == (2, 1)
    finally:
        await qdrant.close()
