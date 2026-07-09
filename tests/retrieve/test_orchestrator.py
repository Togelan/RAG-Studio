"""Unit tests for FR-002: Hybrid Search with RRF and Reranker.

Covers all 3 Acceptance Criteria:
- AC-002.1: Hybrid Search with RRF Fusion
- AC-002.2: Cross-Encoder Reranking
- AC-002.3: Empty Result Handling
"""

from __future__ import annotations

from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.retrieve.orchestrator import (
    _FINAL_TOP_K,  # pyright: ignore[reportPrivateUsage]
    get_reranker_status,
    hybrid_search,
    reset_reranker,
)

# ============================================================
# Helpers
# ============================================================


def _make_mock_qdrant_point(point_id: str, text: str, score: float = 0.8) -> MagicMock:
    """Create a mock Qdrant ScoredPoint with payload."""
    point = MagicMock()
    point.id = point_id
    point.score = score
    point.payload = {
        "text": text,
        "filename": "test.pdf",
        "chunk_index": 1,
        "doc_id": "doc-123",
    }
    return point


def _make_mock_query_points(points: list[MagicMock]) -> MagicMock:
    """Create a mock QueryPoints response."""
    resp = MagicMock()
    resp.points = points
    return resp


def _setup_mock_qdrant_client(points: list[MagicMock] | None = None):
    """Create a mock AsyncQdrantClient with query_points returning given points."""
    if points is None:
        points = [
            _make_mock_qdrant_point("p1", "Relevant chunk about AI.", 0.9),
            _make_mock_qdrant_point("p2", "Another AI-related passage.", 0.7),
            _make_mock_qdrant_point("p3", "Weather forecast data.", 0.3),
        ]

    mock_client = AsyncMock()
    mock_client.query_points = AsyncMock(return_value=_make_mock_query_points(points))
    return mock_client


def _setup_mock_ranker(
    scores: list[float] | None = None,
) -> MagicMock:
    """Create a mock FlashRank Ranker that returns passages with given scores.

    The mock reranker passes through the original passages with the
    provided scores assigned in order.
    """
    if scores is None:
        scores = [0.95, 0.72, 0.08]

    mock_ranker = MagicMock()

    def _fake_rerank(request: object) -> list[dict[str, object]]:
        """Simulate FlashRank rerank: assign scores, sort descending."""
        passages: list[dict[str, object]] = getattr(request, "passages", [])
        for i, passage in enumerate(passages):
            if i < len(scores):
                passage["score"] = scores[i]
            else:
                passage["score"] = 0.0
        # Sort descending by score
        passages.sort(key=lambda x: cast("float", x["score"]), reverse=True)
        return passages

    mock_ranker.rerank = MagicMock(side_effect=_fake_rerank)
    return mock_ranker


# ============================================================
# Fixtures
# ============================================================


@pytest.fixture(autouse=True)
def _reset_reranker_state() -> None:  # pyright: ignore[reportUnusedFunction]
    """Reset reranker global state before each test."""
    reset_reranker()


# ============================================================
# AC-002.1: Hybrid Search with RRF Fusion
# ============================================================


