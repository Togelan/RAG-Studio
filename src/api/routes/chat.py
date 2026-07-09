"""FastAPI router for chat endpoints — messaging and feedback.

Implements FR-003 (LangGraph Chat with Semantic Cache) and FR-006 acceptance criteria:
- AC-003.1-003.5: LangGraph integration with semantic cache
- AC-006.2: SSE streaming message responses (real LangGraph)
- AC-006.3: Source citations from real retrieved docs
- AC-006.4: Message feedback (like/dislike) with JSONL persistence
- AC-006.7: Adversarial prompt robustness (grounding instruction)
- AC-006.8: Input sanitization — max length enforcement
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncGenerator, cast

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from src.api.dependencies import decrypt_api_key, load_secrets
from src.api.routes.settings import load_settings
from src.graph import (
    run_rag_graph,
)
from src.graph.session import delete_session as delete_graph_session
from src.graph.session import list_all_sessions

router = APIRouter(prefix="/api/chat", tags=["chat"])

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
_session_messages: dict[str, list[dict[str, object]]] = {}

# ============================================================
# Session Title Persistence (JSON file — survives restarts)
# ============================================================

_session_titles_file: Path | None = None


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


def _load_session_titles() -> dict[str, str]:
    """Load persisted session titles from the JSON file.

    Returns:
        Dict mapping session_id → title. Empty dict if file doesn't exist.
    """
    titles_path = _get_session_titles_path()
    if not titles_path.exists():
        return {}
    try:
        with open(titles_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return {
                    str(k): str(v) for k, v in cast("dict[str, object]", data).items()
                }
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to load session titles: %s", e)
    return {}


def _save_session_title(session_id: str, title: str) -> None:
    """Persist a session title to the JSON file.

    Args:
        session_id: The session/thread ID.
        title: The title to save.
    """
    titles = _load_session_titles()
    titles[session_id] = title
    try:
        titles_path = _get_session_titles_path()
        with open(titles_path, "w", encoding="utf-8") as f:
            json.dump(titles, f, ensure_ascii=False, indent=2)
    except OSError as e:
        logger.warning("Failed to save session title for %s: %s", session_id, e)


def _delete_session_title(session_id: str) -> None:
    """Remove a session title from the persisted JSON file.

    Args:
        session_id: The session/thread ID to remove.
    """
    titles = _load_session_titles()
    if session_id in titles:
        del titles[session_id]
        try:
            titles_path = _get_session_titles_path()
            with open(titles_path, "w", encoding="utf-8") as f:
                json.dump(titles, f, ensure_ascii=False, indent=2)
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


# ============================================================
# Pydantic Models
# ============================================================


class MessageSend(BaseModel):
    """Request schema for sending a chat message."""

    content: str = Field(
        ...,
        description="The user's message content.",
        min_length=1,
        max_length=10000,
    )
    session_id: str | None = Field(
        default=None,
        description="Optional session ID. Defaults to 'default'.",
        max_length=200,
    )


class FeedbackSubmit(BaseModel):
    """Request schema for submitting message feedback."""

    session_id: str = Field(..., description="Session containing the message.")
    message_id: str = Field(..., description="ID of the message receiving feedback.")
    feedback: str = Field(
        ...,
        pattern=r"^(positive|negative)$",
        description="Feedback type: 'positive' or 'negative'.",
    )
    reason: str | None = Field(
        default=None,
        description="Optional reason for negative feedback.",
        max_length=1000,
    )


# ============================================================
# LangGraph SSE Stream (FR-003 — real generation with citations)
# ============================================================


def _tokenize_response(text: str) -> list[str]:
    """Split a response string into word-level tokens for streaming.

    Args:
        text: The full response text.

    Returns:
        List of token strings (words + whitespace).
    """
    tokens: list[str] = []
    current = ""
    for ch in text:
        current += ch
        if ch in (" ", "\n"):
            tokens.append(current)
            current = ""
    if current:
        tokens.append(current)
    return tokens


async def _sse_stream(
    session_id: str,
    user_content: str,
    user_api_key: str | None = None,
    *,
    compiled_graph: Any,
    provider: str = "openai",
    model: str = "gpt-4o-mini",
    temperature: float = 1.0,
    max_tokens: int = 2048,
    system_prompt: str = "",
) -> AsyncGenerator[str, None]:
    """Generate a Server-Sent Events stream using the real LangGraph pipeline.

    Calls run_rag_graph() which executes the full 7-node graph:
    analyzer → cache_check → (cache|retrieve) → generate → validate → save_to_cache.

    Streams the final_answer as word-level SSE tokens for realistic feel.
    Includes real citations from retrieved_docs in the final event.

    Args:
        session_id: The session ID (used as thread_id for state isolation).
        user_content: The user's message content.
        user_api_key: Optional API key for LLM calls (from user settings).
        compiled_graph: The compiled LangGraph graph.
        provider: LLM provider (openai, deepseek, anthropic, ollama).
        model: Model name for generation.
        temperature: Temperature for LLM generation.
        max_tokens: Maximum tokens for generation.
        system_prompt: Custom system prompt from settings.

    Yields:
        SSE-formatted strings.
    """
    message_id = str(uuid.uuid4())

    # Send initial event to establish stream
    yield "event: start\ndata: {}\n\n"

    # Run the LangGraph pipeline (AC-003.1 through AC-003.5)
    result: dict[str, Any] = {}
    error_message: str | None = None

    try:
        result = await run_rag_graph(
            query=user_content,
            session_id=session_id,
            user_api_key=user_api_key,
            compiled_graph=compiled_graph,
            provider=provider,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            system_prompt=system_prompt,
        )
    except Exception as e:
        logger.error("LangGraph pipeline failed: %s", e, exc_info=True)
        error_message = (
            f"I'm sorry, an error occurred while processing your question: {e}"
        )

    final_answer = error_message or str(result.get("final_answer", ""))
    citations = result.get("citations", [])
    generated_from = str(result.get("generated_from", ""))

    # Stream tokens word-by-word for realistic feel
    tokens = _tokenize_response(final_answer)
    for i, token in enumerate(tokens):
        payload: dict[str, object] = {
            "token": token,
            "index": i,
            "message_id": message_id,
        }
        yield f"data: {json.dumps(payload)}\n\n"
        # Small delay for streaming cadence
        await asyncio.sleep(0.015)

    # Auto-title: use first user message to name the session.
    # Only applies if the title is still "New Session" AND the user hasn't
    # previously renamed it (check persisted titles to avoid overwriting).
    if session_id in _session_meta:
        current_title = str(_session_meta[session_id].get("title", ""))
        saved_titles = _load_session_titles()
        # Don't auto-title if user has saved a custom title for this session
        if current_title == "New Session" and session_id not in saved_titles:
            title = user_content.strip()[:60]
            if len(user_content.strip()) > 60:
                title += "..."
            _session_meta[session_id]["title"] = title
            _save_session_title(session_id, title)

    # Store messages in-memory (lightweight cache alongside checkpointer)
    if session_id not in _session_messages:
        _session_messages[session_id] = []
    _session_messages[session_id].append(
        {
            "id": str(uuid.uuid4()),
            "role": "user",
            "content": user_content,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    _session_messages[session_id].append(
        {
            "id": message_id,
            "role": "assistant",
            "content": final_answer,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "citations": citations,
        }
    )

    # Final event with citations and metadata
    final_payload: dict[str, object] = {
        "done": True,
        "message_id": message_id,
        "full_response": final_answer,
        "citations": _safe_json_value(citations),
        "generated_from": generated_from,
    }
    yield f"data: {json.dumps(final_payload)}\n\n"


# ============================================================
# JSON-safe serialization helper (BUG — HumanMessage fix)
# ============================================================


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


# ============================================================
# Session Management Endpoints
# ============================================================


@router.post("/send")
async def send_message(
    body: MessageSend,
    request: Request,
) -> StreamingResponse:
    """Send a message and receive a streaming response via SSE.

    FR-003 / AC-003.1-003.5: Uses the real LangGraph pipeline
    (analyzer → cache_check → retrieve → generate → validate → save_to_cache).

    AC-006.2: Token-by-token streaming of the generated answer.

    Uses a default session_id internally — no session management required.

    Args:
        body: The message content.
        request: FastAPI request (for extracting API key header).

    Returns:
        Server-Sent Events stream with token data events.
    """
    # Use session_id from body or default
    session_id = body.session_id or "default"

    # Initialize default session metadata if not present
    if session_id not in _session_meta:
        _session_meta[session_id] = {
            "id": session_id,
            "title": "Chat",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

    # Extract user API key from header
    user_api_key: str | None = request.headers.get("X-API-Key")

    # Load settings from the encrypted settings store
    settings_data = load_settings()
    provider = str(settings_data.get("provider", "openai"))
    model = str(settings_data.get("model", "gpt-4o-mini"))
    temperature = float(settings_data.get("temperature", 1.0))
    max_tokens_val = int(settings_data.get("max_tokens", 2048))
    system_prompt_val = str(settings_data.get("system_prompt", ""))

    # Priority 1: Load decrypted API key from secrets store (user-saved keys).
    # The outer Fernet layer is decrypted by load_secrets(), but each
    # individual key value was encrypted separately by validate_api_key().
    # We must decrypt the inner value to get the real API key.
    if not user_api_key:
        secrets = load_secrets()
        provider_key = f"{provider}_api_key"
        encrypted_key = secrets.get(provider_key)
        if encrypted_key:
            user_api_key = decrypt_api_key(encrypted_key)

    # Priority 2: Fall back to environment variable (generic OPENAI_API_KEY
    # or provider-specific like DEEPSEEK_API_KEY).
    if not user_api_key:
        env_key_name = f"{provider.upper()}_API_KEY"
        user_api_key = os.getenv(env_key_name) or os.getenv("OPENAI_API_KEY")

    # Get the compiled graph from app state
    compiled_graph = getattr(request.app.state, "graph", None)
    if compiled_graph is None:
        raise HTTPException(status_code=500, detail="Graph not initialized")

    return StreamingResponse(
        _sse_stream(
            session_id,
            body.content,
            user_api_key=user_api_key,
            compiled_graph=compiled_graph,
            provider=provider,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens_val,
            system_prompt=system_prompt_val,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/feedback", status_code=201)
async def submit_feedback(
    body: FeedbackSubmit,
) -> dict[str, str]:
    """Submit feedback (like/dislike) for an assistant message.

    Feedback is stored in ~/.rag-studio/feedback.jsonl for future analysis.

    Args:
        body: Feedback details including session_id, message_id, and feedback type.

    Returns:
        Confirmation message.
    """
    # Determine feedback file path
    feedback_dir = Path.home() / ".rag-studio"
    feedback_dir.mkdir(parents=True, exist_ok=True)
    feedback_path = feedback_dir / "feedback.jsonl"

    record: dict[str, object] = {
        "session_id": body.session_id,
        "message_id": body.message_id,
        "feedback": body.feedback,
        "reason": body.reason,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    with open(feedback_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

    logger.info(
        "Feedback recorded: session=%s, message=%s, feedback=%s",
        body.session_id,
        body.message_id,
        body.feedback,
    )
    return {"status": "saved", "feedback": body.feedback}


# ============================================================
# Pydantic Models for Session Management
# ============================================================


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


# ============================================================
# Session Management Endpoints (FR-006 AC-006.1)
# ============================================================


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
    #    Also load persisted session titles from JSON file so renames survive.
    saved_titles = _load_session_titles()
    try:
        # Resolve checkpoints path relative to project root
        # __file__ → src/api/routes/chat.py → parent x4 → project root
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
                # Prefer persisted title over auto-derived (first message) title
                if sid in saved_titles:
                    s["title"] = saved_titles[sid]
                result.append(dict(s))
                # Populate in-memory _session_meta so subsequent requests
                # (get_session_messages, rename, delete) can find the session
                if sid not in _session_meta:
                    _session_meta[sid] = {
                        "id": sid,
                        "title": s.get("title", "New Session"),
                        "created_at": s.get("created_at", ""),
                    }
    except Exception as e:
        logger.warning("Failed to list sessions from checkpointer: %s", e)

    # 2. Merge in-memory sessions not already in the checkpointer list.
    #    This covers newly created sessions that haven't sent a message yet.
    for sid, meta in _session_meta.items():
        if sid not in seen_ids:
            entry: dict[str, object] = dict(meta)
            entry["message_count"] = len(_session_messages.get(sid, []))
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

    _session_meta[session_id] = {
        "id": session_id,
        "title": title,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _session_messages[session_id] = []

    # Persist title to disk so it survives restarts
    if title != "New Session":
        _save_session_title(session_id, title)

    return dict(_session_meta[session_id])


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
    if session_id == "default":
        # Reset default session instead of deleting
        _session_messages["default"] = []
        _session_meta["default"]["title"] = "Chat"
        return {"status": "cleared", "session_id": session_id}

    if session_id not in _session_meta:
        raise HTTPException(status_code=404, detail="Session not found")

    _session_meta.pop(session_id, None)
    _session_messages.pop(session_id, None)

    # Also clean up persistent checkpointer state and saved title
    _delete_session_title(session_id)

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
    if session_id not in _session_meta:
        raise HTTPException(status_code=404, detail="Session not found")

    _session_meta[session_id]["title"] = body.title.strip()[:200]

    # Persist title to disk so renames survive restarts
    _save_session_title(session_id, str(_session_meta[session_id]["title"]))

    return dict(_session_meta[session_id])


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
    cached = _session_messages.get(session_id)
    if cached:
        return cached

    # Check if session exists in meta (could be from checkpointer via list_sessions)
    if session_id not in _session_meta:
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

                # Cache for next request
                _session_messages[session_id] = result
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
    if session_id not in _session_meta:
        raise HTTPException(status_code=404, detail="Session not found")

    _session_messages[session_id] = []
    return {"status": "cleared", "session_id": session_id}
