# RAG-Studio Agent Guide

**Generated:** 2026-09-04 | **Commit:** `94581e0` | **Branch:** `codex/mvp-v1`

## Overview

Python 3.14 local-first RAG application with FastAPI, LangGraph, hybrid Qdrant
retrieval, and safe document ingestion. React/TypeScript is the active SaaS
migration surface; local runtime/import boundaries remain authoritative. Read
`.agents/copilot-instructions.md` and the nearest domain guide before edits.

## Structure

```text
src/               Production Python; six approved domain packages
frontend/          React/Vite SaaS client, browser tests, build/audit scripts
widget/            Separate distributable IIFE widget package and artifact QA
tests/             Mirrored pytest domains plus E2E, QA, SQL, and JS contracts
scripts/            Benchmarks, model tools, disposable QA servers and harnesses
docs/              ADRs, feature records, deployment runbooks, design evidence
supabase/          Versioned SaaS schema migrations
.agents/           Project roles, skills, and workflow instructions
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
| React SaaS | `frontend/src/` | Routes, feature state, API gateways, i18n. |
| Widget | `widget/src/` | Embeddable custom-element runtime; artifact contract. |
| QA/build | `scripts/qa/`, `frontend/package.json`, `widget/package.json` | Disposable and package-specific workflows. |
| Tests | `tests/<domain>/`, `frontend/tests/` | Python, browser, SQL, and SSE contracts. |
| Schema/decisions | `supabase/`, `docs/adr/`, `docs/features/` | Durable migrations and requirement traceability. |

## Code map

| Symbol | Type | Location | CodeGraph refs | Role |
| --- | --- | --- | ---: | --- |
| `create_app` | function | `src/api/main.py:245` | 26 | FastAPI composition root. |
| `create_graph` | async context | `src/graph/builder.py` | 10 | Compiled graph/checkpointer lifecycle. |
| `build_rag_graph` | function | `src/graph/builder.py` | 8 | Seven-node StateGraph topology. |
| `hybrid_search` | async function | `src/retrieve/orchestrator.py` | 16 | Search, expansion, reranking, fallback. |
| `get_vector_store` | dependency | `src/api/dependencies.py:314` | 11 | Vendor-neutral storage boundary. |
| `VectorRecord` | domain type | `src/vector_store/models.py` | 20 | Shared persisted/search result contract. |
| `SaasEntry` | React component | `frontend/src/features/saas/SaasEntry.tsx` | 4 | SaaS route composition and auth mode. |
| `IngestionApi` | TypeScript gateway | `frontend/src/features/ingestion/ingestion-api.ts` | 26 | Client-side ingestion contract. |

## Canonical implementation workflow

For substantial work, use the globally installed `alexey-workflow` skill with
the project adapter at `.agents/workflow-adapter.md`. The global workflow owns
lifecycle, delegation roles, and model routing; this repository owns its domain
rules, commands, and evidence requirements.

Non-trivial executable plans must show an explicit proposed `Intensity:` for
every implementation task and every independent model-reasoning final gate:
`L1_SIMPLE`, `L2_EASY`, `L3_MEDIUM`, `L4_HARD`, `L5_INSANE`, or `L6_EXTREME`.
The human approves and locks those values; the coordinator does not infer or
change them during execution.

For each human-reviewable non-trivial plan version, use the project
`lavish-plan-review` skill at `.agents/skills/SKILL.md`. Keep the Markdown plan
canonical; its local `.lavish/` artifact is an annotatable companion only.
Annotations are feedback, not approval or authority to start execution.

Plan before product edits; use small, atomic, reversible changes. Run targeted
checks, then applicable complete checks. Exercise the affected journey in the
running app and record URL, scenario, observed result, viewport, and screenshots
for visual changes.

For high-risk changes, run the read-only `.agents/skills/adversarial-review/`
gate after normal QA and before merge. Invoke `.agents/agents/adversarial-qa.md`
against the final diff and evidence. `PASS` is required; `FAIL` and
`INCONCLUSIVE` block merge. High-risk areas include identity/CSRF/roles,
Personal Lab/Workspace/Agent/Widget/billing, ingestion and re-indexing,
Qdrant/cache/checkpoint/migration/rollback, streaming/concurrency, secrets and
redaction, retrieval/citations, public endpoints, and stateful React UI.

Browser QA uses only the configured Playwright MCP server `playwright_qa_2` and
its structured interactions:
navigate, snapshot, click, type/fill form, press keys,
upload files, wait, resize, screenshot, and verification. Do not use
`browser_run_code`, `browser_run_code_unsafe`, `browser_evaluate`, or arbitrary
JavaScript/Playwright code. No other Playwright MCP server, browser-control
mechanism, or non-Playwright browser tool is permitted in tests or project
instructions.

Non-trivial features start with `.agents/skills/feature-discussion/SKILL.md`.
It records `CONTEXT.md`, an ADR, and `docs/features/<slug>.md`, then stops for
user approval; create the executable plan through `alexey-workflow` afterward.

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
- Resolve tenant identity, roles, collections, entitlements, and publication
  scope server-side; browser values are selectors, never authority.
- Keep typed frontend gateways and safe rendering at the React boundary. Legacy
  `innerHTML` is confined to Jinja/vanilla/widget surfaces.
- Do not delete or commit `graphify-out/`.

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

Frontend and widget checks are separate package workflows. Use `cd frontend;
npm run lint; npm run typecheck; npm run test; npm run build; npm run audit:prod`
and `cd widget; npm run verify` as applicable. Playwright runs through the
configured structured QA server, one worker, with retained evidence.

Run Docker sequentially only. Inspect the full-path Docker CLI `version` and
`ps -a`, set `COMPOSE_PARALLEL_LIMIT=1`, run `docker compose config`, start
detached, then verify `ps` and `stats --no-stream`. Never restart Docker Desktop,
prune/remove data/images/volumes, rebuild an unchanged suitable image, repeat a
stalled command, or use unbounded waits without explicit authority. Use unique
Compose project names and operator-owned env files; preserve volumes during
restart/rollback checks. Browser QA starts only after the target container is
confirmed `Up`.

Do not modify `.env`, credentials, production data, or unrelated files; ask before destructive actions or major architecture changes.
