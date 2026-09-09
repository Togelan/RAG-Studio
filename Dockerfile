# RAG-Studio — multi-stage build with a single Python runtime container
FROM node:24.19.0-bookworm-slim AS frontend-builder

WORKDIR /frontend

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
# The frontend consumes the backend-owned translation bundles at build time.
# Keep this builder-only copy narrow; the runtime still receives only dist/.
COPY src/api/locales/ /src/api/locales/
RUN npm run build

FROM node:24.19.0-bookworm-slim AS widget-builder

WORKDIR /widget

COPY widget/package.json widget/package-lock.json ./
RUN npm ci

COPY widget/ ./
RUN npm run build

# The runtime remains one Python application container; only built assets
# cross this boundary, never Node/npm, frontend source, or QA tooling.
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

# Install production Python dependencies only. Development and QA tools stay
# in requirements.txt for host-side verification and never enter this image.
COPY requirements-runtime.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements-runtime.txt

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

COPY --from=frontend-builder /frontend/dist ./frontend/dist
COPY --from=widget-builder /widget/dist ./widget/dist

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
        /app/data/secrets && \
    chown -R ragstudio:ragstudio /app
# Model downloads above run during the root-owned build phase. Transfer their
# cache ownership before the runtime user transition so startup remains local.
RUN chown -R ragstudio:ragstudio /home/ragstudio/.cache
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
