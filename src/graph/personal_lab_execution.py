"""Server-side provider resolution before Personal Lab graph execution."""

from __future__ import annotations

from collections.abc import Sequence
from contextlib import (
    AbstractAsyncContextManager,
    AbstractContextManager,
    asynccontextmanager,
)
from contextvars import ContextVar
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any
from uuid import UUID

import anyio
from pydantic import SecretStr
from qdrant_client.http import models as qmodels

from src.api.personal_lab_scope import PersonalLabScope
from src.api.personal_lab_settings import (
    PersonalLabSettingsStore,
    PersonalSettingsPersistenceError,
)
from src.graph.graph_checkpoint_runtime import create_graph
from src.graph.graph_execution import GraphResultError, run_rag_graph
from src.graph.llm_provider import (
    LLMProvider,
    LLMProviderConfig,
    LLMProviderFactory,
    OpenAIProviderFactory,
)
from src.graph.personal_lab_checkpoint import PersonalLabCheckpoint
from src.ingestion.embedding import Embedder
from src.vector_store.client import get_qdrant_client
from src.vector_store.contracts import VectorStore
from src.vector_store.models import (
    DocumentMetadata,
    DocumentReplacement,
    PersonalVectorScope,
    VectorCollection,
    VectorRecord,
    VectorSearchHit,
    VectorSearchQuery,
)
from src.vector_store.pagination import ListingPage
from src.vector_store.personal_store import PersonalRagStore, PersonalVectorSearch
from src.vector_store.qdrant_translation import (
    to_qdrant_point,
    to_qdrant_sparse,
    to_search_hit,
    translated_errors,
)

_CACHE_COLLECTION_NAME = "rag_studio_cache"
_CACHE_RECORD_TYPE = "semantic_cache"
_DEFAULT_PROVIDER_FACTORY = OpenAIProviderFactory()
_PROVIDER_SECRET: ContextVar[str | None] = ContextVar(
    "personal_lab_provider_secret", default=None
)


@dataclass(frozen=True, slots=True)
class _ContextProviderFactory:
    delegate: LLMProviderFactory

    def __call__(self, config: LLMProviderConfig) -> LLMProvider:
        secret = _PROVIDER_SECRET.get()
        return self.delegate(
            replace(config, api_key=SecretStr(secret) if secret is not None else None)
        )


type _GraphKey = tuple[UUID, Path, int, int, int]


@dataclass(slots=True)
class _GraphEntry:
    graph: Any
    graph_context: AbstractAsyncContextManager[Any]
    checkpoint_context: AbstractContextManager[None]
    users: int = 0
    failure: BaseException | None = None


class _OverlappingGraphPool:
    def __init__(self) -> None:
        self._lock = anyio.Lock()
        self._entries: dict[_GraphKey, _GraphEntry] = {}

    @asynccontextmanager
    async def lease(
        self,
        scope: PersonalLabScope,
        *,
        provider_factory: LLMProviderFactory,
        embedder: Embedder | None,
        vector_store: VectorStore | None,
    ) -> Any:
        key = (
            scope.id,
            scope.data_root,
            id(provider_factory),
            id(embedder),
            id(vector_store),
        )
        entry = await self._acquire(
            key,
            scope,
            provider_factory=provider_factory,
            embedder=embedder,
            vector_store=vector_store,
        )
        failure: BaseException | None = None
        try:
            yield entry.graph
        except BaseException as error:
            failure = error
            raise
        finally:
            with anyio.CancelScope(shield=True):
                cleanup_error = await self._release(key, entry, failure)
            if failure is None and cleanup_error is not None:
                raise cleanup_error

    async def _acquire(
        self,
        key: _GraphKey,
        scope: PersonalLabScope,
        *,
        provider_factory: LLMProviderFactory,
        embedder: Embedder | None,
        vector_store: VectorStore | None,
    ) -> _GraphEntry:
        async with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                selected_store = vector_store or await _personal_graph_vector_store(
                    scope
                )
                checkpoint = PersonalLabCheckpoint(
                    scope.data_root / "checkpoints.sqlite"
                )
                checkpoint_context = checkpoint.preserve_on_failure()
                checkpoint_context.__enter__()
                graph_context = create_graph(
                    db_path=str(checkpoint.path),
                    provider_factory=_ContextProviderFactory(provider_factory),
                    embedder=embedder,
                    vector_store=selected_store,
                )
                try:
                    graph = await graph_context.__aenter__()
                except BaseException as error:
                    try:
                        checkpoint_context.__exit__(
                            type(error), error, error.__traceback__
                        )
                    except BaseException as rollback_error:
                        if rollback_error is not error:
                            raise rollback_error from error
                    raise
                entry = _GraphEntry(graph, graph_context, checkpoint_context)
                self._entries[key] = entry
            entry.users += 1
            return entry

    async def _release(
        self,
        key: _GraphKey,
        entry: _GraphEntry,
        failure: BaseException | None,
    ) -> BaseException | None:
        async with self._lock:
            entry.failure = entry.failure or failure
            entry.users -= 1
            if entry.users > 0:
                return None
            cleanup_error: BaseException | None = None
            try:
                await entry.graph_context.__aexit__(None, None, None)
            except BaseException as error:  # noqa: BLE001 -- managed context may propagate cancellation
                cleanup_error = error
                entry.failure = entry.failure or error
            try:
                self._finish_checkpoint(entry)
            finally:
                self._entries.pop(key, None)
            return cleanup_error

    @staticmethod
    def _finish_checkpoint(entry: _GraphEntry) -> None:
        failure = entry.failure
        if failure is None:
            entry.checkpoint_context.__exit__(None, None, None)
            return
        try:
            entry.checkpoint_context.__exit__(
                type(failure), failure, failure.__traceback__
            )
        except BaseException as rollback_error:
            if rollback_error is not failure:
                raise rollback_error from failure


