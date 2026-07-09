"""Download and cache all required ML models for RAG-Studio.

Usage:
    python scripts/download_models.py

Downloads:
    - Dense embedding model: paraphrase-multilingual-MiniLM-L12-v2
    - Sparse embedding model: Qdrant/bm25
    - Reranker model: ms-marco-MultiBERT-L-12

All models are cached to data/models/fastembed_cache/ (the same directory
used by the embedder at runtime). Set FASTEMBED_CACHE_PATH env var
to override.
"""

from __future__ import annotations

import logging
from pathlib import Path

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

# Same cache path as src/ingestion/embedder.py — project-relative
_CACHE_DIR = str(
    Path(__file__).resolve().parent.parent / "data" / "models" / "fastembed_cache"
)


def download_models() -> None:
    """Download all three models to the project cache directory."""
    logger.info("Cache directory: %s", _CACHE_DIR)

    # 1. Dense embeddings
    logger.info(
        "Downloading dense embedding model: paraphrase-multilingual-MiniLM-L12-v2"
    )
    from fastembed import TextEmbedding

    _dense = TextEmbedding(
        model_name="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        cache_dir=_CACHE_DIR,
    )
    # Trigger actual download by embedding
    _ = list(_dense.embed(["warmup"]))
    logger.info("Dense embedding model cached successfully.")

    # 2. Sparse embeddings (BM25)
    logger.info("Downloading sparse embedding model: Qdrant/bm25")
    from fastembed import SparseTextEmbedding

    _sparse = SparseTextEmbedding(model_name="Qdrant/bm25", cache_dir=_CACHE_DIR)
    _ = list(_sparse.embed(["warmup"]))
    logger.info("Sparse embedding model cached successfully.")

    # 3. Reranker
    logger.info("Downloading reranker model: ms-marco-MultiBERT-L-12")
    # FlashRank uses its own cache; we set the environment variable for it
    import os

    from flashrank import (
        Ranker,  # type: ignore[import-untyped]  # flashrank ships no stubs
    )

    os.environ["FLASHRANK_CACHE_PATH"] = str(
        Path(__file__).resolve().parent.parent / "data" / "models" / "flashrank"
    )
    _ranker = Ranker(model_name="ms-marco-MultiBERT-L-12")
    logger.info("Reranker model cached successfully.")

    logger.info("All models downloaded and cached.")


if __name__ == "__main__":
    download_models()
