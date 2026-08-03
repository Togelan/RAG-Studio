"""LangGraph StateGraph builder and runner for the RAG-Studio chat graph (FR-003).

Assembles all 7 nodes with conditional edges and a patched AsyncSqliteSaver
checkpointer that uses JsonPlusSerializer for both checkpoint data AND metadata,
fixing the langgraph 0.4.x bug where json.dumps() on metadata fails on
HumanMessage objects in writes.__start__.messages.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import asynccontextmanager
from functools import partial
from typing import TYPE_CHECKING, Any, cast

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
    from langchain_core.runnables import RunnableConfig
    from langgraph.checkpoint.base import (
        ChannelVersions,
        Checkpoint,
        CheckpointMetadata,
    )

    from src.ingestion.embedding import Embedder
    from src.vector_store.contracts import VectorStore

logger = logging.getLogger(__name__)

_DEFAULT_PROVIDER_FACTORY = OpenAIProviderFactory()


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


def build_rag_graph(
    provider_factory: LLMProviderFactory = _DEFAULT_PROVIDER_FACTORY,
    *,
    embedder: Embedder | None = None,
    vector_store: VectorStore | None = None,
) -> StateGraph:
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
    builder.add_node(  # pyright: ignore[reportUnknownMemberType]
        "analyzer",
        partial(analyzer_node, provider_factory=provider_factory),
    )
    builder.add_node(  # pyright: ignore[reportUnknownMemberType]
        "cache_check",
        partial(cache_check_node, embedder=embedder, vector_store=vector_store),
    )
    builder.add_node(  # pyright: ignore[reportUnknownMemberType]
        "retrieve",
        partial(retrieve_node, embedder=embedder, vector_searcher=vector_store),
    )
    builder.add_node("generate_from_cache", generate_from_cache_node)  # pyright: ignore[reportUnknownMemberType]
    builder.add_node(  # pyright: ignore[reportUnknownMemberType]
        "generate_from_retrieval",
        partial(generate_from_retrieval_node, provider_factory=provider_factory),
    )
    builder.add_node(  # pyright: ignore[reportUnknownMemberType]
        "validate",
        partial(validate_node, provider_factory=provider_factory),
    )
    builder.add_node(  # pyright: ignore[reportUnknownMemberType]
        "save_to_cache",
        partial(save_to_cache_node, embedder=embedder, vector_store=vector_store),
    )

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
    provider_factory: LLMProviderFactory = _DEFAULT_PROVIDER_FACTORY,
    *,
    embedder: Embedder | None = None,
    vector_store: VectorStore | None = None,
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
                        channel_values.get("messages", [])
                        if isinstance(channel_values, Mapping)
                        else []
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
                            except Exception as exc:  # noqa: BLE001 - serializer boundary
                                logger.warning(
                                    "aput_writes: value serialization failed "
                                    "(%s), attempting sanitize fallback.",
                                    type(exc).__name__,
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
                                except Exception as meta_err:  # noqa: BLE001 - compatibility boundary
                                    import json as _json

                                    logger.warning(
                                        "aget_tuple: metadata serde.loads_typed "
                                        "failed (%s), trying json.loads() "
                                        "for backward compat.",
                                        type(meta_err).__name__,
                                    )
                                    try:
                                        # Handle both str and bytes
                                        meta_str = (
                                            metadata_blob.decode("utf-8")
                                            if isinstance(metadata_blob, bytes)
                                            else str(metadata_blob)
                                        )
                                        metadata = _json.loads(meta_str)
                                    except Exception as json_err:  # noqa: BLE001 - corrupt legacy metadata
                                        logger.error(
                                            "aget_tuple: json.loads fallback "
                                            "also failed (%s)",
                                            type(json_err).__name__,
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

            compiled_graph = build_rag_graph(  # pyright: ignore[reportUnknownMemberType]
                provider_factory,
                embedder=embedder,
                vector_store=vector_store,
            ).compile(
                checkpointer=saver,
            )
            logger.info("Graph compiled with AsyncSqliteSaver checkpointer")

            yield compiled_graph
    else:
        memory_saver = MemorySaver()
        logger.info(
            "MemorySaver initialized (in-memory, no persistence across restarts)",
        )

        compiled_graph = build_rag_graph(  # pyright: ignore[reportUnknownMemberType]
            provider_factory,
            embedder=embedder,
            vector_store=vector_store,
        ).compile(
            checkpointer=memory_saver,
        )
        logger.info("Graph compiled with MemorySaver checkpointer")

        yield compiled_graph

    logger.info("Graph context closed")


# ============================================================
# Graph Runner
# ============================================================


class GraphResultError(RuntimeError):
    """Raised when a graph emits a result with an unsafe or invalid shape."""


def _graph_inputs(
    query: str,
    session_id: str,
    user_api_key: str | None,
    *,
    provider: str,
    model: str,
    temperature: float,
    max_tokens: int,
    system_prompt: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build isolated LangGraph config and initial state for one user turn."""
    from langchain_core.messages import HumanMessage

    config: dict[str, Any] = {
        "configurable": {"thread_id": session_id},
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
    return config, initial_state


def _normalize_graph_result(result: object, *, session_id: str) -> dict[str, Any]:
    """Validate graph output boundaries and construct safe citation metadata."""
    if not isinstance(result, Mapping):
        logger.error(
            "Invalid graph result: session=%s type=%s",
            session_id,
            type(result).__name__,
        )
        raise GraphResultError("Graph returned an invalid result")

    final_answer = result.get("final_answer")
    if not isinstance(final_answer, str):
        logger.error(
            "Invalid graph final_answer: session=%s type=%s",
            session_id,
            type(final_answer).__name__,
        )
        raise GraphResultError("Graph returned an invalid answer")

    raw_docs = result.get("retrieved_docs", [])
    if not isinstance(raw_docs, Sequence) or isinstance(raw_docs, (str, bytes)):
        logger.error(
            "Invalid graph retrieved_docs: session=%s type=%s",
            session_id,
            type(raw_docs).__name__,
        )
        raise GraphResultError("Graph returned invalid retrieval data")

    retrieved_docs: list[dict[str, Any]] = []
    citations: list[dict[str, object]] = []
    for index, raw_doc in enumerate(raw_docs):
        if not isinstance(raw_doc, Mapping):
            logger.error(
                "Invalid graph document: session=%s index=%d type=%s",
                session_id,
                index,
                type(raw_doc).__name__,
            )
            raise GraphResultError("Graph returned invalid retrieval data")
        doc = dict(raw_doc)
        raw_metadata = doc.get("metadata", {})
        if not isinstance(raw_metadata, Mapping):
            raise GraphResultError("Graph returned invalid document metadata")
        metadata = dict(raw_metadata)
        try:
            score = float(doc.get("score", 0.0))
        except (TypeError, ValueError) as exc:
            raise GraphResultError("Graph returned an invalid document score") from exc
        retrieved_docs.append(doc)
        citations.append(
            {
                "index": index + 1,
                "chunk_text": str(doc.get("text", "")),
                "filename": str(
                    metadata.get("filename", metadata.get("source", "unknown"))
                ),
                "chunk_index": str(metadata.get("chunk_index", "?")),
                "score": score,
            }
        )

    try:
        faithfulness_score = float(result.get("faithfulness_score", 0.0))
    except (TypeError, ValueError) as exc:
        raise GraphResultError("Graph returned an invalid faithfulness score") from exc

    normalized = {
        "final_answer": final_answer,
        "generated_from": str(result.get("generated_from", "")),
        "faithfulness_score": faithfulness_score,
        "retrieved_docs": retrieved_docs,
        "citations": citations,
    }
    logger.info(
        "Graph result normalized: session=%s source=%s docs=%d",
        session_id,
        normalized["generated_from"],
        len(citations),
    )
    return normalized


def _stream_chunk_text(message: object) -> str:
    """Extract text from a LangChain message chunk without stringifying metadata."""
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    if not isinstance(content, Sequence) or isinstance(content, (str, bytes)):
        return ""
    parts: list[str] = []
    for item in content:
        if isinstance(item, str):
            parts.append(item)
        elif isinstance(item, Mapping):
            text = item.get("text")
            if isinstance(text, str):
                parts.append(text)
    return "".join(parts)


async def stream_rag_graph(
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
) -> AsyncIterator[dict[str, Any]]:
    """Yield genuine generation chunks followed by one validated graph result.

    LangGraph's ``custom`` stream relays provider chunks emitted by the grounded
    generation node as it receives them. The ``values`` stream is retained until
    validation and cache persistence complete.
    """
    config, initial_state = _graph_inputs(
        query,
        session_id,
        user_api_key,
        provider=provider,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        system_prompt=system_prompt,
    )

    final_state: object | None = None
    emitted_provider_token = False
    async for mode, payload in compiled_graph.astream(
        initial_state,
        config,
        stream_mode=["custom", "values"],
    ):
        if mode == "values":
            final_state = payload
            continue
        if mode != "custom" or not isinstance(payload, Mapping):
            continue
        if payload.get("type") != "token":
            continue
        token = payload.get("token")
        if isinstance(token, str) and token:
            emitted_provider_token = True
            yield {"type": "token", "token": token}

    if final_state is None:
        raise GraphResultError("Graph stream completed without a result")
    normalized = _normalize_graph_result(final_state, session_id=session_id)
    if normalized["generated_from"] == "cache" and normalized["final_answer"]:
        yield {"type": "token", "token": normalized["final_answer"]}
    elif normalized["generated_from"] == "retrieval" and not emitted_provider_token:
        logger.error("Provider stream emitted no tokens: session=%s", session_id)
        raise GraphResultError("Provider stream completed without tokens")
    yield {"type": "result", "result": normalized}


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
    config, initial_state = _graph_inputs(
        query,
        session_id,
        user_api_key,
        provider=provider,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        system_prompt=system_prompt,
    )
    result = await compiled_graph.ainvoke(initial_state, config)
    return _normalize_graph_result(result, session_id=session_id)
