"""RAGState TypedDict schema for the RAG-Studio chat graph (FR-003).

Defines the custom state that flows through all 7 LangGraph nodes.
Uses Annotated reducers for accumulating state (messages via add_messages).
"""

from __future__ import annotations

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
    user_api_key: str | None

    # LLM Configuration (from user settings)
    provider: str  # "openai" | "deepseek" | "anthropic" | "ollama"
    model_name: str  # e.g., "gpt-4o-mini", "deepseek-chat"
    temperature: float  # 0.0–2.0
    max_tokens: int  # max tokens for generation
    system_prompt: str  # custom system prompt from settings
