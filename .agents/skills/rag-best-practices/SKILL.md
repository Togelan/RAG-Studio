---
name: rag-best-practices
description: RAG best practices for @dev — chunk size, overlap, metadata, hybrid search weights, reranking strategy, cache invalidation rules. Follow these rules to maximize RAG quality.
---

# RAG Best Practices Skill

## When to Use

Invoke this skill **before implementing any RAG pipeline code**:
- Building a document ingestion pipeline
- Implementing retrieval (dense, sparse, hybrid)
- Setting up reranking
- Configuring caching for RAG responses

---

> **Follow these rules to maximize RAG quality.** Every rule below is derived from empirical RAG benchmarks and production experience.

---

## 1. Chunking Strategy

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| **Chunk size** | `512 tokens` | Sweet spot between context completeness and retrieval precision. Smaller chunks improve recall but lose context; larger chunks preserve context but dilute relevance signals. |
| **Chunk overlap** | `10%` (64 tokens for 512-token chunks) | Ensures no semantic unit is split across chunk boundaries. 10% is sufficient for most text; use 15% for code or highly technical documents. |
| **Chunking method** | `RecursiveCharacterTextSplitter` | Splits recursively on natural separators (`\n\n`, `\n`, `. `, ` `) to avoid mid-sentence breaks. |

```python
from langchain_text_splitters import RecursiveCharacterTextSplitter

splitter = RecursiveCharacterTextSplitter(
    chunk_size=512,
    chunk_overlap=64,  # 10% of 512, rounded to nearest power of 2
    separators=["\n\n", "\n", ". ", "? ", "! ", " ", ""],
    length_function=len,  # use token count in production
)
```

### Chunking Rules

- **Never** split mid-word. Always use a tokenizer-aware splitter.
- **Preserve structure** — keep headings with their content, code blocks intact, and tables together.
- **Add metadata to every chunk**: `source`, `page`, `chunk_index`, `total_chunks`.
- **Minimum chunk size**: discard chunks under 20 tokens (they carry no useful signal).

---

## 2. Metadata Schema

Every chunk stored in Qdrant MUST carry these metadata fields:

| Field | Type | Description | Example |
|-------|------|-------------|---------|
| `source` | `str` | Original file name | `"2024-annual-report.pdf"` |
| `page` | `int` | Page number (1-indexed) | `14` |
| `chunk_index` | `int` | Zero-based chunk index within document | `3` |
| `total_chunks` | `int` | Total chunks for this document | `47` |
| `doc_id` | `str` | UUID5 of the parent document | `"a1b2c3d4-..."` |
| `created_at` | `str` | ISO 8601 timestamp of ingestion | `"2026-06-22T14:30:00Z"` |

```python
metadata = {
    "source": filename,
    "page": page_number,
    "chunk_index": i,
    "total_chunks": len(chunks),
    "doc_id": doc_uuid,
    "created_at": datetime.utcnow().isoformat() + "Z",
}
```

---

## 3. Hybrid Search Configuration

### Dense Vector

- **Model**: `text-embedding-3-small` (OpenAI) or `paraphrase-multilingual-MiniLM-L12-v2` (local).
- **Dimensions**: 384 (`paraphrase-multilingual-MiniLM-L12-v2` local ONNX model, cached).
- **Distance metric**: `Cosine`.

### Sparse Vector (BM25)

- **Model**: `Qdrant/bm25` via FastEmbed.
- **Purpose**: Lexical matching for keyword-heavy queries (dates, names, codes).
- **Weight**: BM25 is excellent for exact term matching; dense is better for semantic similarity.

### RRF (Reciprocal Rank Fusion)

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| **k** | `60` | Standard RRF constant. Higher values (e.g., 100) give more weight to consensus; lower values (e.g., 30) favor top-ranked results. |
| **Dense weight** | `0.7` | Semantic similarity carries more weight than lexical matching for most queries. |
| **Sparse weight** | `0.3` | Lexical matching provides precision for specific terms. |
| **Limit** | `20` candidates | Retrieve 20 candidates before reranking. More candidates = better recall but slower reranking. |

```python
# Hybrid search with RRF
search_results = await client.search(
    collection_name="rag_studio_docs",
    query_vector=("dense", dense_vector),
    query_filter=None,
    limit=20,
    with_vectors=False,
    with_payload=True,
)

# If using multi-vector search
from qdrant_client.http import models

results = await client.search(
    collection_name="rag_studio_docs",
    request=models.SearchRequest(
        vector=models.NamedVector(name="dense", vector=dense_vector),
        limit=10,
    ),
    request=models.SearchRequest(
        vector=models.NamedSparseVector(
            name="sparse",
            vector=models.SparseVector(indices=sparse_indices, values=sparse_values),
        ),
        limit=10,
    ),
)
```

