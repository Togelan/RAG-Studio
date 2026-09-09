# RAG-Studio workflow adapter

This file supplies project facts to the globally installed `alexey-workflow`
skill. It does not define reusable lifecycle, role-routing, or Execution
Intensity policy.

## Toolkit

- Global toolkit: `alexey-workflow` (installed in the Codex profile; do not
  vendor, install, or modify it in this repository).
- Project instruction entrypoints: `AGENTS.md`, then the nearest nested
  `AGENTS.md`, and `.agents/copilot-instructions.md` for project conventions.
- Feature/stage evidence: `system_spec.md`, `CONTEXT.md`, `DESIGN.md`,
  `docs/adr/`, `docs/features/`, and the relevant test/QA evidence. No separate
  workflow ledger is currently identified.
- Plan-review companion: `.agents/skills/SKILL.md` (`lavish-plan-review`).

## Repository and stack

- Purpose: local-first document RAG application with a SaaS migration surface.
- Stack: Python 3.14, FastAPI, LangGraph, Qdrant, and Pydantic; React 19,
  TypeScript, Vite, Tailwind/shadcn UI in `frontend/`; a separate TypeScript
  IIFE widget in `widget/`; Supabase-compatible PostgreSQL/Auth resources for
  the stage3 Compose profile.
- Entrypoints: `src/api/main.py`; `frontend/package.json`; `widget/package.json`;
  `docker-compose.yml`.
- Specification and decisions: `system_spec.md`, `CONTEXT.md`, `DESIGN.md`,
  `docs/adr/`, `docs/features/`, and `docs/deployment/`.
- Nested instructions: the nearest `AGENTS.md` in the target directory.

## Commands

- Python setup: create a Python 3.14 virtual environment, then
  `pip install -r requirements.txt` (from `README.md`).
- Frontend/widget setup: `npm ci` in the applicable package directory.
- Focused Python test: `pytest <target> -v`.
- Python checks: `ruff check .`; `ruff format --check .`; `mypy --strict src/`;
  `bandit -r src/`.
- Frontend checks: from `frontend/`, `npm run lint`, `npm run typecheck`,
  `npm run test`, `npm run build`, and `npm run audit:prod` as applicable.
- Widget checks: from `widget/`, `npm run verify`.
- Local backend run: `uvicorn src.api.main:app --reload --host 0.0.0.0 --port 8000`.
- Docker preflight/run: inspect `docker version` and `docker ps -a`, set
  `COMPOSE_PARALLEL_LIMIT=1`, run `docker compose config`, then use the intended
  profile in `docker-compose.yml`. Docker operations are sequential.

## Invariants and boundaries

- Python production domains remain the six approved `src/` packages:
  `api`, `graph`, `vector_store`, `ingestion`, `generate`, and `retrieve`.
- Use `src.paths` for persistent paths; persistent runtime state is application
  managed. Do not modify `.env`, credentials, production data, or Compose
  volumes without explicit human approval.
- Keep tenant identity, roles, collections, entitlements, and publication scope
  server-side. Browser values are selectors, not authority.
- Preserve cancellation, bounded work, metadata/citations, deterministic UUID5
  Qdrant point IDs, and document-replacement rollback.
- Keep typed frontend gateways and safe rendering at the React boundary.
- UI work uses the existing project design skill chain and structured
  `playwright_qa_2` browser QA; the project instructions define its evidence
  requirements.
- Stage3 resources are PostgreSQL, GoTrue, Qdrant, Mailpit, and a fake provider
  in the `stage3` Compose profile. Required operator-owned secrets/configuration
  are intentionally not stored in the repository.

## Workflow activation

- Trivial deterministic changes may follow a direct, focused-check path.
- Non-trivial features first use `.agents/skills/feature-discussion/SKILL.md`;
  it records approved project decisions and stops for human approval.
- For non-trivial executable planning, use the globally installed
  `alexey-workflow` skill and this adapter. Every implementation task and every
  independent model-reasoning final gate must display one proposed `Intensity:`
  value from `L1_SIMPLE`, `L2_EASY`, `L3_MEDIUM`, `L4_HARD`, `L5_INSANE`, or
  `L6_EXTREME`.
- When a non-trivial Markdown plan version is ready for human review, use the
  project `lavish-plan-review` skill. Its local `.lavish/` artifact is an
  annotatable comprehension companion; the Markdown plan remains canonical.
  Treat annotations as feedback, apply only human-approved corrections, and do
  not start execution from Lavish.
- The human may revise proposed intensities. Approved values are locked; the
  coordinator must not infer, raise, lower, or substitute them during execution.
- Apply the existing project high-risk, browser-QA, and review requirements at
  the relevant boundary. Commit, release, destructive operations, global
  installation, and missing operator secrets remain human gates.

## Portability and unknowns

- Never copy `.env`, operator-owned stage3 environment files, `rag-data/`,
  Docker volumes, `graphify-out/`, or local model caches between environments.
- Optional domain-owner scope: assigned subsystem plus its nearest `AGENTS.md`
  invariants; no permanent domain-owner mapping is currently identified.
- Unknown: the repository has no identified canonical plan/ledger filename or
  a checked-in command for provisioning stage3 operator secrets. Record any
  future decision in the appropriate project documentation rather than guessing.
