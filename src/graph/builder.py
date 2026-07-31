"""LangGraph StateGraph builder and runner for the RAG-Studio chat graph (FR-003).

Assembles all 7 nodes with conditional edges and AsyncSqliteSaver checkpointer.
Uses the official LangGraph async pattern:
    async with AsyncSqliteSaver.from_conn_string(...) as saver:
        await saver.setup()
        graph = builder.compile(checkpointer=saver)
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, cast

from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.graph import END, StateGraph

from src.graph.nodes import (
    analyzer_node,
    cache_check_node,
    generate_from_cache_node,
    generate_from_retrieval_node,
    retrieve_node,
    save_to_cache_node,
    validate_node,
)
from src.graph.state import RAGState, _user_api_key_ctx, set_user_api_key

logger = logging.getLogger(__name__)


# ============================================================
# Routing Functions (Conditional Edges)
# ============================================================


def route_after_analyzer(state: RAGState) -> str:
    """Route ALL queries through cache_check first for maximum cache hit rate.

    Previously only follow-up questions were routed to cache_check.
    Now standalone questions also hit the cache, avoiding redundant
    retrieval + LLM generation for semantically similar queries.

    Args:
        state: Current RAGState after analyzer_node.

    Returns:
        Next node name: "cache_check" always.
    """
    return "cache_check"


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


def build_rag_graph() -> StateGraph:
    """Build the complete RAG-Studio chat graph with 7 nodes.

    Graph topology:
        START → analyzer
        analyzer → (conditional) → cache_check | retrieve
        cache_check → (conditional) → generate_from_cache | retrieve
        retrieve → generate_from_retrieval
        generate_from_cache → validate
        generate_from_retrieval → validate
        validate → (conditional) → save_to_cache | END
        save_to_cache → END

    Returns:
        Uncompiled StateGraph instance (compile with checkpointer separately).
    """
    builder = StateGraph(RAGState)

    # Add all 7 nodes
    # LangGraph StateGraph.add_node overloads have Unknown generic params
    # in type stubs — known library limitation, safe to ignore.
    builder.add_node("analyzer", analyzer_node)  # pyright: ignore[reportUnknownMemberType]
    builder.add_node("cache_check", cache_check_node)  # pyright: ignore[reportUnknownMemberType]
    builder.add_node("retrieve", retrieve_node)  # pyright: ignore[reportUnknownMemberType]
    builder.add_node("generate_from_cache", generate_from_cache_node)  # pyright: ignore[reportUnknownMemberType]
    builder.add_node("generate_from_retrieval", generate_from_retrieval_node)  # pyright: ignore[reportUnknownMemberType]
    builder.add_node("validate", validate_node)  # pyright: ignore[reportUnknownMemberType]
    builder.add_node("save_to_cache", save_to_cache_node)  # pyright: ignore[reportUnknownMemberType]

    # Set entry point
    builder.set_entry_point("analyzer")

    # All queries route through cache_check first
    builder.add_conditional_edges(
        "analyzer",
        route_after_analyzer,
        {"cache_check": "cache_check"},
    )

    # Conditional edges from cache_check
    builder.add_conditional_edges(
        "cache_check",
        route_after_cache_check,
        {"generate_from_cache": "generate_from_cache", "retrieve": "retrieve"},
    )

    # Linear edges
    builder.add_edge("retrieve", "generate_from_retrieval")
    builder.add_edge("generate_from_cache", "validate")
    builder.add_edge("generate_from_retrieval", "validate")

    # Conditional edges from validate
    builder.add_conditional_edges(
        "validate",
        route_after_validate,
        {"save_to_cache": "save_to_cache", "end": END},
    )

    # save_to_cache → END
    builder.add_edge("save_to_cache", END)

    logger.info("RAG graph built: 7 nodes, entry=analyzer")
    return builder


# ============================================================
# Custom Serializer — handles LangChain message objects in checkpoints
# ============================================================

# Known LangChain message class names and their short type codes.
# Must match what convert_to_messages expects ('human', 'ai', etc.).
_LC_MESSAGE_TYPE_MAP: dict[str, str] = {
    "HumanMessage": "human",
    "AIMessage": "ai",
    "SystemMessage": "system",
    "ToolMessage": "tool",
    "FunctionMessage": "function",
    "ChatMessage": "chat",
}

_LC_MESSAGE_TYPES: frozenset[str] = frozenset(_LC_MESSAGE_TYPE_MAP.keys())


def _convert_lc_messages(obj: object) -> object:
    """Recursively convert LangChain message objects to plain dicts.

    The default JsonPlusSerializer uses ormsgpack which cannot encode
    LangChain message objects when nested inside checkpoint metadata
    (e.g. the 'writes' field). This function walks the entire object
    graph and converts any LangChain message to a JSON-safe dict.
    """
    if obj is None or isinstance(obj, (str, int, float, bool, bytes, bytearray)):
        return obj
    type_name = type(obj).__name__
    if type_name in _LC_MESSAGE_TYPES and hasattr(obj, "content"):
        msg: dict[str, object] = {
            "type": _LC_MESSAGE_TYPE_MAP.get(type_name, type_name.lower()),
            "content": getattr(obj, "content", ""),
        }
        for attr in ("additional_kwargs", "response_metadata", "id", "name"):
            if hasattr(obj, attr):
                val = getattr(obj, attr)
                if val is not None:
                    msg[attr] = val
        return msg
    if isinstance(obj, dict):
        return {str(k): _convert_lc_messages(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_convert_lc_messages(item) for item in obj]
    return obj


class _RAGStudioSerializer(JsonPlusSerializer):
    """Custom serde that converts LangChain messages before msgpack encoding.

    Overrides dumps_typed (the method actually called by LangGraph's
    AsyncSqliteSaver) to pre-process objects and replace any LangChain
    message with its dict representation before ormsgpack encoding.
    """

    def dumps_typed(self, obj: object) -> tuple[str, bytes]:
        converted = _convert_lc_messages(obj)
        return super().dumps_typed(converted)

    def loads_typed(self, data: tuple[str, bytes]) -> object:
        """Restore serialized LangChain message dictionaries after loading."""
        from langchain_core.messages.utils import convert_to_messages

        def restore(value: object) -> object:
            if isinstance(value, dict):
                message_type = value.get("type")
                if isinstance(message_type, str) and message_type in {
                    "human",
                    "ai",
                    "system",
                    "tool",
                    "function",
                }:
                    return convert_to_messages([value])[0]
                return {str(key): restore(item) for key, item in value.items()}
            if isinstance(value, list):
                return [restore(item) for item in value]
            return value

        return restore(super().loads_typed(data))


# ============================================================
# Graph Lifecycle — AsyncSqliteSaver (Official LangGraph Pattern)
# ============================================================


def _default_checkpoints_path() -> str:
    """Return the absolute path to the checkpoints database.

    Resolves to ``<project_root>/data/checkpoints/checkpoints.db``.

    Returns:
        Absolute path string to the SQLite checkpoints database.
    """
    # __file__ → src/graph/builder.py
    # .parent → src/graph/
    # .parent.parent → src/
    # .parent.parent.parent → project root (RAG-Studio/)
    project_root = Path(__file__).resolve().parent.parent.parent
    return str(project_root / "data" / "checkpoints" / "checkpoints.db")


@asynccontextmanager
async def create_graph(
    db_path: str | None = None,
) -> AsyncIterator[Any]:
    """Create a compiled graph with AsyncSqliteSaver checkpointer.

    Uses the official LangGraph async pattern:
    1. Resolve the absolute db_path (defaults to
       ``<project_root>/data/checkpoints/checkpoints.db``).
    2. Ensure the parent directory exists.
    3. Open AsyncSqliteSaver connection via async context manager.
    4. Call setup() to create tables on first run.
    5. Compile the graph with the checkpointer.
    6. Yield the compiled graph for use.
    7. Close the connection on context exit.

    Args:
        db_path: Absolute or relative path to the SQLite database file.
            If None, uses ``<project_root>/data/checkpoints/checkpoints.db``.

    Yields:
        Compiled StateGraph ready for ainvoke/astream calls.

    Example:
        async with create_graph() as graph:
            result = await run_rag_graph(
                query="What is ML?",
                session_id="session-1",
                compiled_graph=graph,
            )
    """
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    resolved_path: str = db_path if db_path is not None else _default_checkpoints_path()

    # Ensure the parent directory exists so SQLite can create the file.
    Path(resolved_path).parent.mkdir(parents=True, exist_ok=True)

    import aiosqlite

    async with aiosqlite.connect(resolved_path) as conn:
        await conn.execute("PRAGMA journal_mode=WAL;")
        saver = AsyncSqliteSaver(conn, serde=_RAGStudioSerializer())

        # Wrap aput to convert LangChain messages in metadata before
        # the hard-coded json.dumps() call in AsyncSqliteSaver.aput.
        _orig_aput = saver.aput

        async def _wrapped_aput(
            config: dict[str, object],
            checkpoint: object,
            metadata: dict[str, object],
            new_versions: dict[str, object],
        ) -> None:
            safe_metadata = _convert_lc_messages(metadata)
            await _orig_aput(config, checkpoint, safe_metadata, new_versions)  # type: ignore[arg-type]

        saver.aput = _wrapped_aput  # type: ignore[assignment]

        await saver.setup()
        logger.info("AsyncSqliteSaver initialized (db=%s)", resolved_path)

        compiled_graph = build_rag_graph().compile(  # pyright: ignore[reportUnknownMemberType]
            checkpointer=saver,
        )
        logger.info("Graph compiled with AsyncSqliteSaver + _RAGStudioSerializer")

        yield compiled_graph

    logger.info("AsyncSqliteSaver connection closed (db=%s)", resolved_path)


# ============================================================
# Graph Runner
# ============================================================


async def run_rag_graph(
    query: str,
    session_id: str,
    user_api_key: str | None = None,
    *,
    compiled_graph: Any,
    provider: str = "openai",
    model: str = "gpt-4o-mini",
    temperature: float = 1.0,
    max_tokens: int = 2048,
    system_prompt: str = "",
) -> dict[str, Any]:
    """Run the RAG graph for a single query.

    Each invocation uses the session_id as thread_id for state isolation.
    The checkpointer persists state across invocations within the same session.

    Args:
        query: The user's message text.
        session_id: Unique session identifier (used as thread_id).
        user_api_key: Optional API key from user settings.
        compiled_graph: A compiled graph instance (from create_graph()).
        provider: LLM provider (openai, deepseek, anthropic, ollama).
        model: Model name for generation.
        temperature: Temperature for LLM generation (0.0–2.0).
        max_tokens: Maximum tokens for generation.
        system_prompt: Custom system prompt from settings.

    Returns:
        Dict with keys: final_answer, generated_from, faithfulness_score,
        retrieved_docs, citations.
    """
    from langchain_core.messages import HumanMessage

    config: dict[str, Any] = {
        "configurable": {
            "thread_id": session_id,  # isolates state per session (AC-003.4)
        },
    }

    initial_state: dict[str, Any] = {
        "messages": [HumanMessage(content=query)],
        "query": query,
        "intent": "",
        "cache_hit": False,
        "cached_answer": None,
        "retrieved_docs": [],
        "reranked_docs": [],
        "generated_from": "",
        "final_answer": None,
        "faithfulness_score": 0.0,
        "validation_passed": False,
        "session_id": session_id,
        "provider": provider,
        "model_name": model,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "system_prompt": system_prompt,
    }

    # SEC-H02: Store API key in a context variable, not in config.
    # Context vars are NOT traced by LangSmith and NOT persisted by the
    # checkpointer, so the API key never appears in traces or local storage.
    token = set_user_api_key(user_api_key)
    try:
        result = await compiled_graph.ainvoke(initial_state, config)
    finally:
        _user_api_key_ctx.reset(token)

    # Build citations from retrieved docs
    citations: list[dict[str, object]] = []
    raw_docs: object = result.get("retrieved_docs", [])
    retrieved_docs: list[dict[str, Any]] = (
        [dict(d) for d in cast("list[dict[str, Any]]", raw_docs)]
        if isinstance(raw_docs, list)
        else []
    )
    for i, doc in enumerate(retrieved_docs):
        metadata: dict[str, Any] = dict(doc.get("metadata", {}))
        citations.append(
            {
                "index": i + 1,
                "chunk_text": str(doc.get("text", "")),
                "filename": str(metadata.get("filename", "unknown")),
                "chunk_index": str(metadata.get("chunk_index", "?")),
                "score": float(doc.get("score", 0.0)),
            }
        )

    logger.info(
        "run_rag_graph: session=%s, generated_from=%s, faithfulness=%.3f, docs=%d",
        session_id,
        result.get("generated_from", ""),
        result.get("faithfulness_score", 0.0),
        len(citations),
    )

    return {
        "final_answer": result.get("final_answer"),
        "generated_from": str(result.get("generated_from", "")),
        "faithfulness_score": float(result.get("faithfulness_score", 0.0)),
        "retrieved_docs": retrieved_docs,
        "citations": citations,
    }
