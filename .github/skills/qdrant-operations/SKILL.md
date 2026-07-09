---
name: qdrant-operations
description: Concrete code patterns for Qdrant — client connection, collection creation with dense+sparse vectors, UUID5 deterministic IDs, hybrid search with RRF fusion, and cross-encoder reranking. Use when writing any Qdrant interaction code.
---

# Qdrant Operations Skill

## When to Use

Invoke this skill **before writing any code** that interacts with Qdrant:
- Creating collections
- Inserting/upserting vectors
- Running hybrid search (dense + sparse)
- Implementing RRF (Reciprocal Rank Fusion)
- Adding a reranker (cross-encoder)

---

## 1. Connecting to Qdrant

```python
from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels
import os

# For development (local Docker or in-memory)
client = QdrantClient(host="localhost", port=6333)

# For production (async client)
from qdrant_client import AsyncQdrantClient

async_client = AsyncQdrantClient(
    url=os.getenv("QDRANT_URL", "http://localhost:6333"),
    api_key=os.getenv("QDRANT_API_KEY"),  # optional
)
```

---

## 2. Creating a Collection with Dense + Sparse Vectors

```python
from qdrant_client.http import models as qmodels
import uuid

COLLECTION_NAME = "rag_studio_docs"
DENSE_VECTOR_SIZE = 384  # paraphrase-multilingual-MiniLM-L12-v2 (local ONNX, cached in models/)

async def create_collection(client: AsyncQdrantClient) -> None:
    """Create a Qdrant collection supporting both dense and sparse vectors."""
    if not await client.collection_exists(COLLECTION_NAME):
        await client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config={
                "dense": qmodels.VectorParams(
                    size=DENSE_VECTOR_SIZE,
                    distance=qmodels.Distance.COSINE,
                ),
            },
            sparse_vectors_config={
                "sparse": qmodels.SparseVectorParams(
                    index=qmodels.SparseIndexParams(
                        on_disk=False,
                    ),
                ),
            },
        )
```

---

## 3. UUID5 — Deterministic Point IDs (Avoid Collisions)

```python
import uuid

# Use a fixed namespace UUID for your project
RAG_STUDIO_NAMESPACE = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")

def make_doc_id(filename: str, chunk_index: int) -> str:
    """Generate a deterministic UUID5 for a document chunk.
    
    Args:
        filename: The original file name (e.g., 'report.pdf').
        chunk_index: Zero-based index of the chunk within the document.
    
    Returns:
        A UUID5 string, deterministic and collision-free.
    """
    unique_key = f"{filename}:chunk:{chunk_index}"
    return str(uuid.uuid5(RAG_STUDIO_NAMESPACE, unique_key))
```

**Why UUID5?** Using `uuid.uuid5()` with a namespace + unique key ensures:
- Same input → same ID (idempotent upserts, no duplicates).
- Different documents/chunks → different IDs (no collisions).
- No need to query Qdrant first to find existing IDs.

---

## 4. Upserting Points (Dense + Sparse)

```python
from qdrant_client.http import models as qmodels

async def upsert_chunk(
    client: AsyncQdrantClient,
    filename: str,
    chunk_index: int,
    dense_vector: list[float],
    sparse_vector: dict[str, float],  # {token_id_str: weight}
    payload: dict,
) -> None:
    """Upsert a single chunk with both dense and sparse vectors."""
    point_id = make_doc_id(filename, chunk_index)

    await client.upsert(
        collection_name=COLLECTION_NAME,
        points=[
            qmodels.PointStruct(
                id=point_id,
                vector={
                    "dense": dense_vector,
                    "sparse": sparse_vector,
                },
                payload=payload,
            ),
        ],
    )
```

---

## 5. Hybrid Search with RRF (Reciprocal Rank Fusion)

