"""RAGState TypedDict schema for the RAG-Studio chat graph (FR-003).

Defines the custom state that flows through all 7 LangGraph nodes.
Uses Annotated reducers for accumulating state (messages via add_messages).
"""

from __future__ import annotations

import contextvars
from typing import Annotated, Any, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class RAGState(TypedDict):
    """Custom state for the RAG-Studio chat graph.

    All fields are defined with explicit types. The 'messages' field
    uses `add_messages` reducer to accumulate conversation history across
    graph invocations within the same thread_id (session).
    """

    # Messages (accumulated via add_messages reducer across invocations)
    messages: Annotated[list[BaseMessage], add_messages]

    # Query analysis
    query: str
    intent: str  # "follow_up_question" | "standalone_question" | ""

    # Cache
    cache_hit: bool
    cached_answer: str | None

    # Retrieval
    retrieved_docs: list[dict[str, Any]]  # list of {text, score, metadata}
    reranked_docs: list[dict[str, Any]]

    # Generation
    generated_from: str  # "cache" | "retrieval" | ""
    final_answer: str | None

    # Validation
    faithfulness_score: float  # 0.0–1.0, set by validate node
    validation_passed: bool

    # Metadata
    session_id: str

    # LLM Configuration (from user settings)
    provider: str  # "openai" | "deepseek" | "anthropic" | "ollama"
    model_name: str  # e.g., "gpt-4o-mini", "deepseek-chat"
    temperature: float  # 0.0–2.0
    max_tokens: int  # max tokens for generation
    system_prompt: str  # custom system prompt from settings


# ============================================================
# Context Variable: User API Key (SEC-H02)
# ============================================================
# Stored in a context variable rather than in RunnableConfig or
# RAGState so that LangSmith NEVER traces it and the checkpointer
# NEVER persists it.

_user_api_key_ctx: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "_rag_user_api_key", default=None
)


def get_user_api_key() -> str | None:
    """Get the user API key from the current async context.

    Context vars are NOT traced by LangSmith and NOT persisted by
    the checkpointer (SEC-H02).

    Returns:
        The user's API key, or None if not set.
    """
    return _user_api_key_ctx.get()


def set_user_api_key(key: str | None) -> contextvars.Token[str | None]:
    """Set the user API key in the current async context.

    Returns a Token that should be passed to ``_user_api_key_ctx.reset()``
    to restore the previous value when the graph invocation completes.

    Args:
        key: The user's API key, or None.

    Returns:
        A contextvars Token for restoring the previous value.
    """
    return _user_api_key_ctx.set(key)
