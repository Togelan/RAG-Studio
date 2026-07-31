"""Shared state and helpers for the chat routers.

Holds the module-level compiled graph holder, in-memory session
metadata/messages stores, session-title persistence helpers, and message
serialization helpers shared by `chat_stream.py`, `session_routes.py`,
and `feedback_routes.py`.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any, cast

from src.api.routes.session_store import BoundedSessionStore

logger = logging.getLogger(__name__)

# ============================================================
# Module-level compiled graph holder (set during startup)
# ============================================================
_compiled_graph: Any = None


def set_graph(graph: Any) -> None:
    """Set the compiled LangGraph graph for use by chat endpoints.

    Called during application startup from the lifespan context manager.

    Args:
        graph: The compiled LangGraph StateGraph instance.
    """
    global _compiled_graph  # noqa: PLW0603
    _compiled_graph = graph


def get_graph() -> Any:
    """Return the compiled graph or raise if not initialized.

    Returns:
        The compiled LangGraph StateGraph instance.

    Raises:
        RuntimeError: If the graph has not been set via set_graph().
    """
    if _compiled_graph is None:
        raise RuntimeError("Graph not initialized. Call set_graph() during startup.")
    return _compiled_graph


def _is_placeholder_api_key(value: str) -> bool:
    """Check if an API key string looks like a placeholder.

    Detects common placeholder patterns like 'sk-your-key-here',
    'your-', 'change-me', 'xxx', etc.

    Args:
        value: The API key string to check.

    Returns:
        True if the value appears to be a placeholder.
    """
    if not value or not value.strip():
        return True
    v = value.strip().lower()
    placeholder_markers = (
        "your-key",
        "your_api_key",
        "change-me",
        "changeme",
        "replace-me",
        "placeholder",
        "xxx",
        "test_key",
        "sk-xxx",
        "sk-your",
        "sk-ant-your",
        "ls__your",
    )
    return any(marker in v for marker in placeholder_markers)


# ============================================================
# Hardcoded grounding instruction (AC-006.7)
# ============================================================
# This is ALWAYS the first SystemMessage and cannot be overridden.
GROUNDING_INSTRUCTION = (
    "You are RAG-Studio. Answer strictly based on the provided context. "
    "If you don't know, say so."
)

# ============================================================
# Lightweight in-memory session metadata store
# ============================================================
# Session titles and creation timestamps are tracked here for the
# sidebar listing. Messages are stored in the LangGraph checkpointer
# (SqliteSaver/MemorySaver) via the graph's state persistence.
# FR-003: session metadata comes from checkpointer + this lightweight store.

_session_meta: dict[str, dict[str, object]] = {}
_session_messages = BoundedSessionStore(max_sessions=50, max_messages_per_session=100)
_session_lock: asyncio.Lock = asyncio.Lock()
# Protects _session_meta from concurrent access across async endpoints.

# ============================================================
# Session Title Persistence (JSON file — survives restarts)
# ============================================================

_session_titles_file: Path | None = None
_session_titles_lock: asyncio.Lock = asyncio.Lock()
# Serializes all access to data/session_titles.json to prevent
# read-modify-write races on concurrent title saves/deletes (RACE-C02 fix).


def _get_session_titles_path() -> Path:
    """Resolve the session titles JSON file path (lazy init).

    Returns:
        Absolute path to data/session_titles.json.
    """
    global _session_titles_file
    if _session_titles_file is None:
        project_root = Path(__file__).resolve().parent.parent.parent.parent
        data_dir = project_root / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        _session_titles_file = data_dir / "session_titles.json"
    return _session_titles_file


async def _load_session_titles() -> dict[str, str]:
    """Load persisted session titles from the JSON file.

    Serialized by _session_titles_lock to prevent stale reads.

    Returns:
        Dict mapping session_id → title. Empty dict if file doesn't exist.
    """
    async with _session_titles_lock:
        titles_path = _get_session_titles_path()
        if not titles_path.exists():
            return {}
        try:
            with open(titles_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return {
                        str(k): str(v)
                        for k, v in cast("dict[str, object]", data).items()
                    }
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to load session titles: %s", e)
    return {}


async def _save_session_title(session_id: str, title: str) -> None:
    """Persist a session title to the JSON file (atomic write, RACE-C02 fix).

    Uses os.replace() for cross-platform atomic replacement:
    write to a temp file, then atomically swap. Combined with
    _session_titles_lock, this prevents lost-update races.

    Args:
        session_id: The session/thread ID.
        title: The title to save.
    """
    async with _session_titles_lock:
        titles_path = _get_session_titles_path()
        titles: dict[str, str] = {}
        if titles_path.exists():
            try:
                with open(titles_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        titles = {
                            str(k): str(v)
                            for k, v in cast("dict[str, object]", data).items()
                        }
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("Failed to load session titles for save: %s", e)
        titles[session_id] = title
        try:
            tmp_path = titles_path.with_suffix(".tmp")
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(titles, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, titles_path)
        except OSError as e:
            logger.warning("Failed to save session title for %s: %s", session_id, e)


async def _delete_session_title(session_id: str) -> None:
    """Remove a session title from the persisted JSON file (atomic write, RACE-C02 fix).

    Uses os.replace() for cross-platform atomic replacement.

    Args:
        session_id: The session/thread ID to remove.
    """
    async with _session_titles_lock:
        titles_path = _get_session_titles_path()
        titles: dict[str, str] = {}
        if titles_path.exists():
            try:
                with open(titles_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        titles = {
                            str(k): str(v)
                            for k, v in cast("dict[str, object]", data).items()
                        }
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("Failed to load session titles for delete: %s", e)
        if session_id in titles:
            del titles[session_id]
            try:
                tmp_path = titles_path.with_suffix(".tmp")
                with open(tmp_path, "w", encoding="utf-8") as f:
                    json.dump(titles, f, ensure_ascii=False, indent=2)
                os.replace(tmp_path, titles_path)
            except OSError as e:
                logger.warning(
                    "Failed to delete session title for %s: %s",
                    session_id,
                    e,
                )


def _get_message_role(msg: object) -> str:
    """Extract role string from a LangChain message object.

    Handles HumanMessage, AIMessage, SystemMessage, and plain dicts.
    """
    msg_type = getattr(msg, "type", "")
    if msg_type == "human":
        return "user"
    if msg_type == "ai":
        return "assistant"
    if msg_type == "system":
        return "system"
    raw_role: str | None = None
    if isinstance(msg, dict):
        raw_role = cast("str | None", cast("dict[str, object]", msg).get("role"))
    else:
        raw_role = cast("str | None", getattr(msg, "role", None))
    if raw_role in ("user", "assistant", "system"):
        return raw_role
    return "unknown"


def _get_message_content(msg: object) -> str:
    """Extract text content from a LangChain message object.

    Handles HumanMessage, AIMessage with str or list content,
    and plain dicts with 'content' key.
    """
    raw: object
    if isinstance(msg, dict):
        raw = cast("dict[str, object]", msg).get("content", "")
    else:
        raw = getattr(msg, "content", "")
    if isinstance(raw, str):
        return raw
    if isinstance(raw, list):
        # Handle multimodal content blocks — extract text parts
        parts: list[str] = []
        for block in cast("list[dict[str, object]]", raw):
            block_type = block.get("type")
            if block_type == "text":
                parts.append(str(block.get("text", "")))
            elif isinstance(block, str):
                parts.append(block)
        return " ".join(parts)
    # Fallback: try str(), catch failures gracefully
    try:
        return str(raw)
    except Exception:
        return f"[{type(raw).__name__}]"


def _safe_json_value(obj: object) -> object:
    """Convert any object to a JSON-serializable value.

    Handles LangChain message objects, dicts with non-serializable
    values, and other edge cases that break json.dumps().
    """
    if obj is None:
        return None
    if isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, (list, tuple)):
        return [_safe_json_value(item) for item in cast("list[object]", obj)]
    if isinstance(obj, dict):
        return {
            str(k): _safe_json_value(v)
            for k, v in cast("dict[object, object]", obj).items()
        }
    # LangChain message objects — extract content
    if hasattr(obj, "content"):
        content = getattr(obj, "content", "")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return [_safe_json_value(c) for c in cast("list[object]", content)]
        return str(content)
    # Fallback: convert to string
    try:
        return str(obj)
    except Exception:
        return f"<{type(obj).__name__}>"
