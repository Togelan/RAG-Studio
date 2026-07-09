"""Session management helpers for the RAG-Studio chat graph (FR-003).

Provides delete_session() and get_session_metadata() for managing
chat sessions stored in the LangGraph checkpointer (AsyncSqliteSaver/MemorySaver).

AC-003.6: Session deletion must clean up all checkpointed state with no orphans.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


async def delete_session(
    thread_id: str,
    *,
    compiled_graph: Any | None = None,
    db_path: str = "checkpoints.db",
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
    # If compiled graph is provided, use its checkpointer directly
    if compiled_graph is not None:
        checkpointer = getattr(compiled_graph, "checkpointer", None)
        if checkpointer is not None:
            try:
                await checkpointer.adelete_thread(thread_id)
                logger.info("Deleted session thread_id=%s via checkpointer", thread_id)
                return True
            except Exception as e:
                logger.warning(
                    "Checkpointer delete_thread failed for %s: %s",
                    thread_id,
                    e,
                )

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
                await conn.execute(
                    "DELETE FROM checkpoints WHERE thread_id = ?",
                    (thread_id,),
                )
            if "writes" in tables:
                await conn.execute(
                    "DELETE FROM writes WHERE thread_id = ?",
                    (thread_id,),
                )
            await conn.commit()
            logger.info(
                "Deleted session thread_id=%s from SQLite (db=%s)",
                thread_id,
                db_path,
            )
            return True
    except Exception as e:
        logger.warning("SQLite deletion failed for thread_id=%s: %s", thread_id, e)

    return False


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
                state: dict[str, Any] = (
                    checkpoint.get("channel_values", {})
                    if isinstance(checkpoint.get("channel_values"), dict)
                    else {}
                )
                raw_messages = state.get("messages", [])
                messages: list[Any] = (
                    raw_messages if isinstance(raw_messages, list) else []
                )

                created_at = str(checkpoint.get("ts", ""))
                message_count = len(messages)

                # Derive title from first user message
                title = "New Session"
                for msg in messages:
                    if hasattr(msg, "type") and msg.type == "human":
                        content = str(msg.content) if msg.content else ""
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
    except Exception as e:
        logger.warning(
            "Failed to get session metadata for thread_id=%s: %s",
            thread_id,
            e,
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
    except Exception as e:
        logger.debug("Could not list sessions from SQLite: %s", e)

    return sessions