_GRAPH_POOL = _OverlappingGraphPool()


@dataclass(frozen=True, slots=True)
class _PersonalGraphVectorStore:
    personal_store: PersonalRagStore

    async def ensure_collection(self, collection: VectorCollection) -> None:
        await self.personal_store.ensure_ready(dense_size=collection.dense_size)

    async def search(self, query: VectorSearchQuery) -> tuple[VectorSearchHit, ...]:
        match query.collection_name:
            case collection_name if collection_name == _CACHE_COLLECTION_NAME:
                return await self._search_cache(query)
            case _:
                return await self.personal_store.search_documents(
                    PersonalVectorSearch(
                        query.dense,
                        query.sparse,
                        query.limit,
                        query.score_threshold,
                    )
                )

    async def upsert(
        self, collection_name: str, records: Sequence[VectorRecord]
    ) -> None:
        match collection_name:
            case selected_name if selected_name == _CACHE_COLLECTION_NAME:
                await self._upsert_cache(records)
            case _:
                raise PersonalLabExecutionError

    async def find_document(self, filename: str) -> DocumentMetadata | None:
        return await self.personal_store.find_document(filename)

    async def replace_document(self, replacement: DocumentReplacement) -> int:
        return await self.personal_store.replace_document(replacement)

    async def list_documents(self, cursor: str | None = None) -> ListingPage:
        return await self.personal_store.list_documents(cursor)

    async def list_chunks(self, doc_id: str, cursor: str | None = None) -> ListingPage:
        return await self.personal_store.list_chunks(doc_id, cursor)

    async def delete_document(self, doc_id: str) -> int:
        return await self.personal_store.delete_document(doc_id)

    async def clear_documents(self) -> int:
        return await self.personal_store.clear_documents()

    async def _search_cache(
        self, query: VectorSearchQuery
    ) -> tuple[VectorSearchHit, ...]:
        filters = qmodels.Filter(
            must=[
                qmodels.FieldCondition(
                    key="record_type",
                    match=qmodels.MatchValue(value=_CACHE_RECORD_TYPE),
                )
            ]
        )
        async with translated_errors():
            match query.sparse:
                case None:
                    response = await self.personal_store.client.query_points(
                        collection_name=self.personal_store.scope.collection_name,
                        query=list(query.dense.values),
                        using="dense",
                        query_filter=filters,
                        limit=query.limit,
                        with_payload=True,
                        score_threshold=query.score_threshold,
                    )
                case sparse:
                    response = await self.personal_store.client.query_points(
                        collection_name=self.personal_store.scope.collection_name,
                        prefetch=[
                            qmodels.Prefetch(
                                query=list(query.dense.values),
                                using="dense",
                                filter=filters,
                                limit=query.limit * 3,
                            ),
                            qmodels.Prefetch(
                                query=to_qdrant_sparse(sparse),
                                using="sparse",
                                filter=filters,
                                limit=query.limit * 3,
                            ),
                        ],
                        query=qmodels.FusionQuery(fusion=qmodels.Fusion.RRF),
                        query_filter=filters,
                        limit=query.limit,
                        with_payload=True,
                        score_threshold=query.score_threshold,
                    )
        return tuple(to_search_hit(point) for point in response.points)

    async def _upsert_cache(self, records: Sequence[VectorRecord]) -> None:
        scoped_records = tuple(
            VectorRecord(
                record.point_id,
                record.dense,
                {**record.payload, "record_type": _CACHE_RECORD_TYPE},
                record.sparse,
            )
            for record in records
        )
        async with translated_errors():
            await self.personal_store.client.upsert(
                collection_name=self.personal_store.scope.collection_name,
                points=[to_qdrant_point(record) for record in scoped_records],
                wait=True,
            )


async def _personal_graph_vector_store(scope: PersonalLabScope) -> VectorStore:
    client = await get_qdrant_client()
    return _PersonalGraphVectorStore(
        PersonalRagStore(client, PersonalVectorScope(scope.id, scope.collection_name))
    )


class PersonalLabExecutionError(RuntimeError):
    """Report provider or checkpoint failure without exposing backend details."""

    def __str__(self) -> str:
        return "Personal Lab execution failed."


async def run_personal_lab_graph(
    scope: PersonalLabScope,
    *,
    query: str,
    session_id: str,
    settings_store: PersonalLabSettingsStore | None = None,
    provider_factory: LLMProviderFactory | None = None,
    embedder: Embedder | None = None,
    vector_store: VectorStore | None = None,
) -> dict[str, Any]:
    """Resolve encrypted configuration and execute with a secret-free state."""
    store = settings_store or PersonalLabSettingsStore()
    factory = provider_factory or _DEFAULT_PROVIDER_FACTORY
    try:
        record = await anyio.to_thread.run_sync(store.load, scope)
        settings = record.settings
        async with _GRAPH_POOL.lease(
            scope,
            provider_factory=factory,
            embedder=embedder,
            vector_store=vector_store,
        ) as graph:
            secret_token = _PROVIDER_SECRET.set(record.provider_secret)
            try:
                return await run_rag_graph(
                    query,
                    session_id,
                    compiled_graph=graph,
                    persist_user_api_key=False,
                    provider=settings.provider,
                    model=settings.model,
                    temperature=settings.temperature,
                    max_tokens=settings.max_tokens,
                    system_prompt=settings.system_prompt,
                    top_k=settings.top_k,
                )
            finally:
                _PROVIDER_SECRET.reset(secret_token)
    except (
        GraphResultError,
        PersonalSettingsPersistenceError,
        OSError,
        RuntimeError,
        TimeoutError,
    ):
        raise PersonalLabExecutionError from None
