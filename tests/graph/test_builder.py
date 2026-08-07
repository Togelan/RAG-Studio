from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from typing import Any

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, HumanMessage

from src.graph.builder import (
    build_rag_graph,
    create_graph,
    route_after_analyzer,
    route_after_cache_check,
    route_after_validate,
    run_rag_graph,
)
from src.graph.llm_provider import LLMProviderConfig
from src.graph.nodes import CACHE_COLLECTION_NAME
from src.graph.state import RAGState
from src.ingestion.embedding import Embedder
from src.vector_store.models import (
    DenseVector,
    SparseVector,
    VectorCollection,
    VectorRecord,
    VectorSearchHit,
    VectorSearchQuery,
)


@dataclass(frozen=True, slots=True)
class _ProviderReply:
    invoke_content: str
    stream_content: str = ""


class _DeterministicProvider:
    def __init__(self, reply: _ProviderReply) -> None:
        self._reply = reply

    async def ainvoke(self, messages: Sequence[BaseMessage]) -> BaseMessage:
        return AIMessage(content=self._reply.invoke_content)

    async def astream(
        self, messages: Sequence[BaseMessage]
    ) -> AsyncIterator[AIMessageChunk]:
        if self._reply.stream_content:
            yield AIMessageChunk(content=self._reply.stream_content)


class _ScriptedProviderFactory:
    def __init__(self, replies: tuple[_ProviderReply, ...]) -> None:
        self._replies = iter(replies)

    def __call__(self, config: LLMProviderConfig) -> _DeterministicProvider:
        return _DeterministicProvider(next(self._replies))


@dataclass(frozen=True, slots=True)
class _DeterministicEmbedder:
    def embed_dense(self, texts: Sequence[str]) -> tuple[DenseVector, ...]:
        return tuple(DenseVector((1.0,) * 384) for _ in texts)

    def embed_sparse(self, texts: Sequence[str]) -> tuple[SparseVector, ...]:
        return tuple(SparseVector((1,), (1.0,)) for _ in texts)


class _DeterministicVectorStore:
    def __init__(
        self,
        *,
        cache_hits: tuple[VectorSearchHit, ...] = (),
        retrieval_hits: tuple[VectorSearchHit, ...] = (),
    ) -> None:
        self._cache_hits = cache_hits
        self._retrieval_hits = retrieval_hits
        self.saved_records: list[VectorRecord] = []

    async def ensure_collection(self, collection: VectorCollection) -> None:
        return None

    async def search(self, query: VectorSearchQuery) -> tuple[VectorSearchHit, ...]:
        if query.collection_name == CACHE_COLLECTION_NAME:
            return self._cache_hits
        return self._retrieval_hits

    async def upsert(
        self, collection_name: str, records: Sequence[VectorRecord]
    ) -> None:
        self.saved_records.extend(records)


_EMBEDDER: Embedder = _DeterministicEmbedder()


def _make_state(**overrides: Any) -> RAGState:
    defaults: RAGState = {
        "messages": [HumanMessage(content="What is machine learning?")],
        "query": "What is machine learning?",
        "intent": "",
        "cache_hit": False,
        "cached_answer": None,
        "retrieved_docs": [],
        "reranked_docs": [],
        "generated_from": "",
        "final_answer": None,
        "faithfulness_score": 0.0,
        "validation_passed": False,
        "session_id": "test-session-001",
        "user_api_key": None,
        "provider": "openai",
        "model_name": "gpt-4o-mini",
        "temperature": 1.0,
        "max_tokens": 2048,
        "system_prompt": "",
    }
    defaults.update(overrides)
    return defaults


def _retrieval_hit(
    text: str = "Machine learning is a subset of AI.",
) -> VectorSearchHit:
    return VectorSearchHit(
        point_id="retrieval-1",
        score=0.95,
        payload={"text": text, "source": "ai_intro.md", "chunk_index": 3},
    )


def _cache_hit(answer: str) -> VectorSearchHit:
    return VectorSearchHit(
        point_id="cache-1",
        score=0.95,
        payload={"answer": answer},
    )


def _provider_factory_for_retrieval(
    *, answer: str, faithfulness: str = "0.9"
) -> _ScriptedProviderFactory:
    return _ScriptedProviderFactory(
        (
            _ProviderReply("standalone"),
            _ProviderReply("", stream_content=answer),
            _ProviderReply(faithfulness),
        )
    )


class TestRoutingFunctions:
    def test_route_after_analyzer_follow_up(self) -> None:
        assert (
            route_after_analyzer(_make_state(intent="follow_up_question"))
            == "cache_check"
        )

    def test_route_after_analyzer_standalone(self) -> None:
        assert (
            route_after_analyzer(_make_state(intent="standalone_question"))
            == "retrieve"
        )

    def test_route_after_cache_check_hit(self) -> None:
        assert (
            route_after_cache_check(_make_state(cache_hit=True))
            == "generate_from_cache"
        )

    def test_route_after_cache_check_miss(self) -> None:
        assert route_after_cache_check(_make_state(cache_hit=False)) == "retrieve"

    def test_route_after_validate_cache_source(self) -> None:
        assert route_after_validate(_make_state(generated_from="cache")) == "end"

    def test_route_after_validate_passing_retrieval(self) -> None:
        assert (
            route_after_validate(
                _make_state(generated_from="retrieval", validation_passed=True)
            )
            == "save_to_cache"
        )

    def test_route_after_validate_failing_retrieval(self) -> None:
        assert route_after_validate(_make_state(generated_from="retrieval")) == "end"


