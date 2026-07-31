"""FastAPI router for chat streaming — send_message SSE endpoint.

Implements FR-003 (LangGraph Chat with Semantic Cache) and FR-006 acceptance
criteria:
- AC-003.1-003.5: LangGraph integration with semantic cache
- AC-006.2: SSE streaming message responses (real LangGraph)
- AC-006.3: Source citations from real retrieved docs
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
from typing import Any, AsyncGenerator

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from src.api.dependencies import decrypt_api_key, load_secrets
from src.api.routes.chat_state import (
    _is_placeholder_api_key,
    _load_session_titles,
    _safe_json_value,
    _save_session_title,
    _session_lock,
    _session_messages,
    _session_meta,
)
from src.api.routes.settings import load_settings
from src.api.sanitizer import detect_prompt_injection
from src.graph import run_rag_graph

router = APIRouter(prefix="/api/chat", tags=["chat"])

logger = logging.getLogger(__name__)


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
        # Log with enough detail for diagnosis (provider, model, key presence).
        logger.error(
            "LangGraph pipeline failed (session=%s, provider=%s, model=%s, "
            "has_api_key=%s): %s",
            session_id,
            provider,
            model,
            bool(user_api_key),
            e,
            exc_info=True,
        )
        # Give a more helpful message if the API key looks like a placeholder.
        if user_api_key and _is_placeholder_api_key(user_api_key):
            error_message = (
                "No valid API key configured. "
                "Please set your API key in Settings or the .env file."
            )
        elif not user_api_key:
            error_message = (
                "No API key configured. "
                "Please set your API key in Settings or the .env file."
            )
        else:
            error_message = "An internal error occurred. Please try again."

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

    # Auto-title and message storage: hold lock minimally (RACE-C01 fix).
    auto_title: str | None = None
    async with _session_lock:
        # Auto-title: use first user message to name the session.
        if session_id in _session_meta:
            current_title = str(_session_meta[session_id].get("title", ""))
            saved_titles = await _load_session_titles()
            if current_title == "New Session" and session_id not in saved_titles:
                auto_title = user_content.strip()[:60]
                if len(user_content.strip()) > 60:
                    auto_title += "..."
                _session_meta[session_id]["title"] = auto_title

    # Store messages using BoundedSessionStore (has its own lock internally)
    await _session_messages.append(
        session_id,
        {
            "id": str(uuid.uuid4()),
            "role": "user",
            "content": user_content,
            "created_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    await _session_messages.append(
        session_id,
        {
            "id": message_id,
            "role": "assistant",
            "content": final_answer,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "citations": citations,
        },
    )

    # Persist auto-title outside the lock (I/O).
    if auto_title is not None:
        await _save_session_title(session_id, auto_title)

    # Final event with citations and metadata
    final_payload: dict[str, object] = {
        "done": True,
        "message_id": message_id,
        "full_response": final_answer,
        "citations": _safe_json_value(citations),
        "generated_from": generated_from,
    }
    yield f"data: {json.dumps(final_payload)}\n\n"


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

    # Initialize default session metadata if not present (RACE-C01 fix).
    async with _session_lock:
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

    # Detect placeholder API keys (e.g., 'sk-your-key-here') and warn.
    # The LLM provider will reject these, but an early warning helps
    # diagnose "chat does nothing" issues faster.
    if user_api_key and _is_placeholder_api_key(user_api_key):
        logger.warning(
            "API key for provider '%s' appears to be a placeholder "
            "(value starts with '%s...'). Chat requests will likely fail. "
            "Set a real API key in Settings or the .env file.",
            provider,
            user_api_key[:12],
        )

    # Get the compiled graph from app state
    compiled_graph = getattr(request.app.state, "graph", None)
    if compiled_graph is None:
        raise HTTPException(status_code=500, detail="Graph not initialized")

    # SEC-H01: Detect and sanitize prompt injection in user message
    sanitized_content, injection_flagged = detect_prompt_injection(body.content)
    if injection_flagged:
        logger.warning(
            "Prompt injection flagged in message (session=%s, len=%d)",
            session_id,
            len(body.content),
        )

    return StreamingResponse(
        _sse_stream(
            session_id,
            sanitized_content,
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
