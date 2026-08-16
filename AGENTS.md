# RAG-Studio Agent Guide

**Generated:** 2026-08-14 | **Commit:** `3f5e6e0` | **Branch:** `features-v2`

## Overview

Python 3.14 local-first RAG application: FastAPI/Jinja2 web surface,
LangGraph orchestration, hybrid Qdrant retrieval, and safe document ingestion.
The approved target is a staged React/FastAPI multi-tenant SaaS; the current
local runtime and explicit user-controlled import boundary remain authoritative.
Read `.agents/copilot-instructions.md` plus relevant source/tests before edits.

## Structure

```text
src/api/           FastAPI wiring, routes, encrypted settings, legacy UI
src/graph/         LangGraph topology, state, sessions, retries, providers
src/ingestion/     Admission, parsing, chunking, embedding, re-ingestion
src/retrieve/      Hybrid search, context expansion, reranking
src/vector_store/  Domain contracts and Qdrant adapter/persistence
src/generate/      Reserved generation boundary; currently a placeholder
tests/             Mirrored unit/integration/E2E/JS coverage
scripts/           Manual benchmarks, model download, disposable QA servers
docs/              Accepted ADRs, feature designs, visual references
```

## Where to look

| Task | Location | Notes |
| --- | --- | --- |
| Requirements/ACs | `system_spec.md` | BA-owned FR source of truth. |
| Stable decisions | `CONTEXT.md`, `docs/adr/` | Ownership, terminology, rollback. |
| Visual contract | `DESIGN.md` | Approved tokens, references, UI stages. |
| App startup | `src/api/main.py` | Lifespan, routers, graph/Qdrant shutdown. |
| Chat execution | `src/api/routes/chat.py`, `src/graph/` | SSE, sessions, graph streaming. |
| Document lifecycle | `src/ingestion/`, `src/vector_store/` | Atomic replacement and metadata. |
| Retrieval | `src/retrieve/` | Final context units, budgets, reranking. |
| Persistent paths | `src/paths.py` | Environment overrides anchored to project. |
| Tests | `tests/<domain>/` | Mirror source boundaries; root tests are cross-cutting. |

## Code map

| Symbol | Type | Location | CodeGraph refs | Role |
| --- | --- | --- | ---: | --- |
| `create_app` | function | `src/api/main.py:206` | 26 | FastAPI composition root. |
| `create_graph` | async context | `src/graph/builder.py:250` | 10 | Compiled graph/checkpointer lifecycle. |
| `build_rag_graph` | function | `src/graph/builder.py:156` | 8 | Seven-node StateGraph topology. |
| `hybrid_search` | async function | `src/retrieve/orchestrator.py:124` | 16 | Search, expansion, reranking, fallback. |
| `get_vector_store` | dependency | `src/api/dependencies.py:314` | 11 | Vendor-neutral storage boundary. |
| `VectorRecord` | domain type | `src/vector_store/models.py` | 20 | Shared persisted/search result contract. |

## Current-checkout rules

- Use only actual code in this checkout. Do not inspect/switch/create alternate,
  stale, prunable, or deleted branches/worktrees unless explicitly requested.
- Preserve unrelated dirty-worktree changes; never reset, discard, or overwrite them.
- `.agents/copilot-instructions.md` is canonical for architecture, DoR/DoD,
  security, typing, file limits, and NFR thresholds.
- Production code stays under the six allowed `src/` domains; tests stay in `tests/`.

## Canonical implementation workflow

Use: **understand → `$ulw-plan` → `$start-work` → `$ulw-loop` → in-app
`@Browser` → `$review-work` → Graphify when needed → commit**.

1. Plan before product edits; use small, atomic, reversible changes.
2. Run targeted checks, then full applicable checks.
3. Exercise the affected journey in the running app and record URL, scenario,
   observed result, viewport, and screenshots for visual changes.
4. Review before commit; never substitute LazyCodex for project roles/Graphify.
5. Use `$remove-ai-slops` only for behavior-preserving cleanup after green tests.

Non-trivial features start with `.agents/skills/feature-discussion/SKILL.md`.
It records `CONTEXT.md`, an ADR, and `docs/features/<slug>.md`, then stops for
user approval; the user manually invokes `$ulw-plan` afterward.

For `$architect`, gate the FR against DoR first. If ready, produce a file-scoped
plan, one developer subtask, then independent QA against the actual diff. If not
ready, stop with exact gaps. Never commit/discard unless explicitly requested.

## Required decision evidence

Every non-trivial plan, developer handoff, and QA verdict records:

1. Architecture/requirement fit.
2. Measured behavior and bounded failure at the stated load threshold.
3. Two alternatives, rejection reasons, and revisit conditions.
4. Data preservation, redaction, cancellation/rollback, and exact checks run.

Unmeasured claims such as “scalable”, “safe”, or “best” are not evidence.

## Conventions and anti-patterns

- Full typing, `from __future__ import annotations`, public docstrings, async I/O.
- Source ≤500 lines, tests ≤300, functions ≤50, classes ≤200; refactor exceptions.
- Use `src.paths`, never CWD, for persistent paths.
- Secrets only through environment/encrypted storage; update empty `.env.example`.
- Never expose plaintext secrets, filesystem paths, input text, or raw provider,
  SDK, transport, or model exceptions in logs/responses.
- Qdrant document point IDs are deterministic UUID5; keep SDK shapes in adapters.
- Preserve cancellation, bounded work, metadata/citations, and replacement rollback.
- Do not add LazyCodex to runtime dependencies or delete/commit `graphify-out/`.

## UI and documentation

- Every UI task uses `design-system-style-intelligence` →
  `frontend-design-director` → `react-shadcn-ui-contract` → `omo:visual-qa`.
- `ui-design` is only for temporary legacy Jinja2 mechanics; no UI code precedes design.
- Preserve React migration rollback until verified parity; do not invent SaaS behavior.
- Feature tasks cite the owning FR and every modified FR. ADRs capture durable,
  difficult-to-reverse decisions plus alternatives, consequences, and rollback.

## Verification

```powershell
pytest tests/ -v
ruff check .
ruff format --check .
mypy --strict src/
bandit -r src/
docker compose build
```

Run Docker sequentially only. Inspect the full-path Docker CLI `version` and
`ps -a`, set `COMPOSE_PARALLEL_LIMIT=1`, run `docker compose config`, start
detached, then verify `ps` and `stats --no-stream`. Never restart Docker Desktop,
prune/remove data/images/volumes, rebuild an unchanged suitable image, repeat a
stalled command, or use unbounded waits without explicit authority. Browser QA
starts only after the target container is confirmed `Up`.

Do not modify `.env`, credentials, production data, or unrelated files. Ask
before destructive actions or major architecture changes.
