"""Graph invocation, streaming, and result normalization."""  # noqa: SIZE_OK

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Mapping, Sequence
from typing import Any

logger = logging.getLogger(__name__)


class GraphResultError(RuntimeError):
    """Raised when a graph emits a result with an unsafe or invalid shape."""


def _graph_inputs(
    query: str,
    session_id: str,
    user_api_key: str | None,
    *,
    persist_user_api_key: bool = True,
    provider: str,
    model: str,
    temperature: float,
    max_tokens: int,
    system_prompt: str,
    top_k: int,
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
        "provider": provider,
        "model_name": model,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "system_prompt": system_prompt,
        "top_k": top_k,
    }
    if persist_user_api_key:
        initial_state["user_api_key"] = user_api_key
    return config, initial_state


def _normalize_graph_result(result: Any, *, session_id: str) -> dict[str, Any]:
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
    citations: list[dict[str, Any]] = []
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
        citation: dict[str, Any] = {
            "index": index + 1,
            "chunk_text": str(doc.get("text", "")),
            "filename": str(
                metadata.get("filename", metadata.get("source", "unknown"))
            ),
            "chunk_index": str(metadata.get("chunk_index", "?")),
            "score": score,
            "location_unavailable": True,
        }
        start_offset = metadata.get("start_offset")
        end_offset = metadata.get("end_offset")
        if (
            isinstance(start_offset, int)
            and not isinstance(start_offset, bool)
            and isinstance(end_offset, int)
            and not isinstance(end_offset, bool)
            and start_offset <= end_offset
        ):
            citation["start_offset"] = start_offset
            citation["end_offset"] = end_offset
            citation["location_unavailable"] = False
        citations.append(citation)

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


def _stream_chunk_text(message: Any) -> str:
    """Extract text from a LangChain message chunk without stringifying metadata."""
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    if not isinstance(content, Sequence) or isinstance(content, (str, bytes)):
        return ""
    parts: list[str] = []
    for item in content:
        if isinstance(item, str):  # noqa: IF_VARIANT_OK
            parts.append(item)
        elif isinstance(item, Mapping):
            text = item.get("text")
            if isinstance(text, str):
                parts.append(text)
    return "".join(parts)


async def _stream_rag_graph(
    query: str,
    session_id: str,
    user_api_key: str | None = None,
    *,
    persist_user_api_key: bool = True,
    compiled_graph: Any,
    provider: str = "openai",
    model: str = "gpt-4o-mini",
    temperature: float = 1.0,
    max_tokens: int = 2048,
    system_prompt: str = "",
    top_k: int = 5,
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
        persist_user_api_key=persist_user_api_key,
        provider=provider,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        system_prompt=system_prompt,
        top_k=top_k,
    )

    final_state: Any | None = None
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


async def stream_rag_graph(
    query: str,
    session_id: str,
    user_api_key: str | None = None,
    *,
    persist_user_api_key: bool = True,
    compiled_graph: Any,
    provider: str = "openai",
    model: str = "gpt-4o-mini",
    temperature: float = 1.0,
    max_tokens: int = 2048,
    system_prompt: str = "",
    top_k: int = 5,
) -> AsyncIterator[dict[str, Any]]:
    """Yield provider chunks followed by one normalized graph result."""
    async for event in _stream_rag_graph(
        query,
        session_id,
        user_api_key,
        persist_user_api_key=persist_user_api_key,
        compiled_graph=compiled_graph,
        provider=provider,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        system_prompt=system_prompt,
        top_k=top_k,
    ):
        yield event


async def run_rag_graph(
    query: str,
    session_id: str,
    user_api_key: str | None = None,
    *,
    persist_user_api_key: bool = True,
    compiled_graph: Any,
    provider: str = "openai",
    model: str = "gpt-4o-mini",
    temperature: float = 1.0,
    max_tokens: int = 2048,
    system_prompt: str = "",
    top_k: int = 5,
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
        persist_user_api_key=persist_user_api_key,
        provider=provider,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        system_prompt=system_prompt,
        top_k=top_k,
    )
    result = await compiled_graph.ainvoke(initial_state, config)
    return _normalize_graph_result(result, session_id=session_id)
