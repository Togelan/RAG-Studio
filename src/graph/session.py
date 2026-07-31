"""Session management helpers for the RAG-Studio chat graph (FR-003).

Provides delete_session() and get_session_metadata() for managing
chat sessions stored in the LangGraph checkpointer (AsyncSqliteSaver/MemorySaver).

AC-003.6: Session deletion must clean up all checkpointed state with no orphans.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from typing import Any

logger = logging.getLogger(__name__)


class SessionPersistenceError(RuntimeError):
    """Raised when persisted session state cannot be safely changed."""


def _checkpoint_messages(checkpoint: object) -> list[object]:
    """Return checkpoint messages only when the persisted shape is valid."""
    if not isinstance(checkpoint, Mapping):
        return []
    channel_values = checkpoint.get("channel_values")
    if not isinstance(channel_values, Mapping):
        return []
    messages = channel_values.get("messages", [])
    if not isinstance(messages, Sequence) or isinstance(messages, (str, bytes)):
        return []
    return list(messages)


async def delete_session(
    thread_id: str,
    *,
    compiled_graph: Any | None = None,
    db_path: str | None = None,
) -> bool:
    """Delete a chat session and all its state from the checkpointer.

    For AsyncSqliteSaver: opens a connection, deletes the thread.
    For MemorySaver: uses the compiled graph's checkpointer.
    Ensures no orphaned state remains (AC-003.6).

    Args:
        thread_id: The session/thread ID to delete.
        compiled_graph: Optional compiled graph with checkpointer.
        db_path: Path to SQLite database (used if compiled_graph is None).

    Returns:
        True if the session was found and deleted, False otherwise.
    """
    if not isinstance(thread_id, str) or not thread_id:
        logger.warning("Refused deletion for an invalid session identifier")
        return False

    # If compiled graph is provided, use its checkpointer directly.
    if compiled_graph is not None:
        checkpointer = getattr(compiled_graph, "checkpointer", None)
        if checkpointer is not None:
            try:
                await checkpointer.adelete_thread(thread_id)
                logger.info("Deleted session thread_id=%s via checkpointer", thread_id)
                return True
            except Exception as exc:  # noqa: BLE001 - checkpointer backends vary
                logger.warning(
                    "Checkpointer delete_thread failed for %s (%s)",
                    thread_id,
                    type(exc).__name__,
                )

    if db_path is None:
        return False

    # Fallback: direct SQLite deletion
    try:
        import aiosqlite

        async with aiosqlite.connect(db_path) as conn:
            cursor = await conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name IN ('checkpoints', 'writes')"
            )
            tables = [row[0] async for row in cursor]
            if "checkpoints" in tables:
                checkpoint_cursor = await conn.execute(
                    "DELETE FROM checkpoints WHERE thread_id = ?",
                    (thread_id,),
                )
                deleted_rows = checkpoint_cursor.rowcount
            else:
                deleted_rows = 0
            if "writes" in tables:
                writes_cursor = await conn.execute(
                    "DELETE FROM writes WHERE thread_id = ?",
                    (thread_id,),
                )
                deleted_rows += writes_cursor.rowcount
            await conn.commit()
            logger.info(
                "Deleted session thread_id=%s from SQLite (db=%s)",
                thread_id,
                db_path,
            )
            return deleted_rows > 0
    except Exception as exc:
        logger.warning(
            "SQLite deletion failed for thread_id=%s (%s)",
            thread_id,
            type(exc).__name__,
        )
        raise SessionPersistenceError(
            "Unable to delete persisted session state"
        ) from exc


async def get_session_metadata(
    thread_id: str,
    *,
    compiled_graph: Any | None = None,
) -> dict[str, Any] | None:
    """Retrieve session metadata from the checkpointer state.

    For a given thread_id, retrieves title, created_at, and message_count
    from the checkpointed state. Used to populate the chat sidebar (AC-003.6).

    Args:
        thread_id: The session/thread ID.
        compiled_graph: Optional compiled graph with checkpointer.

    Returns:
        Dict with keys: id, title, created_at, message_count, or None if
        the session doesn't exist or the checkpointer doesn't support queries.
    """
    if compiled_graph is None:
        return None

    try:
        checkpointer = getattr(compiled_graph, "checkpointer", None)
        if checkpointer is None:
            return None

        config = {"configurable": {"thread_id": thread_id}}

        if hasattr(checkpointer, "aget_tuple"):
            checkpoint_tuple = await checkpointer.aget_tuple(config)
            if checkpoint_tuple:
                checkpoint = checkpoint_tuple.checkpoint
                messages = _checkpoint_messages(checkpoint)

                created_at = (
                    str(checkpoint.get("ts", ""))
                    if isinstance(checkpoint, Mapping)
                    else ""
                )
                message_count = len(messages)

                # Derive title from first user message
                title = "New Session"
                for msg in messages:
                    if getattr(msg, "type", None) == "human":
                        raw_content = getattr(msg, "content", "")
                        content = str(raw_content) if raw_content else ""
                        title = content.strip()[:60]
                        if len(content.strip()) > 60:
                            title += "..."
                        break

                return {
                    "id": thread_id,
                    "title": title,
                    "created_at": created_at,
                    "message_count": message_count,
                }
    except Exception as exc:  # noqa: BLE001 - SQLite adapter boundary
        logger.warning(
            "Failed to get session metadata for thread_id=%s (%s)",
            thread_id,
            type(exc).__name__,
        )

    return None


async def list_all_sessions(
    *,
    compiled_graph: Any | None = None,
    db_path: str = "checkpoints.db",
) -> list[dict[str, Any]]:
    """List all sessions stored in the checkpointer.

    Scans the checkpointer for all thread_ids and returns their metadata.
    Used by the chat sidebar to display all sessions.

    Args:
        compiled_graph: Optional compiled graph with checkpointer.
        db_path: Path to SQLite database (used if compiled_graph is None).

    Returns:
        List of session metadata dicts (may be empty if no sessions exist
        or checkpointer doesn't support listing).
    """
    sessions: list[dict[str, Any]] = []

    try:
        import aiosqlite

        async with aiosqlite.connect(db_path) as conn:
            cursor = await conn.execute(
                "SELECT DISTINCT thread_id FROM checkpoints ORDER BY thread_id"
            )
            thread_ids = [row[0] async for row in cursor]

        for tid in thread_ids:
            meta = await get_session_metadata(tid, compiled_graph=compiled_graph)
            if meta:
                sessions.append(meta)

        logger.info("Listed %d sessions from SQLite", len(sessions))
        return sessions
    except Exception as exc:  # noqa: BLE001 - SQLite adapter boundary
        logger.debug("Could not list sessions from SQLite (%s)", type(exc).__name__)

    return sessions
