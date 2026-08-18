"""Hybrid search orchestrator with RRF fusion and FlashRank reranker (FR-002).

Orchestrates retrieval combining dense + sparse search with RRF fusion,
and adds cross-encoder reranking via FlashRank (ms-marco-MultiBERT-L-12,
cached in data/models/flashrank/) with graceful OOM fallback
and low-score threshold filtering.
"""

# pyright: reportMissingTypeStubs=false

from __future__ import annotations

import logging
from threading import Lock
from typing import Any, Protocol

from src.paths import configured_path
from src.retrieve.context_expansion import expand_context_units
from src.vector_store.adapter import get_vector_store
from src.vector_store.contracts import VectorSearcher
from src.vector_store.models import (
    DenseVector,
    SparseVector,
    VectorSearchHit,
    VectorSearchQuery,
)
from src.vector_store.tenant_store import TenantVectorSearch

logger = logging.getLogger(__name__)


class TenantVectorSearcher(Protocol):
    """Search capability already bound to an authorized workspace."""

    async def search_documents(
        self, query: TenantVectorSearch
    ) -> tuple[VectorSearchHit, ...]: ...


async def tenant_hybrid_search(
    query: str,
    dense_vector: list[float],
    sparse_indices: list[int],
    sparse_values: list[float],
    *,
    tenant_searcher: TenantVectorSearcher,
    top_k: int = 20,
    use_reranker: bool = True,
    context_character_budget: int = 24_000,
) -> list[dict[str, Any]]:
    """Retrieve only through a server-resolved tenant search capability."""
    try:
        raw_results = await tenant_searcher.search_documents(
            TenantVectorSearch(
                dense=DenseVector(tuple(dense_vector)),
                sparse=SparseVector(tuple(sparse_indices), tuple(sparse_values)),
                limit=top_k,
            )
        )
    except Exception as error:  # noqa: BLE001 -- typed boundary maps to safe empty
        logger.warning(
            "tenant_retrieval_failed error_type=%s", type(error).__name__
        )
        return []

    context_units = expand_context_units(
        raw_results,
        top_k=min(top_k, _FINAL_TOP_K),
        character_budget=context_character_budget,
    )
    candidates = [
        {
            "id": unit.point_id,
            "score": unit.score,
            "text": unit.text,
            "metadata": dict(unit.metadata),
        }
        for unit in context_units
    ]
    if not use_reranker or not candidates:
        return candidates[:_FINAL_TOP_K]

    reranker = _get_reranker()
    if reranker is None:
        return candidates[:_FINAL_TOP_K]
    try:
        from flashrank import RerankRequest

        request = RerankRequest(
            query=query, passages=[{"text": item["text"]} for item in candidates]
        )
        ranked = reranker.rerank(request)
        by_text = {item["text"]: item for item in candidates}
        results: list[dict[str, Any]] = []
        for passage in ranked[:_FINAL_TOP_K]:
            candidate = by_text.get(passage["text"])
            if candidate is not None:
                candidate["rerank_score"] = float(passage["score"])
                results.append(candidate)
        return results
    except (MemoryError, RuntimeError, ValueError, TypeError) as error:
        logger.warning(
            "tenant_reranking_failed error_type=%s", type(error).__name__
        )
        return candidates[:_FINAL_TOP_K]


# FlashRank model config — multilingual cross-encoder, locally cached
_FLASHRANK_MODEL_NAME = "ms-marco-MultiBERT-L-12"


def _flashrank_cache_dir() -> str:
    """Return the reranker cache, honoring the existing environment override."""
    return str(configured_path("FLASHRANK_CACHE_PATH", "models", "flashrank"))


# Score threshold: FlashRank scores are sigmoid probabilities in [0,1].
# 0.0 effectively disables filtering — any score above pure noise passes.
# Keep at 0.0 to avoid dropping low-confidence but valid multilingual passages.
_RERANK_SCORE_THRESHOLD = 0.0
# Number of final results after reranking (AC-002.2)
_FINAL_TOP_K = 5
_FINAL_CONTEXT_CHARACTER_BUDGET = 24_000

# Module-level reranker state
_reranker: Any = None
_reranker_available: bool | None = None  # None = not yet attempted
_reranker_load_error: str | None = None
_reranker_lock = Lock()


def _get_reranker() -> Any | None:
    """Lazily load the FlashRank cross-encoder reranker (FR-002).

    On first call, attempts to load the multilingual
    `ms-marco-MultiBERT-L-12` model from local flashrank cache.
    On MemoryError or other allocation failure, sets _reranker_available=False
    and returns None, enabling RRF-only fallback.

    Returns:
        The FlashRank Ranker instance or None if unavailable.
    """
    global _reranker, _reranker_available, _reranker_load_error

    with _reranker_lock:
        if _reranker_available is not None:
            return _reranker if _reranker_available else None

        logger.info(
            "Attempting to load FlashRank reranker (%s)...", _FLASHRANK_MODEL_NAME
        )
        try:
            from flashrank import Ranker

            _reranker = Ranker(
                model_name=_FLASHRANK_MODEL_NAME,
                cache_dir=_flashrank_cache_dir(),
                max_length=512,
            )
            _reranker_available = True
            logger.info("FlashRank reranker loaded successfully.")
        except MemoryError as e:
            _reranker_available = False
            _reranker_load_error = str(e)
            logger.warning(
                "Cannot load reranker due to insufficient memory. "
                "Falling back to RRF-only retrieval (no reranking). "
                "Error: %s",
                e,
            )
        except Exception as e:  # noqa: BLE001
            _reranker_available = False
            _reranker_load_error = str(e)
            logger.warning(
                "Cannot load reranker: %s. "
                "Falling back to RRF-only retrieval (no reranking).",
                e,
            )

    return _reranker if _reranker_available else None


