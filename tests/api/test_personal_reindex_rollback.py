from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import pytest

from src.api.personal_lab_scope import PersonalLabScope, PersonalLabScopeResolver
from src.ingestion.personal_storage import (
    PersonalKnowledgeStorage,
    PersonalKnowledgeStorageError,
    StoredPersonalDocument,
)
from tests.api.test_group2_personal_lab_ingestion import _build_app


@dataclass(frozen=True, slots=True)
class _FailingUpdateStorage(PersonalKnowledgeStorage):
    should_fail: Callable[[], bool]

    def update_chunks(
        self,
        scope: PersonalLabScope,
        doc_id: UUID,
        chunk_count: int,
        chunk_size: int,
        chunk_overlap: int,
        strategy: str,
    ) -> StoredPersonalDocument:
        if self.should_fail():
            raise PersonalKnowledgeStorageError
        return super().update_chunks(
            scope,
            doc_id,
            chunk_count,
            chunk_size,
            chunk_overlap,
            strategy,
        )


@pytest.mark.asyncio
async def test_successful_reindex_returns_and_persists_fresh_chunking_metadata(
    tmp_path: Path,
) -> None:
    storage = PersonalKnowledgeStorage()
    user_id, scope_id = uuid4(), uuid4()
    app, qdrant = _build_app(
        tmp_path,
        {"a": user_id},
        {user_id: scope_id},
        include_settings=True,
        storage=storage,
    )
    scope = await PersonalLabScopeResolver(
        _StaticScopeRegistry(scope_id), tmp_path / "personal"
    ).resolve(user_id)
    headers = {"X-CSRF-Token": "proof", "Origin": "https://testserver"}
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(
            transport=transport, base_url="https://testserver"
        ) as client:
            client.cookies.set("__Host-ragstudio-csrf", "proof")
            client.cookies.set("identity", "a")
            uploaded = await _upload_baseline(client, headers)
            doc_id = uploaded.json()["doc_id"]
            await _save_static_settings(client, headers)
            reindexed = await client.post(
                f"/api/personal/knowledge/documents/{doc_id}/reindex",
                headers=headers,
            )
        persisted = storage.document(scope, UUID(doc_id))
        assert reindexed.status_code == 200
        assert (
            reindexed.json()["chunk_count"],
            reindexed.json()["chunk_size"],
            reindexed.json()["chunk_overlap"],
            reindexed.json()["strategy"],
        ) == (1, 256, 32, "static")
        assert persisted is not None
        assert (
            persisted.chunk_count,
            persisted.chunk_size,
            persisted.chunk_overlap,
            persisted.strategy,
        ) == (reindexed.json()["chunk_count"], 256, 32, "static")
    finally:
        await qdrant.close()


@dataclass(frozen=True, slots=True)
class _StaticScopeRegistry:
    scope_id: UUID

    async def resolve(self, user_id: UUID) -> UUID:
        del user_id
        return self.scope_id


async def _upload_baseline(
    client: httpx.AsyncClient, headers: dict[str, str]
) -> httpx.Response:
    return await client.post(
        "/api/personal/knowledge/upload",
        headers=headers,
        files={
            "file": (
                "personal-reindex-proof.md",
                b"Synthetic baseline citation marker.",
                "text/markdown",
            )
        },
    )


async def _save_static_settings(
    client: httpx.AsyncClient, headers: dict[str, str]
) -> httpx.Response:
    return await client.post(
        "/api/personal/settings",
        headers=headers,
        json={
            "chunking": {
                "strategy": "static",
                "chunk_size": 256,
                "chunk_overlap": 32,
            }
        },
    )


@pytest.mark.asyncio
async def test_failed_reindex_keeps_previous_personal_chunks(
    tmp_path: Path,
) -> None:
    fail_update = False
    storage = _FailingUpdateStorage(lambda: fail_update)
    user_id, scope_id = uuid4(), uuid4()
    app, qdrant = _build_app(
        tmp_path,
        {"a": user_id},
        {user_id: scope_id},
        include_settings=True,
        storage=storage,
    )
    headers = {"X-CSRF-Token": "proof", "Origin": "https://testserver"}
    transport = httpx.ASGITransport(app=app)
    scope = await PersonalLabScopeResolver(
        _StaticScopeRegistry(scope_id), tmp_path / "personal"
    ).resolve(user_id)
    try:
        async with httpx.AsyncClient(
            transport=transport, base_url="https://testserver"
        ) as client:
            client.cookies.set("__Host-ragstudio-csrf", "proof")
            client.cookies.set("identity", "a")
            uploaded = await _upload_baseline(client, headers)
            doc_id = uploaded.json()["doc_id"]
            before = await client.get(
                f"/api/personal/knowledge/documents/{doc_id}/chunks"
            )
            documents_before = await client.get("/api/personal/knowledge/documents")
            persisted_before = storage.document(scope, UUID(doc_id))
            await _save_static_settings(client, headers)
            fail_update = True
            failed = await client.post(
                f"/api/personal/knowledge/documents/{doc_id}/reindex",
                headers=headers,
            )
            after = await client.get(
                f"/api/personal/knowledge/documents/{doc_id}/chunks"
            )
            documents_after = await client.get("/api/personal/knowledge/documents")
        assert uploaded.status_code == 201
        assert failed.status_code == 503
        assert after.json()["chunks"] == before.json()["chunks"]
        assert documents_after.json() == documents_before.json()
        assert documents_after.json()["documents"][0]["filename"] == (
            "personal-reindex-proof.md"
        )
        persisted_after = storage.document(scope, UUID(doc_id))
        assert persisted_before is not None and persisted_after is not None
        assert (
            persisted_after.chunk_count,
            persisted_after.chunk_size,
            persisted_after.chunk_overlap,
            persisted_after.strategy,
        ) == (
            persisted_before.chunk_count,
            persisted_before.chunk_size,
            persisted_before.chunk_overlap,
            persisted_before.strategy,
        )
    finally:
        await qdrant.close()
