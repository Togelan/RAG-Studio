# RAG-Studio contributor guidance

RAG-Studio is a local-first document-chat application. Its backend is FastAPI,
the workflow is LangGraph, and retrieval uses Qdrant with dense and sparse
vectors. The browser UI is Jinja2 with vanilla JavaScript and CSS.

## Work style

- Inspect the relevant implementation and its focused tests before changing behavior.
- Keep changes small and scoped; reuse existing patterns instead of adding frameworks or speculative abstractions.
- Preserve user changes already present in the worktree. Do not discard unrelated work.
- Keep secrets in environment variables and never print or commit `.env`.

## Repository layout

- `src/api/`: FastAPI app, routes, middleware, templates, and static assets.
- `src/graph/`: LangGraph state, nodes, and graph construction.
- `src/ingestion/`: upload handling, parsing, chunking, and embeddings.
- `src/retrieve/`: retrieval orchestration.
- `src/vector_store/`: Qdrant client and persistence.
- `tests/`: Pytest tests, generally mirroring `src/` modules.

Do not put production code in `tests/` or test helpers in `src/`.

## Code conventions

- Use `from __future__ import annotations`, complete type hints, and docstrings for public functions in new or materially changed Python modules.
- Use async endpoints and async external I/O where the existing API requires it.
- Use Pydantic models for API request and response schemas.
- Prefer explicit exception handling and useful context in logs. Never swallow exceptions or hard-code credentials.
- Keep UI changes within `src/api/templates/`, `src/api/static/css/`, `src/api/static/js/`, and locale JSON as applicable. Keep English and Russian locale keys aligned.

## Verification

Run the narrowest relevant tests first, then broaden when practical:

```powershell
python -m pytest tests/<area> -q
python -m pytest -q
python -m ruff check src tests
python -m ruff format --check src tests
python -m mypy src
python -m bandit -r src
```

Report commands that could not run and why. LangSmith/RAGAS evaluation is an opt-in release evaluation: run it only when credentials, a representative dataset, and the requested scope are available.

## Codex workflow

Use the task to decide the role needed: `ba` for requirements, `architect` for a Definition-of-Ready check and delegation, `dev` for implementation, and `qa` for verification. These are invokable skills, not permanently running subagents. Ask Codex to delegate only when the work has genuinely independent, bounded parts. For reviews, use `/review` or explicitly name the base branch, commit, files, and criteria.

Repository skills live in `.agents/skills/`. Keep their front-matter descriptions short and specific so Codex can select them correctly.

## Graph update lifecycle

- During implementation, run `.\\scripts\\watch_graph.ps1` in a separate terminal so code-graph changes are refreshed as files change.
- After the requested tests pass and before staging or committing, run `.\\scripts\\update_graph.ps1` once to capture the final state.
- Include the resulting `graphify-out/` changes in the same commit as the code they describe. If the update cannot run, report that as a verification blocker instead of claiming the graph is current.

## LazyCodex-style task loop

LazyCodex is an optional workflow layer over Codex. It does not replace the
repository skills or create permanent `@dev`/`@qa` processes.

For non-trivial work use: **understand → plan → implement → test → review →
update graph → commit**. Use `ba` for requirements, `architect` for
Definition-of-Ready and design, `dev` for bounded implementation, and `qa` for
verification. Use `/plan` and `/review` (or LazyCodex equivalents) when useful.

Before implementation record the goal, constraints, acceptance criteria,
affected files, and verification commands. After tests and review pass, run
`.\scripts\update_graph.ps1`, inspect the complete diff including
`graphify-out/`, and only then stage or commit. Never treat an agent response
as evidence without command output. For a small obvious fix, normal Codex plus
a focused skill is sufficient.

## Default task command

When the user says **“create task <name>”**, create `codex/<task-name>` from
`develop`, run `architect`, implement with `dev` if ready, verify with `qa`,
run `.\scripts\update_graph.ps1`, and report changed files, test results,
risks, and the final diff. Stop for explicit approval before staging,
committing, pushing, or merging. If the task is not ready, explain what is
missing and do not modify production code.
