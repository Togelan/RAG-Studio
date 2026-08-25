"""RAG graph topology and node binding."""

from __future__ import annotations

import logging
from functools import partial
from typing import TYPE_CHECKING

from langgraph.graph import END, StateGraph

from src.graph.llm_provider import LLMProviderFactory, OpenAIProviderFactory
from src.graph.nodes import (
    analyzer_node,
    cache_check_node,
    generate_from_cache_node,
    generate_from_retrieval_node,
    retrieve_node,
    save_to_cache_node,
    validate_node,
)
from src.graph.state import RAGState

if TYPE_CHECKING:
    from src.ingestion.embedding import Embedder
    from src.vector_store.contracts import VectorStore
    from src.vector_store.tenant_store import TenantCacheScope, TenantRagStore

logger = logging.getLogger(__name__)
_DEFAULT_PROVIDER_FACTORY = OpenAIProviderFactory()


def route_after_analyzer(state: RAGState) -> str:
    """Route based on intent: follow-up → cache_check, standalone → retrieve.

    Args:
        state: Current RAGState after analyzer_node.

    Returns:
        Next node name: "cache_check" or "retrieve".
    """
    if state["intent"] == "follow_up_question":
        return "cache_check"
    return "retrieve"


def route_after_cache_check(state: RAGState) -> str:
    """Route based on cache hit.

    - True → generate_from_cache (skip retrieval + LLM generation)
    - False → retrieve (run full pipeline)

    Args:
        state: Current RAGState after cache_check_node.

    Returns:
        Next node name: "generate_from_cache" or "retrieve".
    """
    if state["cache_hit"]:
        return "generate_from_cache"
    return "retrieve"


def route_after_validate(state: RAGState) -> str:
    """Route based on validation result and generation source.

    - Cache-sourced → END (already in cache)
    - Retrieval-sourced + validation passed → save_to_cache
    - Retrieval-sourced + validation failed → END (don't cache bad answers)

    Args:
        state: Current RAGState after validate_node.

    Returns:
        Next node name: "save_to_cache" or "__end__".
    """
    if state["generated_from"] == "cache":
        return "end"
    if state.get("validation_passed", False):
        return "save_to_cache"
    return "end"


# ============================================================
# Graph Builder
# ============================================================


def build_rag_graph(
    provider_factory: LLMProviderFactory = _DEFAULT_PROVIDER_FACTORY,
    *,
    embedder: Embedder | None = None,
    vector_store: VectorStore | None = None,
    tenant_store: TenantRagStore | None = None,
    cache_scope: TenantCacheScope | None = None,
    provider_api_key: str | None = None,
) -> StateGraph:
    """Build the seven-node RAG graph with injected capabilities."""
    builder = StateGraph(RAGState)
    _bind_nodes(
        builder,
        provider_factory,
        embedder=embedder,
        vector_store=vector_store,
        tenant_store=tenant_store,
        cache_scope=cache_scope,
        provider_api_key=provider_api_key,
    )
    _bind_edges(builder)
    logger.info("RAG graph built: 7 nodes, entry=analyzer")
    return builder


def _bind_nodes(
    builder: StateGraph,
    provider_factory: LLMProviderFactory,
    *,
    embedder: Embedder | None,
    vector_store: VectorStore | None,
    tenant_store: TenantRagStore | None,
    cache_scope: TenantCacheScope | None,
    provider_api_key: str | None,
) -> None:

    # LangGraph StateGraph.add_node overloads have Unknown generic params
    # in type stubs — known library limitation, safe to ignore.
    builder.add_node(
        "analyzer",
        partial(
            analyzer_node,
            provider_factory=provider_factory,
            provider_api_key=provider_api_key,
        ),
    )
    builder.add_node(
        "cache_check",
        partial(
            cache_check_node,
            embedder=embedder,
            vector_store=vector_store,
            tenant_store=tenant_store,
            cache_scope=cache_scope,
        ),
    )
    builder.add_node(
        "retrieve",
        partial(
            retrieve_node,
            embedder=embedder,
            vector_searcher=vector_store,
            tenant_store=tenant_store,
        ),
    )
    builder.add_node("generate_from_cache", generate_from_cache_node)
    builder.add_node(
        "generate_from_retrieval",
        partial(
            generate_from_retrieval_node,
            provider_factory=provider_factory,
            provider_api_key=provider_api_key,
        ),
    )
    builder.add_node(
        "validate",
        partial(
            validate_node,
            provider_factory=provider_factory,
            provider_api_key=provider_api_key,
        ),
    )
    builder.add_node(
        "save_to_cache",
        partial(
            save_to_cache_node,
            embedder=embedder,
            vector_store=vector_store,
            tenant_store=tenant_store,
            cache_scope=cache_scope,
        ),
    )


def _bind_edges(builder: StateGraph) -> None:
    builder.set_entry_point("analyzer")
    builder.add_conditional_edges(
        "analyzer",
        route_after_analyzer,
        {"cache_check": "cache_check", "retrieve": "retrieve"},
    )

    builder.add_conditional_edges(
        "cache_check",
        route_after_cache_check,
        {"generate_from_cache": "generate_from_cache", "retrieve": "retrieve"},
    )

    builder.add_edge("retrieve", "generate_from_retrieval")
    builder.add_edge("generate_from_cache", "validate")
    builder.add_edge("generate_from_retrieval", "validate")

    builder.add_conditional_edges(
        "validate",
        route_after_validate,
        {"save_to_cache": "save_to_cache", "end": END},
    )

    builder.add_edge("save_to_cache", END)
