#!/bin/sh
set -e

# --- 1. Clean up stale Qdrant lock file ---
LOCK_FILE="/app/data/qdrant_storage/.lock"
if [ -f "$LOCK_FILE" ]; then
  echo "⚠️  Removing stale Qdrant lock file..."
  rm -f "$LOCK_FILE"
fi

# --- 2. Ensure required directories exist ---
mkdir -p /app/data/qdrant_storage
mkdir -p /app/data/checkpoints

# --- 3. Set cache paths for pre-downloaded models ---
export FASTEMBED_CACHE_PATH=/root/.cache/fastembed
export FLASHRANK_CACHE_PATH=/root/.cache/flashrank

# --- 4. Verify that models are correctly loaded (sanity check) ---
echo "🔍 Verifying models are available..."
python -c "
import sys, os
os.environ['FASTEMBED_CACHE_PATH'] = '/root/.cache/fastembed'
os.environ['FLASHRANK_CACHE_PATH'] = '/root/.cache/flashrank'

try:
    from fastembed import TextEmbedding
    dense = TextEmbedding(
        model_name='sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2',
        cache_dir='/root/.cache/fastembed'
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
        cache_dir='/root/.cache/fastembed'
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
        cache_dir='/root/.cache/flashrank'
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
