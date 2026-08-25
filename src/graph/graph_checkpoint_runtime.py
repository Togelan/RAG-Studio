"""Async SQLite checkpoint lifecycle for compiled RAG graphs."""  # noqa: SIZE_OK

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, cast

from src.graph.graph_topology import build_rag_graph
from src.graph.llm_provider import LLMProviderFactory, OpenAIProviderFactory

if TYPE_CHECKING:
    from langchain_core.runnables import RunnableConfig
    from langgraph.checkpoint.base import (
        ChannelVersions,
        Checkpoint,
        CheckpointMetadata,
    )

    from src.ingestion.embedding import Embedder
    from src.vector_store.contracts import VectorStore
    from src.vector_store.tenant_store import TenantCacheScope, TenantRagStore

logger = logging.getLogger(__name__)
_DEFAULT_PROVIDER_FACTORY = OpenAIProviderFactory()


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
        return {_sanitize_for_json(k): _sanitize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [_sanitize_for_json(item) for item in obj]
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    # Fallback: convert to string
    logger.warning(
        "Sanitized non-serializable value: type=%s, repr=%.200s",
        type(obj).__name__,
        repr(obj)[:200],
    )
    return str(obj)


@asynccontextmanager
async def _create_graph(
    db_path: str | None = None,
    provider_factory: LLMProviderFactory = _DEFAULT_PROVIDER_FACTORY,
    *,
    embedder: Embedder | None = None,
    vector_store: VectorStore | None = None,
    tenant_store: TenantRagStore | None = None,
    cache_scope: TenantCacheScope | None = None,
    provider_api_key: str | None = None,
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

                    channel_values: Any = checkpoint.get("channel_values", {})
                    raw_msgs: Any = (
                        channel_values.get("messages", [])
                        if isinstance(channel_values, Mapping)
                        else []
                    )
                    msg_count = (
                        len(cast("list[Any]", raw_msgs))
                        if isinstance(raw_msgs, (list, tuple))
                        else 0
                    )
                    meta_keys: Any = list(metadata.keys())
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
                                if not isinstance(channel, str)
                                else channel
                            )
                            # Value may contain LangChain messages — use serde
                            # Wrap in try/except with sanitize fallback for bytes
                            try:
                                type_, serialized_value = self.serde.dumps_typed(value)
                            except Exception as exc:  # noqa: BLE001  # noqa: BROAD_EXCEPT_OK -- serializer boundary
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
                                except Exception as meta_err:  # noqa: BLE001  # noqa: BROAD_EXCEPT_OK -- compatibility boundary
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
                                    except Exception as json_err:  # noqa: BLE001  # noqa: BROAD_EXCEPT_OK -- corrupt legacy metadata
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

            compiled_graph = build_rag_graph(
                provider_factory,
                embedder=embedder,
                vector_store=vector_store,
                tenant_store=tenant_store,
                cache_scope=cache_scope,
                provider_api_key=provider_api_key,
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

        compiled_graph = build_rag_graph(
            provider_factory,
            embedder=embedder,
            vector_store=vector_store,
            tenant_store=tenant_store,
            cache_scope=cache_scope,
            provider_api_key=provider_api_key,
        ).compile(
            checkpointer=memory_saver,
        )
        logger.info("Graph compiled with MemorySaver checkpointer")

        yield compiled_graph

    logger.info("Graph context closed")


@asynccontextmanager
async def create_graph(
    db_path: str | None = None,
    provider_factory: LLMProviderFactory = _DEFAULT_PROVIDER_FACTORY,
    *,
    embedder: Embedder | None = None,
    vector_store: VectorStore | None = None,
    tenant_store: TenantRagStore | None = None,
    cache_scope: TenantCacheScope | None = None,
    provider_api_key: str | None = None,
) -> AsyncIterator[Any]:
    """Create a compiled graph with managed checkpoint resources."""
    async with _create_graph(
        db_path,
        provider_factory,
        embedder=embedder,
        vector_store=vector_store,
        tenant_store=tenant_store,
        cache_scope=cache_scope,
        provider_api_key=provider_api_key,
    ) as graph:
        yield graph
