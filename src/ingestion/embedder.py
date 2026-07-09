"""Embedding generation — dense (ONNX) + sparse (BM25) via fastembed.

Uses pre-cached models from data/models/fastembed_cache/:
- Dense: sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2 (384-dim, ONNX)
- Sparse: Qdrant/bm25 (BM25 tokenizer)

All embeddings are 100% local — no external API calls.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, cast

from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models as qmodels

logger = logging.getLogger(__name__)

# Collection name
COLLECTION_NAME = "rag_studio_docs"

# Dense vector dimensions
DENSE_VECTOR_SIZE = 384

# Qdrant namespace UUID for UUID5 deterministic IDs
RAG_STUDIO_NAMESPACE_UUID = "6ba7b810-9dad-11d1-80b4-00c04fd430c8"

# Path to the fastembed cache directory (relative to project root)
_FASTEMBED_CACHE_DIR = os.getenv(
    "FASTEMBED_CACHE_PATH",
    str(
        Path(__file__).resolve().parent.parent.parent
        / "data"
        / "models"
        / "fastembed_cache"
    ),
)

# Module-level lazy-loaded embedding models
_dense_model: Any = None
_sparse_model: Any = None


def _get_cache_dir() -> str:
    """Return the fastembed cache directory path.

    Returns:
        Absolute path to the models/fastembed_cache/ directory.
    """
    return _FASTEMBED_CACHE_DIR


def _get_dense_model() -> Any:
    """Lazy-load the dense embedding model (ONNX, 384-dim).

    Returns:
        TextEmbedding instance for paraphrase-multilingual-MiniLM-L12-v2.
    """
    global _dense_model
    if _dense_model is None:
        from fastembed import TextEmbedding

        cache_dir = _get_cache_dir()
        logger.info(
            "Loading dense embedding model: paraphrase-multilingual-MiniLM-L12-v2 "
            "(cache: %s)",
            cache_dir,
        )
        _dense_model = TextEmbedding(
            model_name="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
            cache_dir=cache_dir,
        )
        logger.info("Dense embedding model loaded.")
    return _dense_model


def _get_sparse_model() -> Any:
    """Lazy-load the sparse embedding model (BM25).

    Returns:
        SparseTextEmbedding instance for Qdrant/bm25.
    """
    global _sparse_model
    if _sparse_model is None:
        from fastembed import SparseTextEmbedding

        cache_dir = _get_cache_dir()
        logger.info(
            "Loading sparse embedding model: Qdrant/bm25 (cache: %s)",
            cache_dir,
        )
        _sparse_model = SparseTextEmbedding(
            model_name="Qdrant/bm25",
            cache_dir=cache_dir,
        )
        logger.info("Sparse embedding model loaded.")
    return _sparse_model


async def ensure_collection_exists(client: AsyncQdrantClient) -> None:
    """Create the rag_studio_docs collection if it doesn't exist.

    The collection supports:
    - Dense vectors (384-dim, Cosine distance)
    - Sparse vectors (BM25 index)

    Args:
        client: AsyncQdrantClient instance.
    """
    if not await client.collection_exists(COLLECTION_NAME):
        logger.info("Creating collection '%s'...", COLLECTION_NAME)
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
        logger.info("Collection '%s' created.", COLLECTION_NAME)
    else:
        logger.debug("Collection '%s' already exists.", COLLECTION_NAME)


def make_doc_id(filename: str, chunk_index: int) -> str:
    """Generate a deterministic UUID5 for a document chunk.

    Uses uuid.uuid5() with namespace 6ba7b810-9dad-11d1-80b4-00c04fd430c8
    and key '{filename}:chunk:{chunk_index}'.

    Args:
        filename: Original filename (e.g., 'report.pdf').
        chunk_index: Zero-based index of the chunk within the document.

    Returns:
        UUID5 string, deterministic and collision-free.
    """
    import uuid

    namespace = uuid.UUID(RAG_STUDIO_NAMESPACE_UUID)
    unique_key = f"{filename}:chunk:{chunk_index}"
    return str(uuid.uuid5(namespace, unique_key))


def make_document_doc_id(filename: str) -> str:
    """Generate a deterministic UUID5 for the parent document.

    Uses the same namespace with key '{filename}:doc'.

    Args:
        filename: Original filename.

    Returns:
        UUID5 string for the document.
    """
    import uuid

    namespace = uuid.UUID(RAG_STUDIO_NAMESPACE_UUID)
    return str(uuid.uuid5(namespace, f"{filename}:doc"))


def generate_dense_embeddings(chunks: list[str]) -> list[list[float]]:
    """Generate dense embeddings for a list of text chunks.

    Args:
        chunks: List of text chunks.

    Returns:
        List of dense embedding vectors (each 384-dim).
    """
    model = _get_dense_model()
    embeddings = list(model.embed(chunks))
    return [emb.tolist() for emb in embeddings]


def generate_sparse_embeddings(
    chunks: list[str],
) -> list[qmodels.SparseVector]:
    """Generate sparse (BM25) embeddings for a list of text chunks.

    Args:
        chunks: List of text chunks.

    Returns:
        List of Qdrant SparseVector objects with indices and values.
    """
    model = _get_sparse_model()
    sparse_embeddings = list(model.embed(chunks))

    result: list[qmodels.SparseVector] = []
    for se in sparse_embeddings:
        # fastembed returns SparseEmbedding with .indices and .values
        indices: list[int] = []
        values: list[float] = []

        if hasattr(se, "indices") and hasattr(se, "values"):
            indices = [int(i) for i in se.indices]
            values = [float(v) for v in se.values]
        elif isinstance(se, dict):
            # Dict format: {token_id: weight}
            for k, v in se.items():
                indices.append(int(k))
                values.append(float(v))
        elif hasattr(se, "as_dict"):
            d: dict[str, float] = se.as_dict()
            for k, v in d.items():
                indices.append(int(k))
                values.append(float(v))

        result.append(qmodels.SparseVector(indices=indices, values=values))

    return result


async def delete_document_points(
    client: AsyncQdrantClient,
    doc_id: str,
) -> int:
    """Delete all points for a document from Qdrant.

    Uses a payload filter to find all points with the given doc_id.

    Args:
        client: AsyncQdrantClient instance.
        doc_id: The document UUID5 to delete.

    Returns:
        Number of points deleted.
    """
    from qdrant_client.http import models as qmodels

    # Count points before deletion
    count_result = await client.count(
        collection_name=COLLECTION_NAME,
        count_filter=qmodels.Filter(
            must=[
                qmodels.FieldCondition(
                    key="doc_id",
                    match=qmodels.MatchValue(value=doc_id),
                ),
            ],
        ),
        exact=True,
    )
    point_count = count_result.count

    # Delete points with matching doc_id
    await client.delete(
        collection_name=COLLECTION_NAME,
        points_selector=qmodels.FilterSelector(
            filter=qmodels.Filter(
                must=[
                    qmodels.FieldCondition(
                        key="doc_id",
                        match=qmodels.MatchValue(value=doc_id),
                    ),
                ],
            ),
        ),
    )
    logger.info("Deleted %d points for doc_id=%s", point_count, doc_id)
    return point_count


async def upsert_chunks(
    client: AsyncQdrantClient,
    filename: str,
    doc_id: str,
    chunks: list[str],
    dense_vectors: list[list[float]],
    sparse_vectors: list[qmodels.SparseVector],
    extra_payloads: list[dict[str, object]] | None = None,
    *,
    file_hash: str = "",
    chunk_size: int = 0,
    chunk_overlap: int = 0,
) -> int:
    """Upsert all chunks for a document into Qdrant.

    Args:
        client: AsyncQdrantClient instance.
        filename: Original filename.
        doc_id: UUID5 document ID.
        chunks: List of text chunks.
        dense_vectors: List of dense embedding vectors.
        sparse_vectors: List of sparse vectors.
        extra_payloads: Optional list of per-chunk metadata dicts (e.g., CSV row data).
        file_hash: SHA-256 hex digest of the original file (for duplicate detection).
        chunk_size: Chunk size setting used for this ingestion.
        chunk_overlap: Chunk overlap setting used for this ingestion.

    Returns:
        Number of points upserted.

    Raises:
        ValueError: If lengths of chunks and vectors don't match.
    """
    from datetime import datetime, timezone

    n = len(chunks)
    if len(dense_vectors) != n or len(sparse_vectors) != n:
        raise ValueError(
            f"Mismatched lengths: chunks={n}, dense={len(dense_vectors)}, "
            f"sparse={len(sparse_vectors)}"
        )

    # Delete existing points for this document first (re-ingestion)
    await delete_document_points(client, doc_id)

    points: list[qmodels.PointStruct] = []
    now = datetime.now(timezone.utc).isoformat()

    for i in range(n):
        point_id = make_doc_id(filename, i)

        payload: dict[str, object] = {
            "text": chunks[i],
            "source": filename,
            "chunk_index": i,
            "total_chunks": n,
            "doc_id": doc_id,
            "created_at": now,
            "file_hash": file_hash,
            "chunk_size": chunk_size,
            "chunk_overlap": chunk_overlap,
        }

        # Merge extra payload if provided for this chunk
        if extra_payloads and i < len(extra_payloads):
            payload.update(extra_payloads[i])

        # VectorStruct is a Union type alias (not callable), so we cast the named
        # vector dict to satisfy the type checker. At runtime, Qdrant accepts
        # {"dense": List[float], "sparse": SparseEmbedding} for named vectors.
        points.append(
            qmodels.PointStruct(
                id=point_id,
                vector=cast(
                    qmodels.VectorStruct,
                    {
                        "dense": dense_vectors[i],
                        "sparse": sparse_vectors[i],
                    },
                ),
                payload=payload,
            )
        )

    await client.upsert(
        collection_name=COLLECTION_NAME,
        points=points,
        wait=True,
    )

    logger.info(
        "Upserted %d chunks for '%s' (doc_id=%s)",
        n,
        filename,
        doc_id,
    )

    return n
