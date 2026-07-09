"""Unit tests for LangGraph node functions (FR-003).

Tests each of the 7 nodes:
- analyzer_node: intent classification
- cache_check_node: semantic cache lookup
- retrieve_node: hybrid search + rerank
- generate_from_cache_node: cached answer return
- generate_from_retrieval_node: LLM generation with citations
- validate_node: faithfulness scoring
- save_to_cache_node: cache persistence

ACs covered: AC-003.1 through AC-003.6
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import HumanMessage

from src.graph.nodes import (
    GROUNDING_INSTRUCTION,
    analyzer_node,
    cache_check_node,
    generate_from_cache_node,
    generate_from_retrieval_node,
    retrieve_node,
    save_to_cache_node,
    validate_node,
)
from src.graph.state import RAGState

# ============================================================
# Helpers
# ============================================================


def _make_sparse_vector(indices: list[int], values: list[float]) -> SimpleNamespace:
    """Create a mock sparse vector with .indices and .values attributes."""
    return SimpleNamespace(indices=indices, values=values)


def _make_state(**overrides: object) -> RAGState:
    """Create a minimal RAGState dict with defaults, allowing overrides."""
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
    defaults.update(overrides)  # type: ignore[arg-type]
    return defaults


# ============================================================
# AC-003.1: Analyzer Node — Intent Classification
# ============================================================


class TestAnalyzerNode:
    """Tests for analyzer_node: intent classification (AC-003.1)."""

    @pytest.mark.asyncio
    async def test_standalone_question_classification(self) -> None:
        """AC-003.1: Self-contained message → 'standalone_question'."""
        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "standalone"
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)

        with patch("src.graph.nodes.ChatOpenAI", return_value=mock_llm):
            state = _make_state(
                messages=[HumanMessage(content="What is machine learning?")],
                query="What is machine learning?",
            )
            result = await analyzer_node(state)

        assert result["intent"] == "standalone_question"
        assert result["query"] == "What is machine learning?"

    @pytest.mark.asyncio
    async def test_follow_up_question_classification(self) -> None:
        """AC-003.1: Context-referencing message → 'follow_up_question'."""
        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "follow_up"
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)

        with patch("src.graph.nodes.ChatOpenAI", return_value=mock_llm):
            state = _make_state(
                messages=[
                    HumanMessage(content="What is machine learning?"),
                    HumanMessage(content="Tell me more about supervised learning"),
                ],
            )
            result = await analyzer_node(state)

        assert result["intent"] == "follow_up_question"

    @pytest.mark.asyncio
    async def test_query_extracted_from_last_human_message(self) -> None:
        """Query is extracted from the most recent HumanMessage."""
        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "standalone"
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)

        with patch("src.graph.nodes.ChatOpenAI", return_value=mock_llm):
            state = _make_state(
                messages=[
                    HumanMessage(content="First question"),
                    HumanMessage(content="Second question"),
                ],
            )
            result = await analyzer_node(state)

        assert result["query"] == "Second question"


# ============================================================
# AC-003.2: Cache Check Node — Semantic Cache Lookup
# ============================================================


class TestCacheCheckNode:
    """Tests for cache_check_node: semantic cache lookup (AC-003.2)."""

    @pytest.mark.asyncio
    async def test_cache_hit_returns_cached_answer(self) -> None:
        """AC-003.2: Cache hit → cache_hit=True, cached_answer is set."""
        mock_client = AsyncMock()
        mock_client.collection_exists = AsyncMock(return_value=True)

        mock_point = MagicMock()
        mock_point.score = 0.95
        mock_point.payload = {
            "query": "What is ML?",
            "answer": "ML is a subset of AI...",
            "timestamp": "2025-01-01T00:00:00Z",
            "session_id": "test-session",
        }
        mock_results = MagicMock()
        mock_results.points = [mock_point]
        mock_client.query_points = AsyncMock(return_value=mock_results)

        with patch(
            "src.graph.nodes.get_qdrant_client", AsyncMock(return_value=mock_client)
        ):
            with patch(
                "src.graph.nodes.generate_dense_embeddings",
                return_value=[[0.1] * 384],
            ):
                state = _make_state(query="What is ML?")
                result = await cache_check_node(state)

        assert result["cache_hit"] is True
        assert result["cached_answer"] == "ML is a subset of AI..."

    @pytest.mark.asyncio
    async def test_cache_miss_returns_false(self) -> None:
        """AC-003.2: No similar query → cache_hit=False."""
        mock_client = AsyncMock()
        mock_client.collection_exists = AsyncMock(return_value=True)

        mock_results = MagicMock()
        mock_results.points = []
        mock_client.query_points = AsyncMock(return_value=mock_results)

        with patch(
            "src.graph.nodes.get_qdrant_client", AsyncMock(return_value=mock_client)
        ):
            with patch(
                "src.graph.nodes.generate_dense_embeddings",
                return_value=[[0.1] * 384],
            ):
                state = _make_state(query="Completely new question?")
                result = await cache_check_node(state)

        assert result["cache_hit"] is False
        assert result["cached_answer"] is None

    @pytest.mark.asyncio
    async def test_cache_check_handles_qdrant_error(self) -> None:
        """Cache check gracefully handles Qdrant errors (treats as miss)."""
        mock_client = AsyncMock()
        mock_client.collection_exists = AsyncMock(return_value=True)
        mock_client.query_points = AsyncMock(side_effect=Exception("Qdrant down"))

        with patch(
            "src.graph.nodes.get_qdrant_client", AsyncMock(return_value=mock_client)
        ):
            with patch(
                "src.graph.nodes.generate_dense_embeddings",
                return_value=[[0.1] * 384],
            ):
                state = _make_state(query="test")
                result = await cache_check_node(state)

        assert result["cache_hit"] is False
        assert result["cached_answer"] is None


# ============================================================
# AC-003.3: Retrieve Node — Hybrid Search + Reranking
# ============================================================


class TestRetrieveNode:
    """Tests for retrieve_node: hybrid search with reranking (AC-003.3)."""

    @pytest.mark.asyncio
    async def test_retrieve_returns_documents(self) -> None:
        """AC-003.3: Retrieve returns list of doc dicts with text/score/metadata."""
        mock_results: list[dict[str, Any]] = [
            {
                "text": "Machine learning is a subset of AI.",
                "score": 0.95,
                "metadata": {"filename": "ai_intro.pdf", "chunk_index": 3},
            },
            {
                "text": "Deep learning uses neural networks.",
                "score": 0.87,
                "metadata": {"filename": "dl_basics.pdf", "chunk_index": 1},
            },
        ]

        with patch(
            "src.graph.nodes.generate_dense_embeddings",
            return_value=[[0.1] * 384],
        ):
            with patch(
                "src.graph.nodes.generate_sparse_embeddings",
                return_value=[_make_sparse_vector([1, 2], [0.5, 0.3])],
            ):
                with patch(
                    "src.graph.nodes.hybrid_search",
                    AsyncMock(return_value=mock_results),
                ):
                    state = _make_state(query="What is machine learning?")
                    result = await retrieve_node(state)

        assert len(result["retrieved_docs"]) == 2
        assert (
            result["retrieved_docs"][0]["text"] == "Machine learning is a subset of AI."
        )
        assert result["retrieved_docs"][0]["score"] == 0.95

    @pytest.mark.asyncio
    async def test_retrieve_empty_on_no_results(self) -> None:
        """AC-002.3 / AC-003.3: Empty results → returns empty list."""
        with patch(
            "src.graph.nodes.generate_dense_embeddings",
            return_value=[[0.1] * 384],
        ):
            with patch(
                "src.graph.nodes.generate_sparse_embeddings",
                return_value=[_make_sparse_vector([1], [0.1])],
            ):
                with patch("src.graph.nodes.hybrid_search", AsyncMock(return_value=[])):
                    state = _make_state(query="xyzzy nonsense query")
                    result = await retrieve_node(state)

        assert result["retrieved_docs"] == []


# ============================================================
# AC-003.2: Generate from Cache Node
# ============================================================


class TestGenerateFromCacheNode:
    """Tests for generate_from_cache_node (AC-003.2)."""

    @pytest.mark.asyncio
    async def test_returns_cached_answer_no_llm(self) -> None:
        """AC-003.2: Returns cached answer, sets generated_from='cache', no LLM call."""
        state = _make_state(
            cached_answer="Cached response about ML.",
        )
        result = await generate_from_cache_node(state)

        assert result["final_answer"] == "Cached response about ML."
        assert result["generated_from"] == "cache"


# ============================================================
# AC-003.5: Generate from Retrieval Node
# ============================================================


class TestGenerateFromRetrievalNode:
    """Tests for generate_from_retrieval_node (AC-003.5)."""

    @pytest.mark.asyncio
    async def test_generates_grounded_answer_with_citations(self) -> None:
        """AC-003.5: Generates answer grounded in retrieved docs, sets generated_from='retrieval'."""
        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.content = (
            "Machine learning is a subset of artificial intelligence [1]. "
            "It enables systems to learn from data without explicit programming [2]."
        )
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)

        state = _make_state(
            query="What is machine learning?",
            retrieved_docs=cast(
                "list[dict[str, Any]]",
                [
                    {
                        "text": "Machine learning is a subset of AI focusing on data-driven algorithms.",
                        "score": 0.95,
                        "metadata": {"filename": "ai_intro.pdf", "chunk_index": 3},
                    },
                    {
                        "text": "ML enables systems to learn from data without explicit programming.",
                        "score": 0.87,
                        "metadata": {"filename": "ml_basics.pdf", "chunk_index": 1},
                    },
                ],
            ),
        )

        with patch("src.graph.nodes.ChatOpenAI", return_value=mock_llm):
            result = await generate_from_retrieval_node(state)

        assert result["generated_from"] == "retrieval"
        assert result["final_answer"] is not None
        assert "[1]" in str(result["final_answer"])

    @pytest.mark.asyncio
    async def test_includes_grounding_instruction(self) -> None:
        """AC-006.7: Grounding instruction is always first SystemMessage."""
        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "Grounded answer."
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)

        state = _make_state(
            query="Test?",
            retrieved_docs=cast(
                "list[dict[str, Any]]",
                [
                    {
                        "text": "Test content.",
                        "score": 0.9,
                        "metadata": {"filename": "test.pdf", "chunk_index": 0},
                    },
                ],
            ),
        )

        with patch("src.graph.nodes.ChatOpenAI", return_value=mock_llm):
            await generate_from_retrieval_node(state)

        # Check that the grounding instruction was included in the call
        call_args = mock_llm.ainvoke.call_args
        assert call_args is not None
        messages_obj: object = call_args[0][0] if call_args[0] else []
        messages_list: list[object] = (
            cast("list[object]", messages_obj) if isinstance(messages_obj, list) else []
        )
        first_msg: object | None = messages_list[0] if messages_list else None
        assert first_msg is not None
        assert GROUNDING_INSTRUCTION in str(first_msg)


# ============================================================
# Validate Node (Faithfulness Scoring)
# ============================================================


class TestValidateNode:
    """Tests for validate_node: faithfulness scoring (AC-003.3 validation step)."""

    @pytest.mark.asyncio
    async def test_cache_source_skips_validation(self) -> None:
        """Cache-generated answers skip validation → score=1.0, passed=True."""
        state = _make_state(
            generated_from="cache",
            final_answer="Cached answer.",
        )
        result = await validate_node(state)

        assert result["faithfulness_score"] == 1.0
        assert result["validation_passed"] is True

    @pytest.mark.asyncio
    async def test_no_docs_returns_zero_score(self) -> None:
        """No retrieved docs → score=0.0, not passed."""
        state = _make_state(
            generated_from="retrieval",
            retrieved_docs=[],
            final_answer="Some answer.",
        )
        result = await validate_node(state)

        assert result["faithfulness_score"] == 0.0
        assert result["validation_passed"] is False

    @pytest.mark.asyncio
    async def test_retrieval_source_scores_faithfulness(self) -> None:
        """Retrieval-generated answer is scored by LLM-as-judge."""
        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "0.85"
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)

        state = _make_state(
            generated_from="retrieval",
            final_answer="Grounded answer about ML.",
            retrieved_docs=cast(
                "list[dict[str, Any]]",
                [
                    {
                        "text": "ML is a field of AI.",
                        "score": 0.9,
                        "metadata": {"filename": "test.pdf", "chunk_index": 0},
                    },
                ],
            ),
        )

        with patch("src.graph.nodes.ChatOpenAI", return_value=mock_llm):
            result = await validate_node(state)

        assert result["faithfulness_score"] == 0.85
        assert result["validation_passed"] is True  # 0.85 > 0.7

    @pytest.mark.asyncio
    async def test_low_score_fails_validation(self) -> None:
        """Score below threshold → validation_passed=False."""
        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "0.3"
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)

        state = _make_state(
            generated_from="retrieval",
            final_answer="Hallucinated answer.",
            retrieved_docs=cast(
                "list[dict[str, Any]]",
                [
                    {
                        "text": "Unrelated content.",
                        "score": 0.5,
                        "metadata": {"filename": "test.pdf", "chunk_index": 0},
                    },
                ],
            ),
        )

        with patch("src.graph.nodes.ChatOpenAI", return_value=mock_llm):
            result = await validate_node(state)

        assert result["faithfulness_score"] == 0.3
        assert result["validation_passed"] is False  # 0.3 <= 0.7


# ============================================================
# Save to Cache Node
# ============================================================


class TestSaveToCacheNode:
    """Tests for save_to_cache_node (AC-003.3 save step)."""

    @pytest.mark.asyncio
    async def test_skips_on_cache_source(self) -> None:
        """Does NOT save when answer came from cache (already cached)."""
        state = _make_state(
            generated_from="cache",
            final_answer="Already cached answer.",
            validation_passed=True,
        )
        result = await save_to_cache_node(state)
        assert result == {}

    @pytest.mark.asyncio
    async def test_skips_on_validation_fail(self) -> None:
        """Does NOT save when validation failed (don't cache hallucinations)."""
        state = _make_state(
            generated_from="retrieval",
            final_answer="Potentially hallucinated answer.",
            validation_passed=False,
        )
        result = await save_to_cache_node(state)
        assert result == {}

    @pytest.mark.asyncio
    async def test_saves_on_retrieval_with_validation_pass(self) -> None:
        """Saves to cache when retrieval-generated AND validation passed."""
        mock_client = AsyncMock()
        mock_client.collection_exists = AsyncMock(return_value=True)
        mock_client.upsert = AsyncMock()

        with patch(
            "src.graph.nodes.get_qdrant_client", AsyncMock(return_value=mock_client)
        ):
            with patch(
                "src.graph.nodes.generate_dense_embeddings",
                return_value=[[0.1] * 384],
            ):
                state = _make_state(
                    query="What is ML?",
                    generated_from="retrieval",
                    final_answer="ML is machine learning.",
                    validation_passed=True,
                )
                result = await save_to_cache_node(state)

        # Should have called upsert
        mock_client.upsert.assert_called_once()
        assert result == {}