class TestAC0021RRFFusion:
    """AC-002.1: Verify hybrid search uses RRF fusion with proper prefetch."""

    @pytest.mark.asyncio
    async def test_rrf_fusion_is_used(self) -> None:
        """Hybrid search calls query_points with RRF FusionQuery."""
        mock_points = [
            _make_mock_qdrant_point("p1", "AI chunk one.", 0.9),
            _make_mock_qdrant_point("p2", "AI chunk two.", 0.7),
        ]
        mock_client = _setup_mock_qdrant_client(mock_points)

        with patch(
            "src.vector_store.client.get_qdrant_client",
            return_value=mock_client,
        ):
            results = await hybrid_search(
                query="test query",
                dense_vector=[0.1] * 384,
                sparse_indices=[1, 2, 3],
                sparse_values=[0.5, 0.3, 0.1],
                use_reranker=False,
            )

        # Verify query_points was called
        mock_client.query_points.assert_awaited_once()
        call_kwargs = mock_client.query_points.call_args.kwargs

        # Check FusionQuery with RRF
        assert call_kwargs["query"] is not None
        from qdrant_client.http.models import FusionQuery

        assert isinstance(call_kwargs["query"], FusionQuery)

        # Check prefetch: two prefetch groups (dense + sparse)
        prefetch = call_kwargs["prefetch"]
        assert len(prefetch) == 2
        assert prefetch[0].using == "dense"
        assert prefetch[1].using == "sparse"

        # Check limit: default top_k=20
        assert call_kwargs["limit"] == 20

        # With reranker disabled, returns top 5 RRF-only
        assert 0 < len(results) <= _FINAL_TOP_K

    @pytest.mark.asyncio
    async def test_prefetch_oversamples_candidates(self) -> None:
        """Prefetch limits are top_k * 3 for each vector type."""
        mock_points = [
            _make_mock_qdrant_point(f"p{i}", f"Chunk {i}", 0.5) for i in range(40)
        ]
        mock_client = _setup_mock_qdrant_client(mock_points)

        with patch(
            "src.vector_store.client.get_qdrant_client",
            return_value=mock_client,
        ):
            await hybrid_search(
                query="test",
                dense_vector=[0.1] * 384,
                sparse_indices=[1],
                sparse_values=[0.5],
                top_k=15,
                use_reranker=False,
            )

        call_kwargs = mock_client.query_points.call_args.kwargs
        prefetch = call_kwargs["prefetch"]
        # top_k=15 → oversample limit = 45 (3x)
        assert prefetch[0].limit == 45
        assert prefetch[1].limit == 45
        assert call_kwargs["limit"] == 15


# ============================================================
# AC-002.2: Cross-Encoder Reranking
# ============================================================