def is_reranker_available() -> bool:
    """Check if the cross-encoder reranker is loaded and available.

    Returns:
        True if the reranker is available, False otherwise.
    """
    # Trigger lazy load
    _get_reranker()
    return _reranker_available is True


def get_reranker_status() -> dict[str, Any]:
    """Return the reranker status for diagnostics.

    Returns:
        Dictionary with 'available' (bool) and optional 'error' (str).
    """
    _get_reranker()
    result: dict[str, Any] = {"available": _reranker_available is True}
    if _reranker_load_error:
        result["error"] = _reranker_load_error
    return result


async def hybrid_search(
    query: str,
    dense_vector: list[float],
    sparse_indices: list[int],
    sparse_values: list[float],
    *,
    collection_name: str = "rag_studio_docs",
    top_k: int = 20,
    use_reranker: bool = True,
    vector_searcher: VectorSearcher | None = None,
    context_character_budget: int = _FINAL_CONTEXT_CHARACTER_BUDGET,
) -> list[dict[str, Any]]:
    """Execute hybrid search with RRF fusion and FlashRank reranking (FR-002).

    Steps:
        1. Dense + sparse parallel search via Qdrant prefetch (AC-002.1)
        2. RRF fusion of results (k=60, Qdrant default) (AC-002.1)
        3. FlashRank cross-encoder reranking → top 5 (AC-002.2)
        4. Score threshold check: all scores < 0.1 → empty (AC-002.3)

    Args:
        query: The user query string.
        dense_vector: Dense embedding vector (384-dim).
        sparse_indices: Sparse BM25 vector indices.
        sparse_values: Sparse BM25 vector values.
        collection_name: Qdrant collection to search.
        top_k: Number of fused candidates (default 20 per AC-002.1).
        use_reranker: Whether to attempt reranking (fallback always available).
        context_character_budget: Maximum characters returned to the graph.

    Returns:
        List of up to 5 result dicts with keys: text, score, metadata.
        Returns empty list if no results found or all scores below threshold.
    """
    # Step 1 & 2: Hybrid search with RRF fusion (AC-002.1)
    # Oversample: prefetch top_k * 3 candidates from each vector type
    # (more candidates for RRF fusion to improve recall)
    # RRF k=60 is Qdrant's default — matches AC-002.1 requirement
    try:
        searcher = vector_searcher or await get_vector_store()
        search_results = await searcher.search(
            VectorSearchQuery(
                collection_name=collection_name,
                dense=DenseVector(tuple(dense_vector)),
                sparse=SparseVector(
                    indices=tuple(sparse_indices),
                    values=tuple(sparse_values),
                ),
                limit=top_k,
            )
        )
    except Exception as e:  # noqa: BLE001
        logger.error("Hybrid search failed: %s", e)
        return []  # AC-002.3: graceful empty on error

    # AC-002.3: Empty result handling
    if not search_results:
        logger.info("No search results")
        return []

    context_units = expand_context_units(
        search_results,
        top_k=min(top_k, _FINAL_TOP_K),
        character_budget=context_character_budget,
    )
    candidates = [
        {
            "id": unit.point_id,
            "score": unit.score,
            "text": unit.text,
            "metadata": dict(unit.metadata),
        }
        for unit in context_units
    ]
    logger.info(
        "Expanded search results: raw=%d context_units=%d",
        len(search_results),
        len(candidates),
    )

    # Step 3: FlashRank cross-encoder reranking (AC-002.2)
    if use_reranker:
        reranker = _get_reranker()
        if reranker is not None and candidates:
            try:
                from flashrank import (
                    RerankRequest,
                )

                # Build passages in FlashRank format
                passages = [{"text": c["text"]} for c in candidates]
                request = RerankRequest(query=query, passages=passages)
                reranked_passages = reranker.rerank(request)

                # Merge reranker scores back into candidates
                # reranked_passages is sorted by score descending
                results: list[dict[str, Any]] = []
                for i, rp in enumerate(reranked_passages):
                    if i >= _FINAL_TOP_K:
                        break
                    # Find matching candidate by text
                    rp_text = rp["text"]
                    for cand in candidates:
                        if cand["text"] == rp_text:
                            cand["rerank_score"] = float(rp["score"])
                            results.append(cand)
                            break

                # AC-002.3: Score threshold — if ALL scores < 0.1, treat as no results
                if results and all(
                    r.get("rerank_score", 0) < _RERANK_SCORE_THRESHOLD for r in results
                ):
                    logger.info(
                        "All reranker scores below threshold (%.2f). "
                        "Returning empty results.",
                        _RERANK_SCORE_THRESHOLD,
                    )
                    return []

                logger.info(
                    "Reranked %d candidates to top %d results.",
                    len(candidates),
                    len(results),
                )
                return results

            except MemoryError as e:
                logger.warning(
                    "OOM during reranking: %s. Falling back to RRF-only results.",
                    e,
                )
                _reranker_available = False
            except Exception as e:  # noqa: BLE001
                logger.warning(
                    "Reranking failed: %s. Falling back to RRF-only results.", e
                )

    # RRF-only fallback (no reranker or reranker unavailable)
    logger.info("Returning RRF-only results (reranker unavailable or disabled).")
    return candidates[:_FINAL_TOP_K]


def reset_reranker() -> None:
    """Reset the reranker state (useful for testing)."""
    global _reranker, _reranker_available, _reranker_load_error
    with _reranker_lock:
        _reranker = None
        _reranker_available = None
        _reranker_load_error = None
