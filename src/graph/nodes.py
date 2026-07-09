"""LangGraph async node functions for the RAG-Studio chat graph (FR-003).

Seven nodes implementing the full RAG pipeline:
1. analyzer_node     — intent classification (follow_up vs standalone)
2. cache_check_node  — semantic cache lookup in Qdrant
3. retrieve_node     — hybrid search + reranking
4. generate_from_cache_node    — return cached answer (no LLM)
5. generate_from_retrieval_node — LLM generation with citations
6. validate_node     — faithfulness scoring (LLM-as-judge)
7. save_to_cache_node — persist answer to semantic cache
"""

from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from src.graph.state import RAGState
from src.ingestion.embedder import (
    generate_dense_embeddings,
    generate_sparse_embeddings,
)
from src.retrieve.orchestrator import hybrid_search
from src.vector_store.client import get_qdrant_client

logger = logging.getLogger(__name__)

# ============================================================
# Constants
# ============================================================

# Cache Qdrant collection name
CACHE_COLLECTION_NAME = "rag_studio_cache"

# Qdrant namespace UUID for UUID5 deterministic IDs
CACHE_NAMESPACE = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")

# Cache similarity threshold (cosine ≥ 0.92 for a hit)
CACHE_SCORE_THRESHOLD = 0.92

# Dense vector dimension for cache collection
CACHE_VECTOR_SIZE = 384

# Default classifier model (can be overridden via env)
DEFAULT_CLASSIFIER_MODEL = os.getenv("LLM_CLASSIFIER_MODEL", "gpt-4o-mini")

# Hardcoded grounding instruction (AC-006.7, FR-003)
GROUNDING_INSTRUCTION = (
    "You are RAG-Studio. Answer strictly based on the provided context. "
    "If you don't know, say so."
)

# Faithfulness threshold (NFR: > 0.7)
FAITHFULNESS_THRESHOLD = 0.7


# ============================================================
# Cache Collection Helper
# ============================================================


async def ensure_cache_collection_exists() -> None:
    """Create the rag_studio_cache collection if it doesn't exist.

    The cache collection stores dense vectors of QUESTIONS (384-dim, Cosine)
    for semantic similarity matching.
    """
    from qdrant_client.http import models as qmodels

    client = await get_qdrant_client()

    if not await client.collection_exists(CACHE_COLLECTION_NAME):
        logger.info("Creating cache collection '%s'...", CACHE_COLLECTION_NAME)
        await client.create_collection(
            collection_name=CACHE_COLLECTION_NAME,
            vectors_config={
                "dense": qmodels.VectorParams(
                    size=CACHE_VECTOR_SIZE,
                    distance=qmodels.Distance.COSINE,
                ),
            },
        )
        logger.info("Cache collection '%s' created.", CACHE_COLLECTION_NAME)
    else:
        logger.debug("Cache collection '%s' already exists.", CACHE_COLLECTION_NAME)


# ============================================================
# Node 1: Analyzer — Intent Classification
# ============================================================


async def analyzer_node(state: RAGState) -> dict[str, Any]:
    """Classify user intent: 'follow_up_question' or 'standalone_question'.

    A follow-up question references prior conversation context.
    A standalone question is self-contained and needs fresh retrieval.

    AC-003.1: Classification completes in < 500ms using a fast gpt-4o-mini call.

    Args:
        state: Current RAGState with messages history.

    Returns:
        Dict with 'query' and 'intent' keys to merge into state.
    """
    api_key: str | None = state.get("user_api_key")
    provider = state.get("provider", "openai")
    model_name = state.get("model_name", DEFAULT_CLASSIFIER_MODEL)

    # Determine base_url based on provider so the request hits the correct API
    base_url: str | None = None
    if provider == "deepseek":
        base_url = "https://api.deepseek.com/v1"
    elif provider == "anthropic":
        base_url = "https://api.anthropic.com/v1"
    elif provider == "ollama":
        base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
    # For openai, leave as None (default)

    llm = ChatOpenAI(
        model=model_name,
        temperature=0,
        api_key=SecretStr(api_key) if api_key else None,
        base_url=base_url,
    )

    system_prompt = (
        "You are an intent classifier. Analyze the user's latest message.\n"
        "Return EXACTLY ONE WORD:\n"
        '- "follow_up" if the message references prior conversation '
        '(e.g., "tell me more", "what about X", "and then?")\n'
        '- "standalone" if the message is self-contained and does not '
        "rely on chat history."
    )

    messages: list[Any] = [SystemMessage(content=system_prompt)]
    # Include last 3 messages for context (AC-003.1)
    messages.extend(state["messages"][-3:])

    response = await llm.ainvoke(messages)
    content = response.content
    intent_raw = str(content).strip().lower() if isinstance(content, str) else ""

    intent = "follow_up_question" if "follow" in intent_raw else "standalone_question"

    # Extract query from the last user message
    query = ""
    for msg in reversed(state["messages"]):
        if isinstance(msg, HumanMessage):
            query = str(msg.content) if msg.content else ""
            break

    logger.info("Analyzer: intent=%s, query=%.80s", intent, query)

    return {
        "query": query,
        "intent": intent,
    }


