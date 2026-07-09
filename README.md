# RAG-Studio

**Your private, local document chat assistant.** Upload documents, chat with them using your own LLM API key — nothing leaves your machine.

---

## Features

- 🔒 **100% Local & Private** — All embeddings, vector search, and reranking run on your machine. Only the LLM call goes to the provider API (using your key).
- 📄 **Rich Document Support** — Upload `.txt`, `.md` files. Chunked, embedded, and indexed automatically.   
_(Support for PDF, DOCX, and CSV is planned for future releases.)_
- 🔍 **Hybrid Search** — Combines dense (semantic) and sparse (BM25 keyword) search with Reciprocal Rank Fusion (RRF) and cross-encoder reranking for best-in-class retrieval quality.
- 💬 **Conversational RAG Chat** — Multi-session chat with streaming responses, source citations (`[N]` badges with hover tooltips and expandable cards), and semantic answer caching for instant follow-up responses.
- 🌐 **Bilingual UI** — English and Russian, switchable on the fly with no page reload.
- 🐳 **Single Docker Container** — FastAPI + Qdrant + UI + all ML models in one image. Start instantly — models are pre-downloaded during build.
- 🔐 **Encrypted Secrets** — Your API keys are AES-256 encrypted at rest. Never logged or exposed.
- ⚙️ **Configurable Pipeline** — Choose Top-K, chunk size, overlap, temperature, max tokens, and your own system prompt.

> **v1.0 Note:** Only **DeepSeek** is currently enabled as the LLM provider. OpenAI, Anthropic, and Ollama are stubs ("coming soon") and will be activated in future releases.

---

## Quick Start

```bash
# 1. Clone the repository
git clone https://github.com/Togelan/RAG-Studio.git
cd rag-studio

# 2. Set your DeepSeek API key
echo "DEEPSEEK_API_KEY=your-api-key-here" > .env

# 3. Build the Docker image (includes model downloads — one-time, ~3–5 minutes)
docker compose build

# 4. Start the container
docker compose up -d

# 5. Open in your browser
#    http://localhost:8000
```

> **That's it.** After the initial build, subsequent starts are instant — all models are baked into the image.

---

## Configuration

### Required: API Key

RAG-Studio needs a DeepSeek API key to call the LLM. Pass it via environment variable:

**Option A — `.env` file (recommended):**

```bash
# Create .env in the project root:
echo "DEEPSEEK_API_KEY=your-api-key-here" > .env
```

The `docker-compose.yml` reads this file automatically via `env_file: - .env`.

**Option B — `docker run` with `-e`:**

```bash
docker run -d \
  -p 8000:8000 \
  -e DEEPSEEK_API_KEY=your-api-key-here \
  -v ./rag-data:/app/data \
  rag-studio:latest
```

You can also set the key from the **Settings** page in the UI (`/settings`) — it will be validated, encrypted, and persisted.

### Volumes

All persistent data lives in `./rag-data/` on your host:

| Host Path | Purpose | Survives Restart? |
|-----------|---------|:---:|
| `./rag-data/qdrant_storage/` | Vector database (all embeddings) | ✅ |
| `./rag-data/checkpoints/` | Chat history and session state (SQLite) | ✅ |
| `./rag-data/settings.enc.json` | Encrypted API keys and settings | ✅ |
| `./rag-data/raw_uploads/` | Original uploaded files (for re-ingestion) | ✅ |
| `./rag-data/logs/` | Audit logs (rotated daily) | ✅ |

### Resource Limits

Configured in `docker-compose.yml`:

| Resource | Minimum | Recommended |
|----------|---------|-------------|
| RAM | 4 GB | 8 GB |
| CPU | 2 cores | 4 cores |

---

## Models — How They Work

RAG-Studio uses three local ML models, all running **entirely on your machine** with zero external API calls:

| Model | Size | Purpose |
|-------|------|---------|
| `paraphrase-multilingual-MiniLM-L12-v2` | ~120 MB | Dense (semantic) embeddings, 384-dim |
| `Qdrant/bm25` | ~1 MB | Sparse (BM25 keyword) embeddings |
| `ms-marco-MultiBERT-L-12` | ~110 MB | Cross-encoder reranker (FlashRank) |

### Downloaded During Build, Not at Runtime

All three models are pre-downloaded **during `docker build`** from Hugging Face and baked into the Docker image. This means:

- ✅ **Instant startup** — no waiting for model downloads on first run.
- ✅ **Offline-ready after build** — the container has everything it needs.
- ✅ **Reproducible** — the image is self-contained; no network calls for embeddings.

The `Dockerfile` includes explicit `RUN` steps that import each model via `fastembed` and `flashrank`, triggering the download to `/root/.cache/` inside the image. The entrypoint script (`docker-entrypoint.sh`) verifies all models load correctly before starting the server.

> **Why not download on `docker run`?** Because embedding models are large (~230 MB total) and downloading them on every first run would add 2–5 minutes of startup time. Baking them into the image trades a one-time build cost for instant runtime startup.

### Why Not in Git?

Models are **not** stored in this repository — they're pulled from Hugging Face during the Docker build. The `.gitignore` excludes the `data/models/` directory. If you're developing locally without Docker, run:

```bash
python scripts/download_models.py
```

This downloads the same models to `data/models/fastembed_cache/` and `data/models/flashrank/`.

---

## Container Lifecycle

```bash
# Start (detached)
docker compose up -d

# View logs
docker compose logs -f

# Check health status
docker inspect --format='{{.State.Health.Status}}' rag-studio

# Stop
docker compose down

# Restart
docker compose restart

# Rebuild after code changes
docker compose build --no-cache
docker compose up -d
```