```python
async def hybrid_search(
    client: AsyncQdrantClient,
    query_dense: list[float],
    query_sparse: dict[str, float],
    limit: int = 10,
    rrf_k: int = 60,
) -> list[qmodels.ScoredPoint]:
    """Perform hybrid search combining dense and sparse results via RRF.

    Args:
        client: AsyncQdrantClient instance.
        query_dense: Dense embedding vector of the query.
        query_sparse: Sparse vector of the query (e.g., from BM25/Splade).
        limit: Number of results to return.
        rrf_k: RRF ranking constant (default 60 per Qdrant docs).

    Returns:
        List of ScoredPoint objects sorted by RRF score (descending).
    """
    # Build prefetch queries for dense and sparse
    prefetch = [
        qmodels.Prefetch(
            query=query_dense,
            using="dense",
            limit=limit * 2,  # oversample for fusion
        ),
        qmodels.Prefetch(
            query=query_sparse,
            using="sparse",
            limit=limit * 2,
        ),
    ]

    results = await client.query_points(
        collection_name=COLLECTION_NAME,
        prefetch=prefetch,
        query=qmodels.FusionQuery(
            fusion=qmodels.Fusion.RRF,  # Reciprocal Rank Fusion
        ),
        limit=limit,
    )

    return results.points
```

---

## 6. Adding a Reranker (Cross-Encoder)

```python
from sentence_transformers import CrossEncoder

# Load once at module level (expensive)
_reranker: CrossEncoder | None = None

def get_reranker() -> CrossEncoder:
    """Lazy-load the cross-encoder reranker model."""
    global _reranker
    if _reranker is None:
        _reranker = CrossEncoder(
            "cross-encoder/ms-marco-MiniLM-L-6-v2",
            max_length=512,
        )
    return _reranker


async def rerank_results(
    query: str,
    candidates: list[qmodels.ScoredPoint],
    top_k: int = 5,
) -> list[dict]:
    """Rerank hybrid search results using a cross-encoder.

    Args:
        query: The original user query string.
        candidates: ScoredPoint results from hybrid_search().
        top_k: Number of top results to return after reranking.

    Returns:
        List of dicts with 'point' and 'rerank_score', sorted by rerank_score desc.
    """
    model = get_reranker()

    # Build (query, document_text) pairs
    pairs = [
        (query, point.payload.get("text", ""))
        for point in candidates
    ]

    scores = model.predict(pairs)  # returns list[float]

    # Combine and sort
    scored = [
        {"point": point, "rerank_score": float(score)}
        for point, score in zip(candidates, scores)
    ]
    scored.sort(key=lambda x: x["rerank_score"], reverse=True)

    return scored[:top_k]
```

---

## 7. Full Hybrid Search Pipeline (End-to-End)

```python
async def full_retrieval_pipeline(
    client: AsyncQdrantClient,
    query_text: str,
    query_dense: list[float],
    query_sparse: dict[str, float],
    top_k: int = 5,
) -> list[dict]:
    """Complete retrieval: hybrid search → RRF → rerank.

    Args:
        client: AsyncQdrantClient.
        query_text: Raw query string (for reranker).
        query_dense: Dense embedding of the query.
        query_sparse: Sparse vector of the query.
        top_k: Final number of results.

    Returns:
        Top-k reranked results as list of dicts with text and score.
    """
    # Step 1: Hybrid search with RRF
    hybrid_results = await hybrid_search(
        client=client,
        query_dense=query_dense,
        query_sparse=query_sparse,
        limit=20,  # retrieve more candidates for reranking
    )

    # Step 2: Rerank with cross-encoder
    reranked = await rerank_results(
        query=query_text,
        candidates=hybrid_results,
        top_k=top_k,
    )

    return reranked
```

---

## Best Practices

1. **Always use UUID5** for point IDs — never auto-generated UUID4 for document chunks.
2. **Oversample in prefetch** (2x-3x limit) before RRF fusion to give the fusion algorithm more candidates.
3. **Batch upserts** — use `client.upsert(points=[...])` with multiple points instead of one-at-a-time.
4. **Lazy-load the reranker** — it's a heavy model, load it once at module level.
5. **Use async client** (`AsyncQdrantClient`) for FastAPI compatibility.
6. **Set `on_disk=False`** for sparse vector index in MVP — trade disk for speed.
