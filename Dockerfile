# RAG-Studio — Single-stage Docker Build with pre-cached models
FROM python:3.14-slim

WORKDIR /app

# Run the application as an unprivileged user. Keep the UID/GID explicit so
# deployments can prepare mounted volumes consistently.
ARG APP_UID=10001
ARG APP_GID=10001
RUN groupadd --gid "${APP_GID}" ragstudio && \
    useradd --uid "${APP_UID}" --gid ragstudio --create-home --shell /usr/sbin/nologin ragstudio

# Install build dependencies (curl for healthcheck)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    ca-certificates \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Pre-cache fastembed models — dense embeddings (384-dim, ONNX)
ENV HOME=/home/ragstudio \
    FASTEMBED_CACHE_PATH=/home/ragstudio/.cache/fastembed \
    FLASHRANK_CACHE_PATH=/home/ragstudio/.cache/flashrank
RUN python -c "from fastembed import TextEmbedding; \
    _m = TextEmbedding(model_name='sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2', cache_dir='/home/ragstudio/.cache/fastembed'); \
    _ = list(_m.embed(['warmup']))"

# Pre-cache fastembed models — sparse embeddings (BM25)
RUN python -c "from fastembed import SparseTextEmbedding; \
    _m = SparseTextEmbedding(model_name='Qdrant/bm25', cache_dir='/home/ragstudio/.cache/fastembed'); \
    _ = list(_m.embed(['warmup']))"

# Pre-cache FlashRank reranker (ms-marco-MultiBERT-L-12, local ONNX)
RUN python -c "from flashrank import Ranker; \
    Ranker(model_name='ms-marco-MultiBERT-L-12', cache_dir='/home/ragstudio/.cache/flashrank')"

# Copy application source code
COPY src/ ./src/

# Set PYTHONPATH so IDE imports like `from src.api.xxx` resolve
ENV PYTHONPATH=/app

# Declare volume for persistent data (Qdrant, models, logs, secrets)
VOLUME ["/app/data"]

# Create every runtime-writable location before dropping privileges.
RUN mkdir -p \
        /app/data/qdrant \
        /app/data/qdrant_storage \
        /app/data/checkpoints \
        /app/data/logs \
        /app/data/secrets \
        /data/qdrant \
        /home/ragstudio/.rag-studio/logs \
        /home/ragstudio/.rag-studio/secrets && \
    chown -R ragstudio:ragstudio /app /data /home/ragstudio
# Copy entrypoint script
COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

USER ragstudio

# Expose FastAPI port
EXPOSE 8000

# Use the entrypoint for model verification and server startup
ENTRYPOINT ["/docker-entrypoint.sh"]

# Health check (uses curl against the /health endpoint)
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1