### Health Check

The container includes a built-in `HEALTHCHECK` (30s interval, 10s timeout, 3 retries) that pings `http://localhost:8000/health`. The UI also polls `GET /api/health/status` every 30 seconds and shows:

- 🟢 **Ready** — Qdrant connected + API key configured
- 🟡 **No API key** — Qdrant connected but no API key set
- 🔴 **Disconnected** — Qdrant unreachable

### Graceful Shutdown

On `docker stop`, the container waits up to 15 seconds for in-progress tasks to complete, then closes Qdrant and the checkpointer cleanly.

---

## Persistence — What Survives Restarts

All user data is stored in volume-mounted directories and survives `docker compose down` / `docker compose up` cycles:

| Data | Storage | Notes |
|------|---------|-------|
| Uploaded documents & chunks | `./rag-data/qdrant_storage/` | Full vector index with metadata |
| Chat sessions & history | `./rag-data/checkpoints/checkpoints.db` | SQLite via LangGraph checkpointer |
| API keys & settings | `./rag-data/settings.enc.json` | AES-256 encrypted (Fernet) |
| Original uploaded files | `./rag-data/raw_uploads/` | Used for re-ingestion after settings changes |
| Language preference | Browser cookie + localStorage | 1-year expiry |

> **To fully reset**: delete the `./rag-data/` directory and restart the container.

---

## Troubleshooting

### Qdrant Lock File Error

**Symptom:** Container fails to start with a message about a `.lock` file.

**Cause:** Qdrant was not shut down cleanly (e.g., power loss, `docker kill`).

**Fix:** The entrypoint script automatically removes stale lock files on startup. If the issue persists:

```bash
docker compose down
rm -rf ./rag-data/qdrant_storage/.lock
docker compose up -d
```

### Missing API Key

**Symptom:** Status indicator shows 🟡 "No API key". Chat returns an error.

**Fix:**
1. Ensure `.env` contains `DEEPSEEK_API_KEY=your-api-key-here`
2. Or set it via the Settings UI (`/settings` → Provider → API Key → Save)
3. Verify with: `docker compose exec rag-studio env | grep DEEPSEEK`

### "No text found in PDF"

**Symptom:** Uploading a PDF fails with "No text found in PDF."

**Cause:** The PDF is an image-only scan (no extractable text layer).

**Fix:** OCR/scanned PDFs are not supported in v1.0. Use PDFs with embedded text. Convert scanned PDFs to text externally before uploading.

### Port 8000 Already in Use

```bash
# Find what's using the port
netstat -ano | findstr :8000   # Windows
lsof -i :8000                   # macOS/Linux

# Use a different port
docker compose up -d
# Edit docker-compose.yml: change "8000:8000" to "9000:8000"
```

### Container Won't Start (OOM)

**Symptom:** Container exits with code 137 (killed by OOM killer).

**Fix:** Increase Docker's memory limit:
- Docker Desktop: Settings → Resources → Memory → set to ≥ 6 GB
- Or edit `docker-compose.yml`: `mem_limit: 6g`

### Rebuild Not Picking Up Changes

```bash
# Force a clean rebuild
docker compose build --no-cache
docker compose up -d --force-recreate
```

---

## Development (Local, Without Docker)

For contributing or running without Docker:

```bash
# 1. Create and activate a virtual environment
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Download ML models (one-time)
python scripts/download_models.py

# 4. Set environment variables
export PYTHONPATH=src
export DEEPSEEK_API_KEY=your-api-key-here

# 5. Run the application
uvicorn src.api.main:app --reload --host 0.0.0.0 --port 8000

# 6. Run tests
pytest tests/ -v
```

### Code Quality

```bash
# Lint
ruff check .

# Format check
ruff format --check .

# Type check
mypy --strict src/

# Security audit
bandit -r src/
```

---

## Architecture

```
┌─────────────────────────────────────────────────┐
│                  Docker Container                │
│                                                  │
│  ┌──────────┐   ┌──────────────┐   ┌─────────┐ │
│  │ FastAPI   │   │  LangGraph    │   │ Qdrant  │ │
│  │ (async)   │◄──┤  StateGraph   │◄──┤ (local) │ │
│  │ Jinja2 UI │   │  + Checkpointer│   │         │ │
│  └──────────┘   └──────────────┘   └─────────┘ │
│       │                                          │
│  ┌────▼─────────────────────────────────────┐   │
│  │  Encrypted Local Storage (volume)        │   │
│  │  API keys (AES-256), chat history (SQLite)│   │
│  └──────────────────────────────────────────┘   │
└─────────────────────────────────────────────────┘
```

**7-Node LangGraph Pipeline:** `analyzer → cache_check | retrieve → generate_from_cache | generate_from_retrieval → validate → save_to_cache → END`

See [`system_spec.md`](system_spec.md) for full functional requirements, acceptance criteria, and technical details.

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Language | Python 3.14 |
| Backend | FastAPI (async) |
| Agent Framework | LangGraph (StateGraph, async nodes, SQLite checkpointer) |
| Vector DB | Qdrant (dense + sparse, hybrid search, RRF fusion) |
| Embeddings | fastembed (local ONNX, BM25) |
| Reranker | FlashRank (ms-marco-MultiBERT-L-12, local ONNX) |
| UI | Jinja2 + vanilla HTML/CSS/JS (responsive, i18n-ready) |
| Observability | LangSmith (traces, RAGAS evaluation) |

---