class TestAC0022Reranking:
    """AC-002.2: Verify cross-encoder reranking reduces to top 5."""

    @pytest.mark.asyncio
    async def test_reranker_produces_top_5(self) -> None:
        """With 20 candidates, reranker returns exactly 5 results."""
        mock_points = [
            _make_mock_qdrant_point(f"p{i}", f"Chunk number {i}", 0.5)
            for i in range(20)
        ]
        mock_client = _setup_mock_qdrant_client(mock_points)

        # Mock reranker with descending scores
        mock_ranker = _setup_mock_ranker(
            scores=[0.9, 0.85, 0.8, 0.75, 0.7, 0.1, 0.1, 0.1, 0.1, 0.1] + [0.05] * 10
        )

        with (
            patch(
                "src.vector_store.client.get_qdrant_client",
                return_value=mock_client,
            ),
            patch(
                "src.retrieve.orchestrator._get_reranker",
                return_value=mock_ranker,
            ),
        ):
            results = await hybrid_search(
                query="relevant query",
                dense_vector=[0.1] * 384,
                sparse_indices=[1],
                sparse_values=[0.5],
                use_reranker=True,
            )

        assert len(results) == _FINAL_TOP_K
        # All should have rerank_score
        for r in results:
            assert "rerank_score" in r

    @pytest.mark.asyncio
    async def test_results_sorted_by_rerank_score(self) -> None:
        """Results are sorted in descending rerank_score order."""
        mock_points = [
            _make_mock_qdrant_point(f"p{i}", f"Chunk {i}", 0.5) for i in range(5)
        ]
        mock_client = _setup_mock_qdrant_client(mock_points)

        mock_ranker = _setup_mock_ranker(scores=[0.3, 0.99, 0.55, 0.1, 0.72])

        with (
            patch(
                "src.vector_store.client.get_qdrant_client",
                return_value=mock_client,
            ),
            patch(
                "src.retrieve.orchestrator._get_reranker",
                return_value=mock_ranker,
            ),
        ):
            results = await hybrid_search(
                query="test",
                dense_vector=[0.1] * 384,
                sparse_indices=[1],
                sparse_values=[0.5],
                use_reranker=True,
            )

        # Verify descending order
        scores = [r["rerank_score"] for r in results]
        assert scores == sorted(scores, reverse=True)
        # Best score should be 0.99
        assert scores[0] == 0.99

    @pytest.mark.asyncio
    async def test_result_includes_metadata(self) -> None:
        """Each result includes text, score, and metadata fields."""
        mock_points = [
            _make_mock_qdrant_point("p1", "Important document text.", 0.6),
        ]
        mock_client = _setup_mock_qdrant_client(mock_points)
        mock_ranker = _setup_mock_ranker(scores=[0.88])

        with (
            patch(
                "src.vector_store.client.get_qdrant_client",
                return_value=mock_client,
            ),
            patch(
                "src.retrieve.orchestrator._get_reranker",
                return_value=mock_ranker,
            ),
        ):
            results = await hybrid_search(
                query="test",
                dense_vector=[0.1] * 384,
                sparse_indices=[1],
                sparse_values=[0.5],
                use_reranker=True,
            )

        assert len(results) == 1
        r = results[0]
        assert "text" in r
        assert "score" in r
        assert "metadata" in r
        assert r["text"] == "Important document text."
        assert "filename" in r["metadata"]
        assert "chunk_index" in r["metadata"]

    @pytest.mark.asyncio
    async def test_reranker_disabled_returns_rrf_only(self) -> None:
        """When use_reranker=False, returns RRF-only top 5."""
        mock_points = [
            _make_mock_qdrant_point(f"p{i}", f"Chunk {i}", 0.8 - i * 0.03)
            for i in range(10)
        ]
        mock_client = _setup_mock_qdrant_client(mock_points)

        with patch(
            "src.vector_store.client.get_qdrant_client",
            return_value=mock_client,
        ):
            results = await hybrid_search(
                query="test",
                dense_vector=[0.1] * 384,
                sparse_indices=[1],
                sparse_values=[0.5],
                use_reranker=False,
            )

        assert len(results) == _FINAL_TOP_K
        # No rerank_score when reranker not used
        for r in results:
            assert "rerank_score" not in r


# ============================================================
# AC-002.3: Empty Result Handling
# ============================================================


