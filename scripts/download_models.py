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
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.paths import configured_path  # noqa: E402


def download_models() -> None:
    """Download all three models to the project cache directory."""
    cache_dir = str(
        configured_path("FASTEMBED_CACHE_PATH", "models", "fastembed_cache")
    )
    logger.info("Cache directory: %s", cache_dir)

    # 1. Dense embeddings
    logger.info(
        "Downloading dense embedding model: paraphrase-multilingual-MiniLM-L12-v2"
    )
    from fastembed import TextEmbedding

    _dense = TextEmbedding(
        model_name="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        cache_dir=cache_dir,
    )
    # Trigger actual download by embedding
    _ = list(_dense.embed(["warmup"]))
    logger.info("Dense embedding model cached successfully.")

    # 2. Sparse embeddings (BM25)
    logger.info("Downloading sparse embedding model: Qdrant/bm25")
    from fastembed import SparseTextEmbedding

    _sparse = SparseTextEmbedding(model_name="Qdrant/bm25", cache_dir=cache_dir)
    _ = list(_sparse.embed(["warmup"]))
    logger.info("Sparse embedding model cached successfully.")

    # 3. Reranker
    logger.info("Downloading reranker model: ms-marco-MultiBERT-L-12")
    from flashrank import (
        Ranker,  # type: ignore[import-untyped]  # flashrank ships no stubs
    )

    flashrank_cache_dir = str(
        configured_path("FLASHRANK_CACHE_PATH", "models", "flashrank")
    )
    _ranker = Ranker(
        model_name="ms-marco-MultiBERT-L-12", cache_dir=flashrank_cache_dir
    )
    logger.info("Reranker model cached successfully.")

    logger.info("All models downloaded and cached.")


if __name__ == "__main__":
    download_models()
