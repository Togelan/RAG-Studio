#!/bin/sh
set -e

# Bind mounts are created by Docker/host filesystems and can be root-owned
# despite the image directories being owned by ragstudio. Fix their ownership
# once, then re-exec this entrypoint as the unprivileged application user.
if [ "$(id -u)" -eq 0 ]; then
  mkdir -p \
    /app/data/qdrant \
    /app/data/qdrant_storage \
    /app/data/checkpoints \
    /app/data/logs \
    /app/data/secrets
  chown -R ragstudio:ragstudio /app/data
  exec su -s /bin/sh ragstudio -c /docker-entrypoint.sh
fi

# --- 1. Clean up stale Qdrant lock file ---
DATA_ROOT="${RAG_STUDIO_DATA_ROOT:-/app/data}"
QDRANT_STORAGE="${QDRANT_PATH:-$DATA_ROOT/qdrant_storage}"
LOCK_FILE="$QDRANT_STORAGE/.lock"
if [ -f "$LOCK_FILE" ]; then
  echo "⚠️  Removing stale Qdrant lock file..."
  rm -f "$LOCK_FILE"
fi

# --- 2. Ensure required directories exist ---
mkdir -p "$QDRANT_STORAGE"
mkdir -p "$DATA_ROOT/checkpoints"

# --- 3. Set cache paths for pre-downloaded models ---
export FASTEMBED_CACHE_PATH=/home/ragstudio/.cache/fastembed
export FLASHRANK_CACHE_PATH=/home/ragstudio/.cache/flashrank

# --- 4. Verify that models are correctly loaded (sanity check) ---
echo "🔍 Verifying models are available..."
python -c "
import sys, os
os.environ['FASTEMBED_CACHE_PATH'] = '/home/ragstudio/.cache/fastembed'
os.environ['FLASHRANK_CACHE_PATH'] = '/home/ragstudio/.cache/flashrank'

try:
    from fastembed import TextEmbedding
    dense = TextEmbedding(
        model_name='sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2',
        cache_dir='/home/ragstudio/.cache/fastembed'
    )
    _ = list(dense.embed(['warmup']))
    print('✅ Dense model loaded successfully')
except Exception as e:
    print(f'❌ Dense model failed: {e}')
    sys.exit(1)

try:
    from fastembed import SparseTextEmbedding
    sparse = SparseTextEmbedding(
        model_name='Qdrant/bm25',
        cache_dir='/home/ragstudio/.cache/fastembed'
    )
    _ = list(sparse.embed(['warmup']))
    print('✅ Sparse model loaded successfully')
except Exception as e:
    print(f'❌ Sparse model failed: {e}')
    sys.exit(1)

try:
    from flashrank import Ranker
    ranker = Ranker(
        model_name='ms-marco-MultiBERT-L-12',
        cache_dir='/home/ragstudio/.cache/flashrank'
    )
    print('✅ Reranker loaded successfully')
except Exception as e:
    print(f'❌ Reranker failed: {e}')
    sys.exit(1)
"

if [ $? -ne 0 ]; then
    echo "❌ Model verification failed. Container will not start."
    exit 1
fi

# --- 5. Start the server ---
echo "🚀 Starting RAG-Studio server..."
exec uvicorn src.api.main:app --host 0.0.0.0 --port 8000
