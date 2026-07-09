"""LangGraph StateGraph builder and runner for the RAG-Studio chat graph (FR-003).

Assembles all 7 nodes with conditional edges and a patched AsyncSqliteSaver
checkpointer that uses JsonPlusSerializer for both checkpoint data AND metadata,
fixing the langgraph 0.4.x bug where json.dumps() on metadata fails on
HumanMessage objects in writes.__start__.messages.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, cast

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
from src.graph.state import RAGState

if TYPE_CHECKING:
    from langchain_core.runnables import RunnableConfig
    from langgraph.checkpoint.base import (
        ChannelVersions,
        Checkpoint,
        CheckpointMetadata,
    )

logger = logging.getLogger(__name__)


# ============================================================
# JSON Sanitizer — prevents UnicodeDecodeError in checkpointer
# ============================================================


def _sanitize_for_json(obj: Any) -> Any:
    """Recursively sanitize values for JSON serialization.

    Converts non-JSON-serializable types:
    - bytes → str via repr() (produces b'...' strings)
    - dict keys/values → recursive sanitize
    - list/tuple/set items → recursive sanitize
    - Any other non-serializable type → str() fallback

    Args:
        obj: The value to sanitize.

    Returns:
        A JSON-serializable version of the input.
    """
    if isinstance(obj, bytes):
        logger.warning(
            "Sanitized non-serializable value: type=%s, repr=%.200s",
            type(obj).__name__,
            repr(obj)[:200],
        )
        return repr(obj)  # b'...' — valid JSON string
    if isinstance(obj, dict):
        return {
            _sanitize_for_json(k): _sanitize_for_json(v)
            for k, v in obj.items()  # pyright: ignore[reportUnknownVariableType]
        }
    if isinstance(obj, (list, tuple, set)):
        return [
            _sanitize_for_json(item)  # pyright: ignore[reportUnknownVariableType]
            for item in obj  # pyright: ignore[reportUnknownVariableType]
        ]
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    # Fallback: convert to string
    logger.warning(
        "Sanitized non-serializable value: type=%s, repr=%.200s",
        type(obj).__name__,
        repr(obj)[:200],
    )
    return str(obj)


# ============================================================
# Routing Functions (Conditional Edges)
# ============================================================


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

    # Conditional edges from analyzer
    builder.add_conditional_edges(
        "analyzer",
        route_after_analyzer,
        {"cache_check": "cache_check", "retrieve": "retrieve"},
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
# Graph Lifecycle — AsyncSqliteSaver (persistent checkpointer)
# ============================================================


@asynccontextmanager
async def create_graph(
    db_path: str | None = None,
) -> AsyncIterator[Any]:
    """Create a compiled graph with AsyncSqliteSaver checkpointer.

    Uses a patched AsyncSqliteSaver with persistent SQLite storage and
    JsonPlusSerializer for LangChain message serialization in WRITES,
    so chat sessions survive server restarts. Falls back to
    MemorySaver if db_path is not provided.

    The patched subclass overrides aput_writes() to use serde for the
    VALUE column (BLOB) which may contain HumanMessage/AIMessage objects.
    The aput() method uses json.dumps() for metadata (TEXT column —
    aget_tuple reads it via json.loads()) and serde only for checkpoints.
    This fixes the langgraph 0.4.x bug where json.dumps() on writes
    crashes on HumanMessage objects.

    Args:
        db_path: Path to SQLite database for checkpoint persistence.

    Yields:
        Compiled StateGraph ready for ainvoke/astream calls.
    """
    from pathlib import Path

    from langgraph.checkpoint.memory import MemorySaver
    from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    if db_path:
        db_path_resolved = str(Path(db_path).resolve())
        Path(db_path_resolved).parent.mkdir(parents=True, exist_ok=True)

        from collections.abc import Sequence

        import aiosqlite

        async with aiosqlite.connect(db_path_resolved) as conn:
            serde = JsonPlusSerializer()

            # Patched subclass: overrides aput() and aput_writes() to fix
            # LangGraph 0.4.x serialization bugs:
            # - aput:     checkpoint uses serde (BLOB), metadata uses json.dumps()
            #             (TEXT — aget_tuple reads via json.loads())
            # - aput_writes: channel uses json.dumps() (TEXT), value uses serde
            #             (BLOB — may contain HumanMessage/AIMessage objects)
            class _PatchedSaver(AsyncSqliteSaver):
                async def aput(
                    self,
                    config: RunnableConfig,
                    checkpoint: Checkpoint,
                    metadata: CheckpointMetadata,
                    new_versions: ChannelVersions,
                ) -> RunnableConfig:
                    # Serialize checkpoint with serde (JsonPlusSerializer)
                    type_, serialized_checkpoint = self.serde.dumps_typed(checkpoint)

                    # Serialize metadata with serde (NOT json.dumps()).
                    # BUGFIX: Previously json.dumps() was used here, but
                    # aget_tuple() reads metadata via serde.loads_typed().
                    # The mismatch caused UnicodeDecodeError ("Input must be
                    # bytes, bytearray, memoryview") on every checkpoint read,
                    # making sessions disappear after server restart.
                    _, serialized_metadata = self.serde.dumps_typed(metadata)
                    await self.setup()
                    configurable: dict[str, Any] = config.get("configurable", {})
                    thread_id = configurable["thread_id"]
                    checkpoint_ns = configurable["checkpoint_ns"]

                    # Diagnostic log: what is being saved to the checkpointer
                    import json as _json

                    channel_values: object = checkpoint.get("channel_values", {})
                    raw_msgs: object = (
                        channel_values.get("messages", [])  # type: ignore[union-attr]
                    )
                    msg_count = (
                        len(cast("list[object]", raw_msgs))
                        if isinstance(raw_msgs, (list, tuple))
                        else 0
                    )
                    meta_keys: object = list(metadata.keys())
                    logger.info(
                        "aput: thread_id=%s, checkpoint_id=%.8s, "
                        "messages_in_state=%d, metadata_keys=%s",
                        thread_id,
                        str(checkpoint.get("id", ""))[:8],
                        msg_count,
                        _json.dumps(meta_keys, default=str)[:200],
                    )

                    async with (
                        self.lock,
                        self.conn.execute(
                            "INSERT OR REPLACE INTO checkpoints "
                            "(thread_id, checkpoint_ns, checkpoint_id, "
                            "parent_checkpoint_id, type, checkpoint, metadata) "
                            "VALUES (?, ?, ?, ?, ?, ?, ?)",
                            (
                                str(thread_id),
                                checkpoint_ns,
                                checkpoint["id"],
                                configurable.get("checkpoint_id"),
                                type_,
                                serialized_checkpoint,
                                serialized_metadata,
                            ),
                        ),
                    ):
                        await self.conn.commit()
                    return {
                        "configurable": {
                            "thread_id": thread_id,
                            "checkpoint_ns": checkpoint_ns,
                            "checkpoint_id": checkpoint["id"],
                        }
                    }

                async def aput_writes(
                    self,
                    config: RunnableConfig,
                    writes: Sequence[tuple[str, Any]],
                    task_id: str,
                    task_path: str = "",
                ) -> None:
                    """Override aput_writes to use serde for VALUE serialization.

                    langgraph 0.4.x AsyncSqliteSaver.aput_writes() calls
                    json.dumps() on write VALUES which crashes when writes
                    contain LangChain message objects (e.g., messages channel
                    with HumanMessage/AIMessage in writes).

                    Only the VALUE column uses serde (BLOB). The CHANNEL column
                    (TEXT) uses json.dumps() as expected by the table schema.
                    """
                    import json as _json

                    await self.setup()
                    configurable: dict[str, Any] = config.get("configurable", {})
                    thread_id = configurable["thread_id"]
                    checkpoint_ns = configurable["checkpoint_ns"]
                    checkpoint_id = configurable["checkpoint_id"]

                    # Diagnostic: log what writes are being saved
                    write_channels = [ch for ch, _ in writes]
                    logger.info(
                        "aput_writes: thread_id=%s, checkpt=%.8s, "
                        "task_id=%.8s, channels=%s, count=%d",
                        thread_id,
                        str(checkpoint_id)[:8],
                        str(task_id)[:8],
                        write_channels,
                        len(writes),
                    )

                    async with self.lock:
                        for idx, (channel, value) in enumerate(writes):
                            # Channel is TEXT — use json.dumps() (original behavior)
                            channel_str = (
                                _json.dumps(channel)
                                if not isinstance(channel, str)  # pyright: ignore[reportUnnecessaryIsInstance]
                                else channel
                            )
                            # Value may contain LangChain messages — use serde
                            # Wrap in try/except with sanitize fallback for bytes
                            try:
                                type_, serialized_value = self.serde.dumps_typed(value)
                            except Exception as exc:
                                logger.warning(
                                    "aput_writes: value serialization failed "
                                    "(%s: %s), attempting sanitize fallback.",
                                    type(exc).__name__,
                                    exc,
                                )
                                sanitized_value = _sanitize_for_json(value)
                                type_, serialized_value = self.serde.dumps_typed(
                                    sanitized_value
                                )
                            await self.conn.execute(
                                "INSERT OR REPLACE INTO writes "
                                "(thread_id, checkpoint_ns, checkpoint_id, "
                                "task_id, idx, channel, type, value) "
                                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                                (
                                    str(thread_id),
                                    checkpoint_ns,
                                    checkpoint_id,
                                    task_id,
                                    idx,
                                    channel_str,
                                    type_,
                                    serialized_value,
                                ),
                            )
                        await self.conn.commit()

                async def aget_tuple(
                    self, config: RunnableConfig
                ) -> Any:  # CheckpointTuple | None
                    """Override aget_tuple to use serde.loads_typed() for checkpoint and metadata.

                    Since aput() and aput_writes() now serialize checkpoints and
                    metadata using serde.dumps_typed() (not json.dumps()), the
                    read path must also use serde.loads_typed().

                    Backward compatibility: old checkpoints may have metadata
                    stored as plain JSON text (bug from v0.1). If
                    serde.loads_typed() fails on metadata, fall back to
                    json.loads().
                    """
                    await self.setup()
                    _configurable: dict[str, Any] = config.get("configurable", {})
                    checkpoint_ns = _configurable.get("checkpoint_ns", "")
                    async with self.lock, self.conn.cursor() as cur:
                        from langgraph.checkpoint.base import (
                            get_checkpoint_id,
                        )

                        if checkpoint_id := get_checkpoint_id(config):
                            await cur.execute(
                                "SELECT thread_id, checkpoint_id, "
                                "parent_checkpoint_id, type, checkpoint, metadata "
                                "FROM checkpoints WHERE thread_id = ? "
                                "AND checkpoint_ns = ? AND checkpoint_id = ?",
                                (
                                    str(_configurable["thread_id"]),
                                    checkpoint_ns,
                                    checkpoint_id,
                                ),
                            )
                        else:
                            await cur.execute(
                                "SELECT thread_id, checkpoint_id, "
                                "parent_checkpoint_id, type, checkpoint, metadata "
                                "FROM checkpoints WHERE thread_id = ? "
                                "AND checkpoint_ns = ? "
                                "ORDER BY checkpoint_id DESC LIMIT 1",
                                (
                                    str(_configurable["thread_id"]),
                                    checkpoint_ns,
                                ),
                            )
                        if value := await cur.fetchone():
                            (
                                thread_id,
                                cp_id,
                                parent_checkpoint_id,
                                type_,
                                checkpoint_blob,
                                metadata_blob,
                            ) = value
                            if not get_checkpoint_id(config):
                                config = {
                                    "configurable": {
                                        "thread_id": thread_id,
                                        "checkpoint_ns": checkpoint_ns,
                                        "checkpoint_id": cp_id,
                                    }
                                }
                            # Use serde.loads_typed() for checkpoint
                            checkpoint = self.serde.loads_typed(
                                (type_, checkpoint_blob)
                            )
                            # Deserialize metadata.
                            # Try serde.loads_typed() first (new format).
                            # Fall back to json.loads() for old-format metadata
                            # that was stored as plain JSON text (BUGFIX v0.1).
                            metadata: Any = {}
                            if metadata_blob is not None:
                                try:
                                    metadata = self.serde.loads_typed(
                                        (type_, metadata_blob)
                                    )
                                except Exception as meta_err:
                                    import json as _json

                                    logger.warning(
                                        "aget_tuple: metadata serde.loads_typed "
                                        "failed (%s: %s), trying json.loads() "
                                        "for backward compat.",
                                        type(meta_err).__name__,
                                        meta_err,
                                    )
                                    try:
                                        # Handle both str and bytes
                                        meta_str = (
                                            metadata_blob.decode("utf-8")
                                            if isinstance(metadata_blob, bytes)
                                            else str(metadata_blob)
                                        )
                                        metadata = _json.loads(meta_str)
                                    except Exception as json_err:
                                        logger.error(
                                            "aget_tuple: json.loads fallback "
                                            "also failed: %s",
                                            json_err,
                                        )
                                        metadata = {}
                            # Read pending writes
                            await cur.execute(
                                "SELECT task_id, channel, type, value "
                                "FROM writes WHERE thread_id = ? "
                                "AND checkpoint_ns = ? AND checkpoint_id = ? "
                                "ORDER BY task_id, idx",
                                (
                                    str(thread_id),
                                    checkpoint_ns,
                                    str(cp_id),
                                ),
                            )
                            writes_list = [
                                (
                                    task_id,
                                    channel,
                                    self.serde.loads_typed((w_type, w_value)),
                                )
                                for task_id, channel, w_type, w_value in await cur.fetchall()
                            ]
                            from langgraph.checkpoint.base import (
                                CheckpointTuple,
                            )

                            return CheckpointTuple(
                                config=config,
                                checkpoint=checkpoint,
                                metadata=metadata,
                                parent_config=(
                                    {
                                        "configurable": {
                                            "thread_id": thread_id,
                                            "checkpoint_ns": checkpoint_ns,
                                            "checkpoint_id": parent_checkpoint_id,
                                        }
                                    }
                                    if parent_checkpoint_id
                                    else None
                                ),
                                pending_writes=writes_list if writes_list else None,
                            )
                        return None

            saver = _PatchedSaver(conn, serde=serde)
            await saver.setup()
            logger.info(
                "AsyncSqliteSaver initialized: path=%s, serde=JsonPlusSerializer (patched aput + aput_writes)",
                db_path_resolved,
            )

            compiled_graph = build_rag_graph().compile(  # pyright: ignore[reportUnknownMemberType]
                checkpointer=saver,
            )
            logger.info("Graph compiled with AsyncSqliteSaver checkpointer")

            yield compiled_graph
    else:
        memory_saver = MemorySaver()
        logger.info(
            "MemorySaver initialized (in-memory, no persistence across restarts)",
        )

        compiled_graph = build_rag_graph().compile(  # pyright: ignore[reportUnknownMemberType]
            checkpointer=memory_saver,
        )
        logger.info("Graph compiled with MemorySaver checkpointer")

        yield compiled_graph

    logger.info("Graph context closed")


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
        }
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
        "user_api_key": user_api_key,
        "provider": provider,
        "model_name": model,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "system_prompt": system_prompt,
    }

    result = await compiled_graph.ainvoke(initial_state, config)

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
