# Current Task State

Updated: 2026-08-12

## Scope

The active task is to complete the local-first RAG-Studio chunking strategy
library for static, recursive, parent-document, and sentence-window strategies.
The application remains a single Docker container with embedded persistent
Qdrant; this is not a SaaS or multi-tenant change.

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

## Verification completed

- Targeted chunking/retrieval/vector-store/settings/re-ingest suite:
  `64 passed` before the final legacy compatibility regression was added.
- Legacy settings migration suite after compatibility repair: `9 passed`.
- Docker syntax compilation for `src/` and `tests/`: passed.
- Source LSP diagnostics for modified Python files: no diagnostics.
- Docker Compose application startup: passed.
- Embedded Qdrant health: `HTTP 200 {"status":"ok"}`.
- Informational 50,000-point benchmark under 4 GB RAM / 2 CPU Docker limits:
  ingestion `683.315 s`, peak cgroup memory `211.96 MB`, storage `24.41 MB`,
  retrieval p95 `3.138 ms`; completed successfully.

## Current commits

The chunking implementation and follow-up hardening are committed on
`features-v2`:

- `661c366` strategy units and durable metadata
- `d996180` strategy library
- `a6030ef` re-ingestion and chunk-cap safety
- `02061e2` retrieval location safety
- `ddcb307` strategy configuration hardening, top-k propagation, benchmark
  measurements, legacy compatibility, and mobile-width fix

## Remaining limitations

- The full repository suite and full quality commands have not been confirmed
  green in the current checkout. Earlier broad checks reported unrelated
  existing Ruff/format issues, and an independent QA pass reported additional
  failures that require a fresh current-checkout run.
- The final five-lane review/debugging gate has not passed for the final commit.
- Browser evidence covers strategy panel switching and Docker startup, but a
  complete current-checkout browser pass for every manual re-ingest scenario is
  still outstanding.
- The benchmark is informational. Qdrant emitted its expected warning that
  embedded local mode is not recommended above 20,000 points.
- The host Python virtual environments currently cannot launch their configured
  Python 3.14 executable; verification was therefore run in Docker.

## Runtime state

Docker Compose is running the `rag-studio` service with embedded Qdrant on
`http://localhost:8000`. Project `rag-data` was not cleared or replaced.

## Git/worktree state

The product changes are committed. `.omo/` contains local LazyCodex workflow
state and remains intentionally untracked; it must not be included in product
commits.
