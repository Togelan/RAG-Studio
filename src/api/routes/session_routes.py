"""FastAPI router for chat session management (FR-006 AC-006.1).

Session CRUD endpoints: create, list, rename, delete sessions, and
retrieve/clear session messages.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from src.api.routes.chat_state import (
    _delete_session_title,
    _get_message_content,
    _get_message_role,
    _load_session_titles,
    _save_session_title,
    _session_lock,
    _session_messages,
    _session_meta,
    get_graph,
)
from src.graph.session import delete_session as delete_graph_session
from src.graph.session import list_all_sessions

router = APIRouter(prefix="/api/chat", tags=["chat"])

logger = logging.getLogger(__name__)


class SessionCreate(BaseModel):
    """Request schema for creating a new chat session."""

    title: str | None = Field(
        default=None,
        description="Optional initial title. Defaults to 'New Session'.",
        max_length=200,
    )


class SessionRename(BaseModel):
    """Request schema for renaming a session."""

    title: str = Field(
        ...,
        description="New title for the session.",
        min_length=1,
        max_length=200,
    )


@router.get("/sessions")
async def list_sessions() -> list[dict[str, object]]:
    """List all chat sessions with metadata.

    Merges persistent checkpointer data (survives restarts) with in-memory
    sessions (newly created, not yet persisted). Checkpointer data takes
    precedence for sessions that exist in both sources.

    Returns:
        List of session objects with id, title, created_at, message_count.
    """
    # Collect session IDs seen from the checkpointer
    seen_ids: set[str] = set()
    result: list[dict[str, object]] = []

    # 1. Load persistent sessions from the checkpointer (BUG 2 fix)
    saved_titles = await _load_session_titles()
    try:
        project_root = Path(__file__).resolve().parent.parent.parent.parent
        checkpoints_db = str(project_root / "data" / "checkpoints" / "checkpoints.db")
        checkpoint_sessions = await list_all_sessions(
            compiled_graph=get_graph(),
            db_path=checkpoints_db,
        )
        for s in checkpoint_sessions:
            sid = str(s.get("id", ""))
            if sid:
                seen_ids.add(sid)
                if sid in saved_titles:
                    s["title"] = saved_titles[sid]
                result.append({**s})
                # Populate in-memory _session_meta under lock (RACE-C01 fix).
                async with _session_lock:
                    if sid not in _session_meta:
                        _session_meta[sid] = {
                            "id": sid,
                            "title": s.get("title", "New Session"),
                            "created_at": s.get("created_at", ""),
                        }
    except Exception as e:
        logger.warning("Failed to list sessions from checkpointer: %s", e)

    # 2. Snapshot in-memory sessions under lock to avoid iteration errors (RACE-C01 fix).
    async with _session_lock:
        meta_snapshot = {**_session_meta}
    messages_snapshot = await _session_messages.items_snapshot()

    for sid, meta in meta_snapshot.items():
        if sid not in seen_ids:
            entry: dict[str, object] = {**meta}
            entry["message_count"] = len(messages_snapshot.get(sid, []))
            result.append(entry)

    # Sort by created_at descending
    result.sort(key=lambda s: str(s.get("created_at", "")), reverse=True)
    return result


@router.post("/sessions", status_code=201)
async def create_session(
    body: SessionCreate | None = None,
) -> dict[str, object]:
    """Create a new chat session.

    Args:
        body: Optional session creation data with title.

    Returns:
        The created session metadata.
    """
    session_id = str(uuid.uuid4())
    title = (body.title if body and body.title else "New Session").strip()[
        :200
    ] or "New Session"

    async with _session_lock:
        _session_meta[session_id] = {
            "id": session_id,
            "title": title,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        result: dict[str, object] = {**_session_meta[session_id]}
    await _session_messages.put(session_id, [])

    # Persist title to disk so it survives restarts
    if title != "New Session":
        await _save_session_title(session_id, title)

    return result


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str) -> dict[str, str]:
    """Delete a chat session and all its messages.

    Args:
        session_id: The session ID to delete.

    Returns:
        Confirmation message.

    Raises:
        HTTPException: 404 if session not found.
    """
    async with _session_lock:
        if session_id == "default":
            _session_meta.setdefault(
                "default",
                {
                    "id": "default",
                    "title": "Chat",
                    "created_at": datetime.now(timezone.utc).isoformat(),
                },
            )["title"] = "Chat"
        elif session_id not in _session_meta:
            raise HTTPException(status_code=404, detail="Session not found")

        if session_id != "default":
            _session_meta.pop(session_id, None)
    if session_id == "default":
        await _session_messages.put(session_id, [])
    else:
        await _session_messages.pop(session_id)

    # Also clean up persistent checkpointer state and saved title
    await _delete_session_title(session_id)

    # Also clean up persistent checkpointer state (BUG 2 fix)
    try:
        await delete_graph_session(
            session_id,
            compiled_graph=get_graph(),
        )
    except Exception as e:
        logger.warning("Failed to delete session from checkpointer: %s", e)

    return {"status": "deleted", "session_id": session_id}


@router.patch("/sessions/{session_id}")
async def rename_session(
    session_id: str,
    body: SessionRename,
) -> dict[str, object]:
    """Rename a chat session.

    Args:
        session_id: The session ID to rename.
        body: New title data.

    Returns:
        Updated session metadata.

    Raises:
        HTTPException: 404 if session not found.
    """
    async with _session_lock:
        if session_id not in _session_meta:
            raise HTTPException(status_code=404, detail="Session not found")

        _session_meta[session_id]["title"] = body.title.strip()[:200]
        new_title = str(_session_meta[session_id]["title"])
        result: dict[str, object] = {**_session_meta[session_id]}

    # Persist title to disk so renames survive restarts
    await _save_session_title(session_id, new_title)

    return result


@router.get("/sessions/{session_id}/messages")
async def get_session_messages(
    session_id: str,
    request: Request,
) -> list[dict[str, object]]:
    """Get all messages for a session.

    Loads from in-memory cache first, then falls back to the checkpointer
    so messages survive server restarts.

    Args:
        session_id: The session ID.
        request: FastAPI request (for accessing app.state.graph).

    Returns:
        List of message objects.

    Raises:
        HTTPException: 404 if session not found.
    """
    # Try in-memory cache first (fast path)
    cached = await _session_messages.get(session_id)
    async with _session_lock:
        session_exists = session_id in _session_meta
    if cached:
        return cached

    # Check if session exists in meta (could be from checkpointer via list_sessions)
    if not session_exists:
        raise HTTPException(status_code=404, detail="Session not found")

    # Fallback: load messages from the checkpointer
    try:
        compiled_graph = getattr(request.app.state, "graph", None)
        if compiled_graph is None:
            return []

        checkpointer = getattr(compiled_graph, "checkpointer", None)
        if checkpointer is None:
            return []

        config = {"configurable": {"thread_id": session_id}}

        if hasattr(checkpointer, "aget_tuple"):
            checkpoint_tuple = await checkpointer.aget_tuple(config)
            if checkpoint_tuple:
                checkpoint = checkpoint_tuple.checkpoint
                state: dict[str, Any] = (
                    checkpoint.get("channel_values", {})
                    if isinstance(checkpoint.get("channel_values"), dict)
                    else {}
                )
                raw_messages: list[object] = (
                    state.get("messages", [])
                    if isinstance(state.get("messages"), list)
                    else []
                )

                # Convert LangChain messages to plain dicts for JSON serialization
                result: list[dict[str, object]] = []
                for msg in raw_messages:
                    msg_dict: dict[str, object] = {
                        "id": str(uuid.uuid4()),
                        "role": _get_message_role(msg),
                        "content": _get_message_content(msg),
                        "created_at": "",
                    }
                    result.append(msg_dict)

                # Cache for next request.
                await _session_messages.put(session_id, result)
                return result
    except Exception as e:
        logger.warning(
            "Failed to load messages from checkpointer for session %s: %s",
            session_id,
            e,
        )

    return []


@router.delete("/sessions/{session_id}/messages")
async def clear_session_messages(session_id: str) -> dict[str, str]:
    """Clear all messages from a session.

    Args:
        session_id: The session ID to clear.

    Returns:
        Confirmation message.

    Raises:
        HTTPException: 404 if session not found.
    """
    async with _session_lock:
        if session_id not in _session_meta:
            raise HTTPException(status_code=404, detail="Session not found")

    await _session_messages.put(session_id, [])
    try:
        await delete_graph_session(
            session_id,
            compiled_graph=get_graph(),
        )
    except Exception as e:
        logger.warning("Failed to clear checkpointed session %s: %s", session_id, e)
    return {"status": "cleared", "session_id": session_id}
