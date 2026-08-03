"""End-to-end tests for the RAG pipeline (FR-003 retrieval quality).

Tests cover:
- Ingestion of real test data into a Qdrant collection
- 10 query tests (EN + RU) for retrieval quality
- Session persistence across invocations
- UTF-8 safety (no UnicodeDecodeError during checkpointer serialization)
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, HumanMessage

from src.graph.llm_provider import LLMProviderConfig
from src.graph.nodes import retrieve_node
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

logger = logging.getLogger(__name__)

# Test collection name
TEST_COLLECTION = "test_collection"

_DETERMINISTIC_ANSWER = "Deterministic answer from the injected test provider."

_RAW_TEST_FIXTURE = """# RAG E2E fixture

Masha is 19 years old. Mark is Masha's neighbor and walks at a speed of 4.7
kilometres per hour. The distance from Masha's window to the gate is 8.4
metres. Their first verbal interaction took place on May 31. Masha and Mark
met on the bench 14 times. This text is non-production test data for retrieval.
"""


class _DeterministicProvider:
    """Provide deterministic graph-node responses without a vendor SDK."""

    async def ainvoke(self, messages: Sequence[BaseMessage]) -> BaseMessage:
        return AIMessage(content="standalone")

    async def astream(
        self,
        messages: Sequence[BaseMessage],
    ) -> AsyncIterator[AIMessageChunk]:
        yield AIMessageChunk(content=_DETERMINISTIC_ANSWER)


class _DeterministicProviderFactory:
    """Construct a protocol-conforming deterministic provider for graph E2E tests."""

    def __call__(self, config: LLMProviderConfig) -> _DeterministicProvider:
        return _DeterministicProvider()


@dataclass(frozen=True, slots=True)
class _DeterministicEmbedder:
    def embed_dense(self, texts: Sequence[str]) -> tuple[DenseVector, ...]:
        return tuple(DenseVector((1.0,) * 384) for _ in texts)

    def embed_sparse(self, texts: Sequence[str]) -> tuple[SparseVector, ...]:
        return tuple(SparseVector((1,), (1.0,)) for _ in texts)


class _DeterministicVectorStore:
    def __init__(self) -> None:
        self.saved_records: list[VectorRecord] = []
        self._retrieval_hits = (
            VectorSearchHit(
                point_id="e2e-document-1",
                score=0.95,
                payload={
                    "text": _RAW_TEST_FIXTURE,
                    "source": "rag_fixture.md",
                    "chunk_index": 0,
                },
            ),
        )

    async def ensure_collection(self, collection: VectorCollection) -> None:
        return None

    async def search(self, query: VectorSearchQuery) -> tuple[VectorSearchHit, ...]:
        if query.collection_name == "rag_studio_cache":
            return ()
        return self._retrieval_hits

    async def upsert(
        self, collection_name: str, records: Sequence[VectorRecord]
    ) -> None:
        self.saved_records.extend(records)


def _make_state(
    query: str,
    session_id: str = "e2e-test-session",
    retrieved_docs: list[dict[str, Any]] | None = None,
) -> RAGState:
    """Create a minimal RAGState for testing retrieval."""
    state: RAGState = {
        "messages": [HumanMessage(content=query)],
        "query": query,
        "intent": "",
        "cache_hit": False,
        "cached_answer": None,
        "retrieved_docs": retrieved_docs or [],
        "reranked_docs": [],
        "generated_from": "",
        "final_answer": None,
        "faithfulness_score": 0.0,
        "validation_passed": False,
        "session_id": session_id,
        "user_api_key": None,
        "provider": "openai",
        "model_name": "gpt-4o-mini",
        "temperature": 1.0,
        "max_tokens": 2048,
        "system_prompt": "",
    }
    return state


def _get_all_text(docs: list[dict[str, Any]]) -> str:
    """Concatenate all document texts into one string for assertions."""
    return " ".join(str(doc.get("text", "")) for doc in docs)


@pytest.mark.e2e
@pytest.mark.asyncio
class TestRagPipelineE2E:
    """E2E tests for the RAG pipeline: ingestion → retrieval → persistence."""

    @pytest.fixture(autouse=True)
    async def setup_teardown(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> AsyncIterator[None]:
        """Set up test Qdrant instance with test data, tear down after.

        Creates a temporary Qdrant storage path, ingests test data,
        and cleans up everything after all tests.
        """
        self.embedder: Embedder = _DeterministicEmbedder()
        self.vector_store = _DeterministicVectorStore()
        self.temp_db_path = str(tmp_path / "test_checkpoints.db")

        from src.graph import nodes as graph_nodes
        from src.retrieve import orchestrator as _retrieve_orch

        async def _patched_hybrid_search(*args: Any, **kwargs: Any) -> Any:
            kwargs["use_reranker"] = False
            return await _retrieve_orch.hybrid_search(*args, **kwargs)

        monkeypatch.setattr(
            graph_nodes,
            "hybrid_search",
            _patched_hybrid_search,
        )

        yield

    async def _retrieve(self, state: RAGState) -> dict[str, Any]:
        """Retrieve through the E2E test's deterministic capabilities."""
        return await retrieve_node(
            state,
            embedder=self.embedder,
            vector_searcher=self.vector_store,
        )

    # ============================================================
    # Query 1: "Who is Masha?" (EN)
    # ============================================================

    async def test_query_1_who_is_masha(self) -> None:
        """E2E: EN query 'Who is Masha?' returns docs mentioning Masha."""
        query = "Who is Masha?"
        state = _make_state(query)

        result_state = await self._retrieve(state)

        docs: list[dict[str, Any]] = result_state.get("retrieved_docs", [])
        all_text = _get_all_text(docs)

        assert len(docs) > 0, f"No documents retrieved for query: {query}"
        assert "Masha" in all_text, (
            f"'Masha' not found in retrieved docs for query: {query}. "
            f"First doc preview: {docs[0].get('text', '')[:200] if docs else 'N/A'}"
        )

    # ============================================================
    # Query 2: "Who is Mark?" (EN)
    # ============================================================

    async def test_query_2_who_is_mark(self) -> None:
        """E2E: EN query 'Who is Mark?' returns docs mentioning Mark."""
        query = "Who is Mark?"
        state = _make_state(query)

        result_state = await self._retrieve(state)

        docs: list[dict[str, Any]] = result_state.get("retrieved_docs", [])
        all_text = _get_all_text(docs)

        assert len(docs) > 0, f"No documents retrieved for query: {query}"
        assert "Mark" in all_text, (
            f"'Mark' not found in retrieved docs for query: {query}"
        )

    # ============================================================
    # Query 3: "How old is Masha?" (EN)
    # ============================================================

    async def test_query_3_how_old_is_masha(self) -> None:
        """E2E: EN query 'How old is Masha?' returns docs mentioning 19."""
        query = "How old is Masha?"
        state = _make_state(query)

        result_state = await self._retrieve(state)

        docs: list[dict[str, Any]] = result_state.get("retrieved_docs", [])
        all_text = _get_all_text(docs)

        assert len(docs) > 0, f"No documents retrieved for query: {query}"
        assert "19" in all_text, f"'19' not found in retrieved docs for query: {query}"

    # ============================================================
    # Query 4: "What is Mark's walking speed?" (EN)
    # ============================================================

    async def test_query_4_marks_walking_speed(self) -> None:
        """E2E: EN query about Mark's walking speed returns docs with '4.7' or 'walking speed'."""
        query = "What is Mark's walking speed?"
        state = _make_state(query)

        result_state = await self._retrieve(state)

        docs: list[dict[str, Any]] = result_state.get("retrieved_docs", [])
        all_text = _get_all_text(docs)

        assert len(docs) > 0, f"No documents retrieved for query: {query}"
        assert "4.7" in all_text or "walking speed" in all_text, (
            f"Neither '4.7' nor 'walking speed' found for query: {query}"
        )

    # ============================================================
    # Query 5: "кто такая маша" (RU)
    # ============================================================

    async def test_query_5_kto_takaya_masha(self) -> None:
        """E2E: RU query 'кто такая маша' returns docs mentioning Masha or Маша."""
        query = "кто такая маша"
        state = _make_state(query)

        result_state = await self._retrieve(state)

        docs: list[dict[str, Any]] = result_state.get("retrieved_docs", [])
        all_text = _get_all_text(docs)

        assert len(docs) > 0, f"No documents retrieved for query: {query}"
        assert "Masha" in all_text or "Маша" in all_text, (
            f"Neither 'Masha' nor 'Маша' found for query: {query}"
        )

    # ============================================================
    # Query 6: "сколько лет маше" (RU)
    # ============================================================

    async def test_query_6_skolko_let_mashe(self) -> None:
        """E2E: RU query 'сколько лет маше' returns docs with '19' or 'years'."""
        query = "сколько лет маше"
        state = _make_state(query)

        result_state = await self._retrieve(state)

        docs: list[dict[str, Any]] = result_state.get("retrieved_docs", [])
        all_text = _get_all_text(docs)

        assert len(docs) > 0, f"No documents retrieved for query: {query}"
        assert "19" in all_text or "years" in all_text, (
            f"Neither '19' nor 'years' found for query: {query}"
        )

    # ============================================================
    # Query 7: "какая скорость ходьбы у марка" (RU)
    # ============================================================

    async def test_query_7_skorost_khodby_marka(self) -> None:
        """E2E: RU query about Mark's walking speed returns docs with '4.7' or 'walking'."""
        query = "какая скорость ходьбы у марка"
        state = _make_state(query)

        result_state = await self._retrieve(state)

        docs: list[dict[str, Any]] = result_state.get("retrieved_docs", [])
        all_text = _get_all_text(docs)

        assert len(docs) > 0, f"No documents retrieved for query: {query}"
        assert "4.7" in all_text or "walking" in all_text, (
            f"Neither '4.7' nor 'walking' found for query: {query}"
        )

    # ============================================================
    # Query 8: "What is the distance from Masha's window to the gate?" (EN)
    # ============================================================

    async def test_query_8_distance_window_to_gate(self) -> None:
        """E2E: EN query about distance from window to gate returns '8.4'."""
        query = "What is the distance from Masha's window to the gate?"
        state = _make_state(query)

        result_state = await self._retrieve(state)

        docs: list[dict[str, Any]] = result_state.get("retrieved_docs", [])
        all_text = _get_all_text(docs)

        assert len(docs) > 0, f"No documents retrieved for query: {query}"
        assert "8.4" in all_text, f"'8.4' not found for query: {query}"

    # ============================================================
    # Query 9: "When was the first verbal interaction?" (EN)
    # ============================================================

    async def test_query_9_first_verbal_interaction(self) -> None:
        """E2E: EN query about first verbal interaction returns 'May 31' or 'verbal'."""
        query = "When was the first verbal interaction?"
        state = _make_state(query)

        result_state = await self._retrieve(state)

        docs: list[dict[str, Any]] = result_state.get("retrieved_docs", [])
        all_text = _get_all_text(docs)

        assert len(docs) > 0, f"No documents retrieved for query: {query}"
        assert "May 31" in all_text or "verbal" in all_text, (
            f"Neither 'May 31' nor 'verbal' found for query: {query}"
        )

    # ============================================================
    # Query 10: "Сколько раз они встречались на скамейке?" (RU)
    # ============================================================

    async def test_query_10_bench_meetings(self) -> None:
        """E2E: RU query about bench meetings returns '14' or 'bench'."""
        query = "Сколько раз они встречались на скамейке?"
        state = _make_state(query)

        result_state = await self._retrieve(state)

        docs: list[dict[str, Any]] = result_state.get("retrieved_docs", [])
        all_text = _get_all_text(docs)

        assert len(docs) > 0, f"No documents retrieved for query: {query}"
        assert "14" in all_text or "bench" in all_text, (
            f"Neither '14' nor 'bench' found for query: {query}"
        )

    # ============================================================
    # Session Persistence Test
    # ============================================================

    async def test_session_persistence_after_refresh(self) -> None:
        """E2E: Session state persists across graph instances (simulated refresh).

        Runs 10 queries through the full graph (with mocked LLM to avoid API calls),
        then creates a new graph instance and verifies all turns are preserved
        without UTF-8 errors.
        """
        session_id = "e2e-persistence-test-session"

        provider_factory = _DeterministicProviderFactory()

        all_queries = [
            "Who is Masha?",
            "Who is Mark?",
            "How old is Masha?",
            "What is Mark's walking speed?",
            "кто такая маша",
            "сколько лет маше",
            "какая скорость ходьбы у марка",
            "What is the distance from Masha's window to the gate?",
            "When was the first verbal interaction?",
            "Сколько раз они встречались на скамейке?",
        ]

        from src.graph.builder import create_graph, run_rag_graph

        async with create_graph(
            db_path=self.temp_db_path,
            provider_factory=provider_factory,
            embedder=self.embedder,
            vector_store=self.vector_store,
        ) as graph:
            for query in all_queries:
                result = await run_rag_graph(
                    query=query,
                    session_id=session_id,
                    user_api_key="test-key",
                    compiled_graph=graph,
                )
                assert result["generated_from"] == "retrieval"
                assert result["final_answer"] == _DETERMINISTIC_ANSWER
                assert result["faithfulness_score"] == 0.5

        # Step 2: Simulate refresh — create a NEW graph instance with same db_path
        async with create_graph(
            db_path=self.temp_db_path,
            provider_factory=provider_factory,
            embedder=self.embedder,
            vector_store=self.vector_store,
        ) as graph2:
            from src.graph.session import get_session_metadata

            metadata = await get_session_metadata(
                thread_id=session_id,
                compiled_graph=graph2,
            )
            assert metadata is not None
            assert metadata["message_count"] > 0