# ============================================================
# Node 2: Cache Check — Semantic Cache Lookup
# ============================================================


async def cache_check_node(state: RAGState) -> dict[str, Any]:
    """Check if a semantically similar question has a cached answer.

    Uses Qdrant to search the rag_studio_cache collection for questions
    with cosine similarity ≥ 0.92 (CACHE_SCORE_THRESHOLD).

    AC-003.2: Cache hit path bypasses retrieval + generation for < 500ms total.

    Args:
        state: Current RAGState with query to check.

    Returns:
        Dict with 'cache_hit' and 'cached_answer' keys.
    """
    await ensure_cache_collection_exists()

    client = await get_qdrant_client()

    # Generate dense embedding of the QUESTION using local ONNX model
    query_embeddings = generate_dense_embeddings([state["query"]])
    query_dense = query_embeddings[0]

    try:
        results = await client.query_points(
            collection_name=CACHE_COLLECTION_NAME,
            query=query_dense,
            using="dense",
            limit=1,
            score_threshold=CACHE_SCORE_THRESHOLD,
        )

        if results.points:
            payload = results.points[0].payload or {}
            cached_answer = str(payload.get("answer", ""))
            logger.info(
                "Cache HIT: score=%.3f, query=%.60s",
                results.points[0].score,
                state["query"],
            )
            return {
                "cache_hit": True,
                "cached_answer": cached_answer,
            }
        else:
            logger.info("Cache MISS: query=%.60s", state["query"])
            return {
                "cache_hit": False,
                "cached_answer": None,
            }
    except Exception as e:
        logger.warning("Cache check failed (treating as miss): %s", e)
        return {
            "cache_hit": False,
            "cached_answer": None,
        }


# ============================================================
# Node 3: Retrieve — Hybrid Search + Reranking
# ============================================================


async def retrieve_node(state: RAGState) -> dict[str, Any]:
    """Perform hybrid search + reranking to retrieve relevant documents.

    Uses src.retrieve.orchestrator.hybrid_search() which handles:
    - Dense + sparse parallel search via Qdrant prefetch
    - RRF fusion (k=60)
    - FlashRank cross-encoder reranking → top 5

    AC-003.3: Full retrieval pipeline provides grounded context for generation.

    Args:
        state: Current RAGState with query to search.

    Returns:
        Dict with 'retrieved_docs' list of {text, score, metadata}.
    """
    # Generate embeddings for the query
    query = state["query"]

    # Dense embedding
    dense_embeddings = generate_dense_embeddings([query])
    dense_vector = dense_embeddings[0]

    # Sparse embedding — SparseVector has .indices and .values
    sparse_vectors = generate_sparse_embeddings([query])
    sparse_vector = sparse_vectors[0]
    sparse_indices = list(sparse_vector.indices)
    sparse_values = list(sparse_vector.values)

    logger.info("Retrieve: running hybrid search for query=%.80s", query)
    logger.info("DEBUG retrieve_node QUERY: %s", query)
    logger.info(
        "DEBUG retrieve_node DENSE_VECTOR: dim=%d, first5=%.5s",
        len(dense_vector),
        str(dense_vector[:5]),
    )
    logger.info(
        "DEBUG retrieve_node SPARSE: indices_count=%d, values_first5=%.5s",
        len(sparse_indices),
        str(sparse_values[:5]),
    )

    results = await hybrid_search(
        query=query,
        dense_vector=dense_vector,
        sparse_indices=sparse_indices,
        sparse_values=sparse_values,
        top_k=50,
    )

    logger.info("Retrieve: got %d results", len(results))
    logger.info("DEBUG retrieve_node: raw results count=%d", len(results))
    for i, doc in enumerate(results):
        snippet = str(doc.get("text", ""))[:200]
        rerank_score = doc.get("rerank_score")
        raw_score = doc.get("score", 0)
        if rerank_score is not None:
            score = float(rerank_score)
            score_type = "rerank_score"
        else:
            score = float(raw_score)
            score_type = "raw_score"
        logger.info(
            "DEBUG result[%d]: %s=%.4f, text_preview=%.200s",
            i,
            score_type,
            score,
            snippet,
        )

    return {"retrieved_docs": results}