class TestAC0023EmptyResults:
    """AC-002.3: Verify graceful empty result handling."""

    @pytest.mark.asyncio
    async def test_no_points_returns_empty_list(self) -> None:
        """When Qdrant returns no points, hybrid_search returns []."""
        mock_client = _setup_mock_qdrant_client([])

        with patch(
            "src.vector_store.client.get_qdrant_client",
            return_value=mock_client,
        ):
            results = await hybrid_search(
                query="xyzzy nonsense query",
                dense_vector=[0.1] * 384,
                sparse_indices=[1],
                sparse_values=[0.5],
                use_reranker=True,
            )

        assert results == []

    @pytest.mark.asyncio
    async def test_threshold_at_zero_passes_low_scores(self) -> None:
        """With threshold=0.0, even very low sigmoid scores pass through.

        FlashRank outputs sigmoid probabilities in [0,1]. Since 0.0 is the
        mathematical minimum, the threshold is effectively disabled — only
        truly broken/NaN scores would be filtered. This is intentional for
        multilingual support where cross-encoder confidence may be lower.
        """
        mock_points = [
            _make_mock_qdrant_point(f"p{i}", f"Low-confidence chunk {i}", 0.3)
            for i in range(5)
        ]
        mock_client = _setup_mock_qdrant_client(mock_points)

        # Very low but valid sigmoid scores — all pass threshold=0.0
        mock_ranker = _setup_mock_ranker(scores=[0.002, 0.001, 0.0005, 0.0001, 0.0])

        with (
            patch(
                "src.vector_store.client.get_qdrant_client",
                return_value=mock_client,
            ),
            patch(
                "src.retrieve.orchestrator._get_reranker",
                return_value=mock_ranker,
            ),
        ):
            results = await hybrid_search(
                query="low confidence multilingual query",
                dense_vector=[0.1] * 384,
                sparse_indices=[1],
                sparse_values=[0.5],
                use_reranker=True,
            )

        # All scores are >= 0.0 (sigmoid minimum), so no filtering occurs
        assert len(results) > 0
        assert len(results) <= _FINAL_TOP_K

    @pytest.mark.asyncio
    async def test_mixed_scores_passes_threshold(self) -> None:
        """When at least one reranker score >= 0.1, results are returned."""
        mock_points = [
            _make_mock_qdrant_point(f"p{i}", f"Mixed chunk {i}", 0.3) for i in range(5)
        ]
        mock_client = _setup_mock_qdrant_client(mock_points)

        # One good score, rest low
        mock_ranker = _setup_mock_ranker(scores=[0.85, 0.05, 0.03, 0.01, 0.02])

        with (
            patch(
                "src.vector_store.client.get_qdrant_client",
                return_value=mock_client,
            ),
            patch(
                "src.retrieve.orchestrator._get_reranker",
                return_value=mock_ranker,
            ),
        ):
            results = await hybrid_search(
                query="partially relevant query",
                dense_vector=[0.1] * 384,
                sparse_indices=[1],
                sparse_values=[0.5],
                use_reranker=True,
            )

        # Should return results because one score passes threshold
        assert len(results) > 0
        assert len(results) <= _FINAL_TOP_K

    @pytest.mark.asyncio
    async def test_qdrant_error_returns_empty_list(self) -> None:
        """When Qdrant search raises, hybrid_search returns [] gracefully."""
        mock_client = AsyncMock()
        mock_client.query_points = AsyncMock(
            side_effect=Exception("Qdrant connection error")
        )

        with patch(
            "src.vector_store.client.get_qdrant_client",
            return_value=mock_client,
        ):
            results = await hybrid_search(
                query="test query",
                dense_vector=[0.1] * 384,
                sparse_indices=[1],
                sparse_values=[0.5],
                use_reranker=True,
            )

        assert results == []


# ============================================================
# Reranker lifecycle tests
# ============================================================


class TestRerankerLifecycle:
    """Tests for reranker lazy loading, status, and reset."""

    def test_reset_clears_reranker_state(self) -> None:
        """After reset, reranker state is cleared and needs re-init."""
        reset_reranker()
        # State should be cleared (None = not yet attempted)
        from src.retrieve.orchestrator import (
            _reranker_available as _ravail,  # pyright: ignore[reportPrivateUsage]
        )

        assert _ravail is None

    def test_get_reranker_status_after_load(self) -> None:
        """Status reflects actual availability after lazy load."""
        reset_reranker()
        status = get_reranker_status()
        # After calling get_reranker_status, the reranker has been
        # lazily loaded. It may or may not be available depending on
        # environment, but the 'available' key must be present.
        assert "available" in status
        assert isinstance(status["available"], bool)

    @pytest.mark.asyncio
    async def test_reranker_fallback_when_unavailable(self) -> None:
        """When reranker fails to load, RRF fallback works."""
        mock_points = [
            _make_mock_qdrant_point("p1", "A relevant chunk.", 0.7),
        ]
        mock_client = _setup_mock_qdrant_client(mock_points)

        with (
            patch(
                "src.vector_store.client.get_qdrant_client",
                return_value=mock_client,
            ),
            patch(
                "src.retrieve.orchestrator._get_reranker",
                return_value=None,  # reranker unavailable
            ),
        ):
            results = await hybrid_search(
                query="test",
                dense_vector=[0.1] * 384,
                sparse_indices=[1],
                sparse_values=[0.5],
                use_reranker=True,
            )

        # Falls back to RRF-only top 5
        assert len(results) <= _FINAL_TOP_K
        for r in results:
            assert "rerank_score" not in r