class TestGraphConstruction:
    def test_graph_compiles_with_injected_capabilities(self) -> None:
        from langgraph.checkpoint.memory import MemorySaver

        graph = build_rag_graph(
            _provider_factory_for_retrieval(answer="answer"),
            embedder=_EMBEDDER,
            vector_store=_DeterministicVectorStore(),
        ).compile(checkpointer=MemorySaver())

        assert graph is not None


class TestFullGraphFlow:
    @pytest.mark.asyncio
    async def test_standalone_question_flows_through_all_nodes(self) -> None:
        from langgraph.checkpoint.memory import MemorySaver

        store = _DeterministicVectorStore(retrieval_hits=(_retrieval_hit(),))
        graph = build_rag_graph(
            _provider_factory_for_retrieval(answer="Machine learning is AI [1]."),
            embedder=_EMBEDDER,
            vector_store=store,
        ).compile(checkpointer=MemorySaver())

        result = await run_rag_graph(
            query="What is machine learning?",
            session_id="test-session-standalone",
            compiled_graph=graph,
        )

        assert result["generated_from"] == "retrieval"
        assert result["final_answer"] == "Machine learning is AI [1]."
        assert len(store.saved_records) == 1

    @pytest.mark.asyncio
    async def test_follow_up_cache_hit_bypasses_retrieval(self) -> None:
        from langgraph.checkpoint.memory import MemorySaver

        answer = "ML is machine learning, a subset of AI."
        store = _DeterministicVectorStore(cache_hits=(_cache_hit(answer),))
        provider_factory = _ScriptedProviderFactory((_ProviderReply("follow_up"),))
        graph = build_rag_graph(
            provider_factory,
            embedder=_EMBEDDER,
            vector_store=store,
        ).compile(checkpointer=MemorySaver())

        result = await run_rag_graph(
            query="Tell me more about ML",
            session_id="test-session-cache-hit",
            compiled_graph=graph,
        )

        assert result["generated_from"] == "cache"
        assert result["final_answer"] == answer
        assert store.saved_records == []

    @pytest.mark.asyncio
    async def test_empty_retrieval_returns_generated_response(self) -> None:
        from langgraph.checkpoint.memory import MemorySaver

        provider_factory = _ScriptedProviderFactory(
            (
                _ProviderReply("standalone"),
                _ProviderReply("", stream_content="No matching information."),
            )
        )
        graph = build_rag_graph(
            provider_factory,
            embedder=_EMBEDDER,
            vector_store=_DeterministicVectorStore(),
        ).compile(checkpointer=MemorySaver())

        result = await run_rag_graph(
            query="xyzzy nonsense",
            session_id="test-empty-retrieval",
            compiled_graph=graph,
        )

        assert result["generated_from"] == "retrieval"
        assert result["final_answer"] == "No matching information."
        assert result["faithfulness_score"] == 0.0

    @pytest.mark.asyncio
    async def test_citations_are_built_from_injected_retrieval_hits(self) -> None:
        from langgraph.checkpoint.memory import MemorySaver

        store = _DeterministicVectorStore(
            retrieval_hits=(_retrieval_hit("Document chunk about ML."),)
        )
        graph = build_rag_graph(
            _provider_factory_for_retrieval(answer="Answer with citation [1]."),
            embedder=_EMBEDDER,
            vector_store=store,
        ).compile(checkpointer=MemorySaver())

        result = await run_rag_graph(
            query="What is ML?",
            session_id="test-citations",
            compiled_graph=graph,
        )

        assert result["citations"] == [
            {
                "index": 1,
                "chunk_text": "Document chunk about ML.",
                "filename": "ai_intro.md",
                "chunk_index": "3",
                "score": 0.95,
                "location_unavailable": True,
            }
        ]


class TestPersistenceAcrossRestarts:
    @pytest.mark.asyncio
    async def test_session_persists_across_new_graph_instance(
        self, tmp_path: Any
    ) -> None:
        db_path = str(tmp_path / "test_persistence.db")
        store = _DeterministicVectorStore(retrieval_hits=(_retrieval_hit(),))

        async with create_graph(
            db_path,
            _provider_factory_for_retrieval(answer="Persisted answer [1]."),
            embedder=_EMBEDDER,
            vector_store=store,
        ) as graph:
            result = await run_rag_graph(
                query="Who is Masha?",
                session_id="persist-test-session-001",
                compiled_graph=graph,
            )

        assert result["final_answer"] == "Persisted answer [1]."

        async with create_graph(
            db_path,
            embedder=_EMBEDDER,
            vector_store=store,
        ) as graph:
            from src.graph.session import get_session_metadata

            metadata = await get_session_metadata(
                "persist-test-session-001", compiled_graph=graph
            )

        assert metadata is not None
        assert metadata["message_count"] >= 2

    @pytest.mark.asyncio
    async def test_aimessage_is_persisted_in_messages_channel(
        self, tmp_path: Any
    ) -> None:
        db_path = str(tmp_path / "test_aimessage.db")
        store = _DeterministicVectorStore(retrieval_hits=(_retrieval_hit(),))

        async with create_graph(
            db_path,
            _provider_factory_for_retrieval(answer="Test answer from retrieval."),
            embedder=_EMBEDDER,
            vector_store=store,
        ) as graph:
            await run_rag_graph(
                query="test question",
                session_id="aimessage-test-session",
                compiled_graph=graph,
            )

        async with create_graph(
            db_path,
            embedder=_EMBEDDER,
            vector_store=store,
        ) as graph:
            checkpointer = getattr(graph, "checkpointer", None)
            assert checkpointer is not None
            checkpoint = await checkpointer.aget_tuple(
                {"configurable": {"thread_id": "aimessage-test-session"}}
            )

        assert checkpoint is not None
        messages = checkpoint.checkpoint["channel_values"]["messages"]
        assert [message.type for message in messages] == ["human", "ai"]
        assert messages[1].content == "Test answer from retrieval."
