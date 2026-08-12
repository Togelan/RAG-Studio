# Current Task State

Updated: 2026-08-12

## Scope

The active feature is the local-first RAG-Studio chunking strategy library for
static, recursive, parent-document, and sentence-window strategies. The
application remains a single Docker container with embedded persistent Qdrant;
this is not a SaaS or multi-tenant change.

## Implemented

- Added the four text chunking strategies and strategy dispatch during
  ingestion.
- Preserved CSV row-based ingestion with the `csv_row` strategy marker.
- Added bounded, versioned chunking settings with legacy flat-field migration.
- Persisted strategy, fingerprint, schema, parent/window, and location metadata
  in Qdrant and document-index payloads.
- Added duplicate comparison using document identity, content, and strategy
  fingerprints.
- Added parent-document and sentence-window retrieval expansion,
  deduplication, context budgets, final `top_k`, and citation fallback.
- Added settings strategy selection with conditional parameter panels.
- Preserved Skip/Re-ingest All behavior with per-document replacement and
  rollback protection.
- Added document-table strategy and parameter display.
- Added re-ingest ownership/path-traversal validation.
- Added benchmark resource reporting and a responsive Settings mobile-width
  fix.
- Hardened legacy strategy defaults and re-ingest compatibility.

## Current Checkout

- Branch: `features-v2`
- HEAD: `33b53a5dcf1682b68fd21e06abea8e4fa6383097`
- Current feature commits:
  - `661c366` strategy units and durable metadata
  - `d996180` strategy library
  - `a6030ef` re-ingestion and chunk-cap safety
  - `02061e2` retrieval location safety
  - `ddcb307` strategy configuration hardening and benchmark/mobile fixes
  - `33b53a5` legacy default and re-ingest compatibility hardening

## Verification Completed

All commands below were run on this checkout using the project `venv` with
Python 3.14.5 unless noted otherwise.

- Full test suite: `python -m pytest tests/ -v --tb=short` — `625 passed`.
- Lint: `python -m ruff check .` — passed.
- Formatting: `python -m ruff format --check .` — passed.
- Type checking: `python -m mypy --strict src/` — passed with no issues in
  48 source files.
- Security scan: `python -m bandit -r src/` — no issues identified.
- Docker image: `docker compose build` — passed.
- Docker runtime: `rag-studio` is healthy with embedded Qdrant.
- HTTP smoke checks: `GET /health` and `GET /api/settings` — HTTP 200.
- Informational 50,000-point benchmark under 4 GB RAM / 2 CPU Docker limits:
  ingestion `683.315 s`, peak cgroup memory `211.96 MB`, storage `24.41 MB`,
  retrieval p95 `3.138 ms`; completed successfully.

## Remaining Limitations

- Browser evidence covers strategy-panel switching and Docker startup, but a
  fresh complete browser pass for every manual re-ingest scenario remains
  outstanding.
- The benchmark is informational. Qdrant emits its expected warning that
  embedded local mode is not recommended above 20,000 points.
- Upstream dependency warnings remain during tests: LangGraph coroutine API,
  Starlette `TemplateResponse`, FastEmbed pooling behavior, and PyPDF2
  deprecation. They do not fail the suite.
- Final `$review-work`/Graphify evidence has not yet been recorded for the
  current uncommitted quality/documentation update.

## Runtime And Worktree State

Docker Compose runs `rag-studio` with embedded Qdrant on
`http://localhost:8000`. Project `rag-data` was not cleared or replaced.

The baseline lint/format remediation and `init-deep` child guidance are present
on this branch. `.omo/`, `rag-data/`, secrets, caches, and the locally
installed `grill-with-docs` skill remain excluded from product commits.