# ============================================================
# Node 4: Generate from Cache — No LLM Call
# ============================================================


async def generate_from_cache_node(state: RAGState) -> dict[str, Any]:
    """Return the cached answer directly — no LLM call needed.

    AC-003.2: This is the fast path, completing in < 500ms total when
    combined with analyzer + cache_check (no retrieval, no LLM generation).

    Args:
        state: Current RAGState with cached_answer.

    Returns:
        Dict with 'final_answer' and 'generated_from' keys.
    """
    return {
        "final_answer": state["cached_answer"],
        "generated_from": "cache",
        "messages": [AIMessage(content=str(state["cached_answer"] or ""))],
    }


# ============================================================
# Node 5: Generate from Retrieval — LLM Generation with Citations
# ============================================================


async def generate_from_retrieval_node(state: RAGState) -> dict[str, Any]:
    """Generate the final answer using retrieved documents as context.

    AC-003.5: LLM is prompted to output citations inline as [N].
    AC-006.7: Hardcoded grounding instruction is always the first SystemMessage.

    Args:
        state: Current RAGState with retrieved_docs and messages.

    Returns:
        Dict with 'final_answer' and 'generated_from' keys.
    """
    api_key: str | None = state.get("user_api_key")
    provider = state.get("provider", "openai")
    model_name = state.get("model_name", "gpt-4o-mini")
    llm_temperature = state.get("temperature", 0.3)
    system_prompt_text = state.get("system_prompt", "") or GROUNDING_INSTRUCTION

    # Determine base_url based on provider
    base_url: str | None = None
    if provider == "deepseek":
        base_url = "https://api.deepseek.com/v1"
    elif provider == "anthropic":
        base_url = "https://api.anthropic.com/v1"
    elif provider == "ollama":
        base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
    # For openai, leave as None (default)

    llm = ChatOpenAI(
        model=model_name,
        temperature=llm_temperature,
        api_key=SecretStr(api_key) if api_key else None,
        base_url=base_url,
    )

    retrieved_docs: list[dict[str, Any]] = state["retrieved_docs"]

    # Build context from retrieved docs with [N] citation markers
    context_parts: list[str] = []
    for i, doc in enumerate(retrieved_docs):
        source = doc.get("metadata", {}).get("filename", "unknown")
        chunk_idx = doc.get("metadata", {}).get("chunk_index", "?")
        context_parts.append(
            f"[DOC {i + 1}] (source: {source}, chunk #{chunk_idx}): {doc.get('text', '')}"
        )
    context = "\n\n---\n\n".join(context_parts)

    system_prompt = f"""{system_prompt_text}

When quoting or referencing document content, cite sources inline using [N]
where N is the document number from the context below.

CONTEXT:
{context}"""

    messages: list[Any] = [SystemMessage(content=system_prompt)]
    messages.extend(state["messages"])

    response = await llm.ainvoke(messages)

    logger.info(
        "Generate (retrieval): answer length=%d, docs=%d",
        len(str(response.content)) if response.content else 0,
        len(retrieved_docs),
    )

    return {
        "final_answer": response.content,
        "generated_from": "retrieval",
        "messages": [AIMessage(content=str(response.content))],
    }


# ============================================================
# Node 6: Validate — Faithfulness Scoring (LLM-as-Judge)
# ============================================================


