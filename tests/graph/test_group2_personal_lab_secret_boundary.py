from __future__ import annotations

import sqlite3
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage
from qdrant_client.http import models as qmodels

from src.api.personal_lab_scope import PersonalLabScope
from src.api.personal_lab_settings import PersonalLabSettingsStore, PersonalSettings
from src.graph import personal_lab_execution
from src.graph.llm_provider import LLMProviderConfig
from src.graph.personal_lab_checkpoint import PersonalLabCheckpoint
from src.graph.personal_lab_execution import run_personal_lab_graph
from src.vector_store.models import (
    DenseVector,
    SparseVector,
    VectorCollection,
    VectorRecord,
    VectorSearchHit,
    VectorSearchQuery,
)


class _DeterministicProvider:
    def __init__(self, invoke_reply: str, stream_reply: str = "") -> None:
        self._invoke_reply = invoke_reply
        self._stream_reply = stream_reply

    async def ainvoke(self, messages: Sequence[BaseMessage]) -> BaseMessage:
        del messages
        return AIMessage(content=self._invoke_reply)

    async def astream(
        self, messages: Sequence[BaseMessage]
    ) -> AsyncIterator[AIMessageChunk]:
        del messages
        if self._stream_reply:
            yield AIMessageChunk(content=self._stream_reply)


class _CapturingProviderFactory:
    def __init__(self) -> None:
        self.configs: list[LLMProviderConfig] = []

    def __call__(self, config: LLMProviderConfig) -> _DeterministicProvider:
        self.configs.append(config)
        return _DeterministicProvider("follow_up")


class _DeterministicEmbedder:
    def embed_dense(self, texts: Sequence[str]) -> tuple[DenseVector, ...]:
        return tuple(DenseVector((1.0,) * 384) for _ in texts)

    def embed_sparse(self, texts: Sequence[str]) -> tuple[SparseVector, ...]:
        return tuple(SparseVector((1,), (1.0,)) for _ in texts)


class _DeterministicVectorStore:
    async def ensure_collection(self, collection: VectorCollection) -> None:
        del collection

    async def search(self, query: VectorSearchQuery) -> tuple[VectorSearchHit, ...]:
        del query
        return (
            VectorSearchHit(
                point_id="personal-result",
                score=0.95,
                payload={
                    "answer": "synthetic cached answer",
                    "text": "private synthetic context",
                    "source": "synthetic.txt",
                },
            ),
        )

    async def upsert(
        self, collection_name: str, records: Sequence[VectorRecord]
    ) -> None:
        del collection_name, records


class _SyntheticGraphFailure(RuntimeError):
    def __str__(self) -> str:
        return "synthetic failure"


class _CapturingPersonalClient:
    def __init__(self) -> None:
        self.created_collections: list[str] = []
        self.cache_query_collections: list[str] = []
        self.cache_filters: list[qmodels.Filter] = []
        self.cache_write_collections: list[str] = []

    async def collection_exists(self, collection_name: str) -> bool:
        del collection_name
        return False

    async def create_collection(self, *, collection_name: str, **_: object) -> None:
        self.created_collections.append(collection_name)

    async def query_points(
        self, *, collection_name: str, query_filter: qmodels.Filter, **_: object
    ) -> qmodels.QueryResponse:
        self.cache_query_collections.append(collection_name)
        self.cache_filters.append(query_filter)
        return qmodels.QueryResponse(points=[])

    async def upsert(self, *, collection_name: str, **_: object) -> None:
        self.cache_write_collections.append(collection_name)


class _GraphResult:
    async def ainvoke(self, _: object, __: object) -> dict[str, object]:
        return {
            "final_answer": "scoped result",
            "generated_from": "retrieval",
            "faithfulness_score": 1.0,
            "retrieved_docs": [],
        }