---

## 4. Reranking Strategy

### Cross-Encoder Reranker

- **Model**: `ms-marco-MiniLM-L-6-v2` (default) or `BAAI/bge-reranker-v2-m3` (multilingual).
- **Input**: Top 20 candidates from hybrid search.
- **Output**: Top 5 reranked documents.

```python
from fastembed.rerank.cross_encoder import TextCrossEncoder

reranker = TextCrossEncoder(model_name="ms-marco-MiniLM-L-6-v2")

# Rerank candidates
candidate_texts = [doc.payload["text"] for doc in search_results]
scores = reranker.rerank(query, candidate_texts)

# Take top 5
top_k = 5
reranked = sorted(
    zip(search_results, scores),
    key=lambda x: x[1],
    reverse=True,
)[:top_k]
```

### Reranking Rules

- **Always rerank** hybrid search results before passing to the generator.
- **Top 5 is the sweet spot** — more than 5 documents dilutes the generator's attention; fewer may miss relevant context.
- **Deduplicate** results by `source` + `chunk_index` before reranking.
- **Cache reranker model** at module level (do not reload per query).

---

## 5. Cache Invalidation Rules

### When to Invalidate

| Trigger | Scope | Action |
|---------|-------|--------|
| New document ingested | All queries that could match the new document's topics | Invalidate topic cache |
| Document deleted | All cached answers sourced from that document | Invalidate by `doc_id` |
| Document updated | Same as delete + ingest | Invalidate by `doc_id`, then re-ingest |
| Embedding model changed | Entire cache | Full cache flush |
| Chunking parameters changed | Entire cache | Full cache flush |

### Invalidation Strategy

- Use **TTL + explicit invalidation**:
  - TTL: 1 hour for all cached answers.
  - Explicit: invalidate by `doc_id` on document lifecycle events.
- Cache key format: `{query_hash}:{topic}:{doc_ids_sorted}`
- Use `query_hash` (MD5 of normalized query) to detect semantically identical queries.

```python
import hashlib
import time
from typing import Optional

# Simple in-memory cache with TTL
_cache: dict[str, tuple[float, str]] = {}  # key -> (expiry, answer)

def cache_key(query: str, doc_ids: list[str]) -> str:
    normalized = query.strip().lower()
    query_hash = hashlib.md5(normalized.encode()).hexdigest()[:12]
    doc_ids_sorted = "-".join(sorted(doc_ids))
    return f"{query_hash}:{doc_ids_sorted}"

def cache_set(key: str, answer: str, ttl: int = 3600) -> None:
    _cache[key] = (time.time() + ttl, answer)

def cache_get(key: str) -> Optional[str]:
    entry = _cache.get(key)
    if entry is None:
        return None
    expiry, answer = entry
    if time.time() > expiry:
        del _cache[key]
        return None
    return answer

def invalidate_by_doc_id(doc_id: str) -> int:
    """Remove all cache entries that reference a specific doc_id. Returns count removed."""
    removed = 0
    for key in list(_cache.keys()):
        if doc_id in key:
            del _cache[key]
            removed += 1
    return removed
```

---

## 6. Prompt Template for Generation

```python
RAG_PROMPT_TEMPLATE = """You are a helpful AI assistant. Answer the user's question using ONLY the context provided below.
If the context does not contain enough information to answer, say "I don't have enough information to answer that."

Context:
{context}

Question: {question}

Answer:"""
```

### Prompt Rules

- **Always** include `Context:` before the retrieved documents.
- **Always** include the instruction to say "I don't have enough information" — this reduces hallucinations.
- **Limit context length** to the top 5 chunks (~2560 tokens at 512 tokens/chunk).
- **Cite sources** when possible: append `[Source: {source}, Page {page}]` to the answer.

---

## 7. Quality Checklist

Before merging any RAG pipeline code, verify:

- [ ] Chunk size is 512 tokens with 10% overlap.
- [ ] All chunks carry the required metadata (`source`, `page`, `chunk_index`, `total_chunks`, `doc_id`, `created_at`).
- [ ] Hybrid search uses both dense and sparse vectors with RRF fusion (k=60).
- [ ] Reranker is applied to top 20 candidates, outputting top 5.
- [ ] Cache is invalidated on document create/update/delete.
- [ ] Generator prompt includes the anti-hallucination instruction.
- [ ] UUID5 is used for all Qdrant point IDs.
- [ ] `faithfulness` > 0.7, `context_recall` > 0.8, `answer_relevancy` > 0.7.