async def validate_node(state: RAGState) -> dict[str, Any]:
    """Validate that the generated answer is faithful to the retrieved context.

    Uses LLM-as-judge to score faithfulness (0.0–1.0).
    Cache-generated answers skip validation (score = 1.0).
    NFR threshold: faithfulness > 0.7.

    Args:
        state: Current RAGState with final_answer and retrieved_docs.

    Returns:
        Dict with 'faithfulness_score' and 'validation_passed' keys.
    """
    # Cache-generated answers are pre-validated — skip LLM call
    if state["generated_from"] == "cache":
        logger.info("Validate: cache source, score=1.0 (skipped)")
        return {"faithfulness_score": 1.0, "validation_passed": True}

    # No retrieved docs → nothing to validate against
    retrieved_docs = state.get("retrieved_docs", [])
    if not retrieved_docs:
        logger.info("Validate: no retrieved docs, score=0.0")
        return {"faithfulness_score": 0.0, "validation_passed": False}

    api_key: str | None = state.get("user_api_key")
    provider = state.get("provider", "openai")
    model_name = state.get("model_name", "gpt-4o-mini")

    # Determine base_url based on provider
    base_url: str | None = None
    if provider == "deepseek":
        base_url = "https://api.deepseek.com/v1"
    elif provider == "anthropic":
        base_url = "https://api.anthropic.com/v1"
    elif provider == "ollama":
        base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
    # For openai, leave as None (default)

    llm = ChatOpenAI(
        model=model_name,
        temperature=0,
        api_key=SecretStr(api_key) if api_key else None,
        base_url=base_url,
    )

    # Build context for validation
    context = "\n\n".join(
        f"[DOC {i + 1}]: {doc.get('text', '')}" for i, doc in enumerate(retrieved_docs)
    )

    validation_prompt = f"""You are a faithfulness evaluator. Score whether the ANSWER
is fully grounded in the CONTEXT provided. Return ONLY a float between 0.0 and 1.0:
- 1.0: Every claim in the answer is directly supported by the context.
- 0.7–0.9: Minor unsupported details but mostly grounded.
- 0.4–0.6: Partially supported, significant unsupported claims.
- 0.0–0.3: Mostly or entirely unsupported / hallucinated.

ANSWER:
{state["final_answer"]}

CONTEXT:
{context}"""

    response = await llm.ainvoke([HumanMessage(content=validation_prompt)])

    try:
        score = float(str(response.content).strip() if response.content else "0.5")
        score = max(0.0, min(1.0, score))  # clamp to [0, 1]
    except ValueError, TypeError:
        score = 0.5  # default on parse failure

    validation_passed = score > FAITHFULNESS_THRESHOLD

    logger.info(
        "Validate: score=%.3f, passed=%s, generated_from=%s",
        score,
        validation_passed,
        state["generated_from"],
    )

    return {
        "faithfulness_score": score,
        "validation_passed": validation_passed,
    }


# ============================================================
# Node 7: Save to Cache — Persist Answer to Qdrant
# ============================================================


async def save_to_cache_node(state: RAGState) -> dict[str, Any]:
    """Save newly generated answers to the semantic cache.

    Uses UUID5 deterministic IDs (namespace + normalized query).
    Skips cache-generated answers (already cached).
    Skips when validation fails (don't cache hallucinated answers).
    Embeds the QUESTION (not answer) for future semantic matching.

    Args:
        state: Current RAGState with final_answer and metadata.

    Returns:
        Empty dict (no state changes).
    """
    # Skip if answer was from cache — already stored
    if state["generated_from"] == "cache":
        logger.debug("Save to cache: skipped (already from cache)")
        return {}

    # Skip if validation failed — don't cache hallucinated responses
    if not state.get("validation_passed", False):
        logger.debug("Save to cache: skipped (validation not passed)")
        return {}

    await ensure_cache_collection_exists()

    client = await get_qdrant_client()

    # Generate dense embedding of the QUESTION (same ONNX model)
    query_embeddings = generate_dense_embeddings([state["query"]])
    query_dense = query_embeddings[0]

    # UUID5 deterministic ID: same question → same cache key
    point_id = str(uuid.uuid5(CACHE_NAMESPACE, state["query"].strip().lower()))

    payload: dict[str, object] = {
        "query": state["query"],
        "answer": state["final_answer"],
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "session_id": state["session_id"],
    }

    from qdrant_client.http import models as qmodels

    await client.upsert(
        collection_name=CACHE_COLLECTION_NAME,
        points=[
            qmodels.PointStruct(
                id=point_id,
                vector={"dense": query_dense},
                payload=payload,
            )
        ],
    )

    logger.info(
        "Save to cache: point_id=%s, query=%.60s",
        point_id,
        state["query"],
    )

    return {}
