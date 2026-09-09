"""Ephemeral streaming adapter over the existing Personal Lab RAG graph."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Final, Literal, assert_never

import anyio
from pydantic import TypeAdapter, ValidationError

from src.api.personal_chat_state import CitationPayload, project_safe_citation
from src.api.personal_lab_scope import PersonalLabScope
from src.api.personal_lab_settings import (
    PersonalLabSettingsStore,
    PersonalSettingsPersistenceError,
)
from src.graph.graph_checkpoint_runtime import create_graph
from src.graph.graph_execution import GraphResultError, stream_rag_graph
from src.graph.llm_provider import OpenAIProviderFactory
from src.graph.nodes import CACHE_COLLECTION_NAME
from src.graph.personal_lab_execution import (
    _PROVIDER_SECRET,
    PersonalLabExecutionError,
    _ContextProviderFactory,
    _personal_graph_vector_store,
)
from src.vector_store.contracts import VectorStore
from src.vector_store.models import (
    DocumentMetadata,
    DocumentReplacement,
    JsonValue,
    VectorCollection,
    VectorRecord,
    VectorSearchHit,
    VectorSearchQuery,
)
from src.vector_store.pagination import ListingPage


@dataclass(frozen=True, slots=True)
class PublicToken:
    """One ordered provider token safe for public SSE framing."""

    value: str


@dataclass(frozen=True, slots=True)
class PublicResult:
    """Terminal safe citations after the graph has completed validation."""

    citations: tuple[CitationPayload, ...]


type PublicGraphEvent = PublicToken | PublicResult
type _GraphEventType = Literal["token", "result"]
_EVENT_TYPE: Final[TypeAdapter[_GraphEventType]] = TypeAdapter(_GraphEventType)


@dataclass(frozen=True, slots=True)
class _NoPublicHistoryVectorStore:
    delegate: VectorStore

    async def ensure_collection(self, collection: VectorCollection) -> None:
        if collection.name != CACHE_COLLECTION_NAME:
            await self.delegate.ensure_collection(collection)

    async def search(self, query: VectorSearchQuery) -> tuple[VectorSearchHit, ...]:
        if query.collection_name == CACHE_COLLECTION_NAME:
            return ()
        return await self.delegate.search(query)

    async def upsert(
        self, collection_name: str, records: Sequence[VectorRecord]
    ) -> None:
        if collection_name != CACHE_COLLECTION_NAME:
            await self.delegate.upsert(collection_name, records)

    async def find_document(self, filename: str) -> DocumentMetadata | None:
        return await self.delegate.find_document(filename)

    async def replace_document(self, replacement: DocumentReplacement) -> int:
        return await self.delegate.replace_document(replacement)

    async def list_documents(self, cursor: str | None = None) -> ListingPage:
        return await self.delegate.list_documents(cursor)

    async def list_chunks(self, doc_id: str, cursor: str | None = None) -> ListingPage:
        return await self.delegate.list_chunks(doc_id, cursor)

    async def delete_document(self, doc_id: str) -> int:
        return await self.delegate.delete_document(doc_id)

    async def clear_documents(self) -> int:
        return await self.delegate.clear_documents()


async def stream_public_personal_lab_graph(
    scope: PersonalLabScope, query: str, session_id: str
) -> AsyncIterator[PublicGraphEvent]:
    """Stream existing RAG behavior with memory-only state and no semantic cache."""
    settings_store = PersonalLabSettingsStore()
    provider_factory = OpenAIProviderFactory()
    try:
        record = await anyio.to_thread.run_sync(settings_store.load, scope)
        vector_store = _NoPublicHistoryVectorStore(
            await _personal_graph_vector_store(scope)
        )
        async with create_graph(
            provider_factory=_ContextProviderFactory(provider_factory),
            vector_store=vector_store,
        ) as graph:
            secret_token = _PROVIDER_SECRET.set(record.provider_secret)
            try:
                async for event in stream_rag_graph(
                    query,
                    session_id,
                    compiled_graph=graph,
                    persist_user_api_key=False,
                    provider=record.settings.provider,
                    model=record.settings.model,
                    temperature=record.settings.temperature,
                    max_tokens=record.settings.max_tokens,
                    system_prompt=record.settings.system_prompt,
                    top_k=record.settings.top_k,
                ):
                    yield _public_event(event)
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


def _public_event(event: Mapping[str, JsonValue]) -> PublicGraphEvent:
    try:
        event_type = _EVENT_TYPE.validate_python(event.get("type"))
    except ValidationError:
        raise PersonalLabExecutionError from None
    match event_type:
        case "token":
            token = event.get("token")
            if not isinstance(token, str) or not token:
                raise PersonalLabExecutionError
            return PublicToken(token)
        case "result":
            result = event.get("result")
            if not isinstance(result, Mapping):
                raise PersonalLabExecutionError
            raw_citations = result.get("citations", ())
            if not isinstance(raw_citations, Sequence) or isinstance(
                raw_citations, (str, bytes)
            ):
                raise PersonalLabExecutionError
            citations = tuple(
                project_safe_citation(item)
                for item in raw_citations
                if isinstance(item, Mapping)
            )
            return PublicResult(citations)
        case unreachable:
            assert_never(unreachable)