@pytest.mark.asyncio
async def test_server_resolved_secret_never_enters_graph_state_or_checkpoint(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Given: encrypted scoped settings and deterministic real graph capabilities.
    monkeypatch.setenv("RAG_STUDIO_DATA_ROOT", str(tmp_path / "runtime"))
    scope_id = uuid4()
    scope = PersonalLabScope(
        scope_id,
        f"pl_{scope_id.hex}",
        tmp_path / f"pl_{scope_id.hex}",
        f"pl_{scope_id.hex}",
    )
    store = PersonalLabSettingsStore()
    store.save(
        scope,
        PersonalSettings(provider="deepseek", model="deepseek-chat"),
        provider_secret="synthetic-graph-secret",
    )
    provider_factory = _CapturingProviderFactory()
    checkpoint_path = scope.data_root / "checkpoints.sqlite"

    # When: the production Personal path executes with a real AsyncSqliteSaver.
    result = await run_personal_lab_graph(
        scope,
        query="synthetic question",
        session_id="session-a",
        settings_store=store,
        provider_factory=provider_factory,
        embedder=_DeterministicEmbedder(),
        vector_store=_DeterministicVectorStore(),
    )

    # Then: closure configs receive the key, while actual SQLite rows never do.
    assert result["final_answer"] == "synthetic cached answer"
    assert checkpoint_path.is_file()
    assert provider_factory.configs
    assert all(
        config.api_key is not None
        and config.api_key.get_secret_value() == "synthetic-graph-secret"
        for config in provider_factory.configs
    )
    assert b"synthetic-graph-secret" not in checkpoint_path.read_bytes()
    with sqlite3.connect(checkpoint_path) as connection:
        rows = connection.execute(
            "SELECT checkpoint, metadata FROM checkpoints"
        ).fetchall()
    assert rows
    assert "synthetic-graph-secret" not in repr(rows)
    assert "synthetic-graph-secret" not in caplog.text

    # And: a restart can load the completed checkpoint after settings are absent.
    store.path_for(scope).unlink()
    assert PersonalLabCheckpoint(checkpoint_path).path.stat().st_size > 0


def test_checkpoint_failure_restores_prior_database(tmp_path: Path) -> None:
    # Given: a completed-session checkpoint already exists.
    path = tmp_path / "scope" / "checkpoints.sqlite"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"completed-session")
    checkpoint = PersonalLabCheckpoint(path)

    # When: a later transaction mutates the file and fails.
    with (
        pytest.raises(_SyntheticGraphFailure, match="synthetic failure"),
        checkpoint.preserve_on_failure(),
    ):
        path.write_bytes(b"partial-session")
        raise _SyntheticGraphFailure

    # Then: the completed checkpoint survives byte-for-byte.
    assert path.read_bytes() == b"completed-session"
    assert not checkpoint.rollback_path.exists()


@pytest.mark.asyncio
async def test_personal_graph_binds_scoped_default_and_preserves_injected_store(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _CapturingPersonalClient()
    settings_store = PersonalLabSettingsStore()
    first_id = uuid4()
    second_id = uuid4()
    first_scope = PersonalLabScope(
        first_id,
        f"pl_{first_id.hex}",
        tmp_path / "first",
        f"pl_{first_id.hex}",
    )
    second_scope = PersonalLabScope(
        second_id,
        f"pl_{second_id.hex}",
        tmp_path / "second",
        f"pl_{second_id.hex}",
    )
    for scope in (first_scope, second_scope):
        settings_store.save(
            scope,
            PersonalSettings(provider="deepseek", model="deepseek-chat"),
            provider_secret="synthetic-graph-secret",
        )

    async def client_provider() -> _CapturingPersonalClient:
        return client

    @asynccontextmanager
    async def capturing_create_graph(*_: object, **kwargs: object):
        selected = kwargs["vector_store"]
        await selected.ensure_collection(VectorCollection("ignored", 384, sparse=True))
        await selected.search(
            VectorSearchQuery("rag_studio_cache", DenseVector((1.0,)), limit=1)
        )
        await selected.upsert(
            "rag_studio_cache",
            (VectorRecord("cache", DenseVector((1.0,)), {"answer": "private"}),),
        )
        yield _GraphResult()

    monkeypatch.setattr(
        personal_lab_execution, "get_qdrant_client", client_provider, raising=False
    )
    monkeypatch.setattr(personal_lab_execution, "create_graph", capturing_create_graph)

    for scope in (first_scope, second_scope):
        result = await run_personal_lab_graph(
            scope,
            query="synthetic question",
            session_id=f"session-{scope.id.hex}",
            settings_store=settings_store,
        )
        assert result["final_answer"] == "scoped result"

    assert client.created_collections == [
        first_scope.collection_name,
        second_scope.collection_name,
    ]
    assert client.cache_query_collections == client.created_collections
    assert client.cache_write_collections == client.created_collections
    assert [
        (condition.key, condition.match.value)
        for cache_filter in client.cache_filters
        for condition in cache_filter.must
    ] == [("record_type", "semantic_cache"), ("record_type", "semantic_cache")]

    injected_store = _DeterministicVectorStore()
    selected_stores: list[_DeterministicVectorStore] = []

    @asynccontextmanager
    async def capturing_create_graph(*_: object, **kwargs: object):
        selected_stores.append(kwargs["vector_store"])
        yield _GraphResult()

    async def unexpected_client_resolution() -> _CapturingPersonalClient:
        raise AssertionError("injected vector store must prevent default resolution")

    monkeypatch.setattr(
        personal_lab_execution, "get_qdrant_client", unexpected_client_resolution
    )
    monkeypatch.setattr(personal_lab_execution, "create_graph", capturing_create_graph)

    await run_personal_lab_graph(
        first_scope,
        query="synthetic question",
        session_id="session-injected",
        settings_store=settings_store,
        vector_store=injected_store,
    )

    assert selected_stores == [injected_store]
