# RAG-Studio — Always-On Instructions

> **Rule:** All agents (@ba, @architect, @dev, @qa) MUST read this file before acting.

> **Live-checkout rule:** MUST USE ONLY THE ACTUAL CODE IN THE CURRENT CHECKOUT. Do not inspect, modify, create, switch, or rely on alternate, stale, prunable, or deleted branches/worktrees—or cached session memory—as the source of truth unless the user explicitly requests it.

---
#fetch https://masteringllm.medium.com/best-practices-for-rag-pipeline-8c12a8096453
#fetch https://cloud.google.com/blog/products/ai-machine-learning/optimizing-rag-retrieval
#fetch https://www.kapa.ai/blog/rag-best-practices

## Tech Stack (DO NOT CHANGE)

| Layer | Technology | Version |
|-------|-----------|---------|
| Language | Python | 3.14 |
| Backend | FastAPI (async) | latest |
| Agent Framework | LangGraph (StateGraph, async nodes, checkpointer) | latest |
| Vector DB | Qdrant (dense + sparse, hybrid search, RRF, reranker) | latest |
| Observability | LangSmith (traces, datasets, experiments, RAGAS) | latest |
| Testing | Pytest (unit + integration) | latest |
| UI | React + TypeScript + Tailwind CSS + shadcn/ui (approved SaaS migration target); retain legacy Jinja2 only until its replacement is planned | latest |

---

## File Boundaries

| Directory | Purpose | Owner |
|-----------|---------|-------|
| `src/` | Production code (FastAPI, LangGraph, Qdrant) | @dev |
| `tests/` | Pytest unit + integration tests | @dev + @qa |
| `system_spec.md` | Functional Requirements & Acceptance Criteria | @ba |
| `.agents/agents/` | Custom agent definitions | @architect |
| `.agents/skills/` | Reusable skill modules | @architect |

**Rule:** `src/` contains ONLY production code. `tests/` contains ONLY test code. Never mix them.

---

## Source Directory Structure

`src/` MUST contain ONLY these top-level directories:

| Directory | Purpose |
|-----------|---------|
| `src/api/` | FastAPI routes, middleware, dependencies, Jinja2 templates |
| `src/graph/` | LangGraph StateGraph, nodes, edges, state schemas |
| `src/vector_store/` | Qdrant client, collections, upsert, search, reranker |
| `src/ingestion/` | Document upload, parsing, chunking, embedding |
| `src/generate/` | LLM generation, prompt templates, output parsing |
| `src/retrieve/` | Retrieval logic, hybrid search orchestration |

**No other top-level folders are allowed in `src/`.** If a module doesn't fit these categories, discuss with @architect first.

---

## Python Type Annotations — Strict Mode

- **All functions MUST have complete type hints** on every parameter and return value.
- `mypy --strict` must pass with **zero errors**.
- No `# type: ignore` comments without a documented justification in a comment on the same line.
- Use `from __future__ import annotations` at the top of every file for forward references.
- Use `| None` syntax (Python 3.10+ union) for optional types, not `Optional[...]`.

```python
# CORRECT
from __future__ import annotations


async def search_documents(
    query: str,
    collection_name: str,
    limit: int = 20,
    filters: dict[str, str] | None = None,
) -> list[dict[str, object]]:
    """Search Qdrant collection and return ranked results."""
    ...


# WRONG — missing return type, bare Optional
async def search_documents(query, collection_name, limit=20, filters=None): ...
```

---

## File Size Limits

- **Source files must not exceed 500 lines.** Break large modules into smaller, focused files.
- **Test files must not exceed 300 lines** per test module (one test module per source module).
- If a function exceeds 50 lines, extract helper functions.
- If a class exceeds 200 lines, consider splitting into mixins or composition.

**How to break up a large module:**

```
# BEFORE (too large)
src/ingestion/ingest.py        # 620 lines

# AFTER (decomposed)
src/ingestion/router.py        # FastAPI endpoints (~80 lines)
src/ingestion/parser.py        # Document parsing (~120 lines)
src/ingestion/chunker.py       # Text splitting (~90 lines)
src/ingestion/embedder.py      # Embedding generation (~70 lines)
src/ingestion/__init__.py      # Re-exports (~15 lines)
```

---

## Security — Zero Hard-Coded Secrets

- **NEVER** commit API keys, tokens, passwords, or connection strings to source code.
- **ALWAYS** use environment variables via `os.getenv()` or `os.environ[]`.
- **ALWAYS** provide a `.env.example` file (without real values) when adding new environment variables.
- **ALWAYS** run `bandit -r src/` before committing. Zero high/medium findings required.
- Sensitive values include: `OPENAI_API_KEY`, `QDRANT_API_KEY`, `LANGCHAIN_API_KEY`, `DATABASE_URL`, `REDIS_URL`.

```python
# CORRECT
import os
from qdrant_client import AsyncQdrantClient

client = AsyncQdrantClient(
    url=os.getenv("QDRANT_URL", "http://localhost:6333"),
    api_key=os.getenv("QDRANT_API_KEY"),  # None if unset (no-auth mode)
)

# WRONG
client = AsyncQdrantClient(
    url="https://qdrant-prod.example.com",
    api_key="sk-abc123def456",  # NEVER DO THIS
)
```

---

## Definition of Ready (DoR)

A Functional Requirement is **ready for implementation** when:

1. The FR has at least 2 Gherkin Acceptance Criteria (ACs) in `system_spec.md`.
2. Each AC is independently testable.
3. All required skills are available. SaaS UI work additionally requires `frontend-design-director`, `design-system-style-intelligence`, and `react-shadcn-ui-contract`.
4. The architect has reviewed and approved the FR.
5. File paths for implementation are specified.

---

## Definition of Done (DoD)

A Functional Requirement is **done** when:

1. All ACs pass (`pytest` green).
2. RAGAS thresholds are met:
   - `faithfulness` > 0.7
   - `context_recall` > 0.8
   - `answer_relevancy` > 0.7
3. Code quality checks pass:
   - `ruff check .` — zero errors.
   - `ruff format --check .` — all files correctly formatted.
   - `mypy --strict src/` — zero type errors.
   - `bandit -r src/` — zero high/medium findings.
4. `DEV_RESULT` JSON is returned with `status: "done"`.
5. `QA_VERDICT` JSON is returned with `verdict: "PASS"`.
6. Code is merged to `main`.
7. LangSmith experiment results are recorded.

---

## NFR Thresholds

| Metric | Threshold |
|--------|-----------|
| Latency (p95) | < 3 seconds |
| Document scale | 1000 docs |
| Concurrent users | 10 |
| RAGAS faithfulness | > 0.7 |
| RAGAS context_recall | > 0.8 |
| RAGAS answer_relevancy | > 0.7 |

---

## Coding Conventions

- All Python code MUST use type hints.
- All public functions MUST have docstrings.
- Async/await throughout FastAPI and LangGraph nodes.
- Use `pydantic` models for all request/response schemas.
- Use `uuid.uuid5()` for deterministic Qdrant point IDs.
- Never commit secrets or API keys — use environment variables.
- Source files must not exceed 500 lines.
- `mypy --strict` must pass with zero errors.
- Run `ruff check . && ruff format --check .` before committing.

---

## Agent Workflow

### Mandatory engineering decision evidence

Every non-trivial change MUST record: (1) why the selected solution fits this
architecture, (2) its measured behavior and bounded failure mode under the
applicable load threshold, (3) at least two considered alternatives with
rejection reasons and revisit conditions, and (4) safety evidence covering
data preservation, secret/error redaction, cancellation or rollback, and the
exact automated checks run. Unmeasured claims that a design is scalable, safe,
or best do not satisfy Definition of Done.

### Global workflow integration

For substantial Codex work, use the globally installed `alexey-workflow` skill
and read `.agents/workflow-adapter.md` before planning or dispatching. The
global workflow defines lifecycle, roles, and routing; this repository defines
only its commands, domain constraints, and evidence requirements.

Every non-trivial executable plan must propose an explicit `Intensity:` for
each implementation task and each independent model-reasoning final gate from
`L1_SIMPLE`, `L2_EASY`, `L3_MEDIUM`, `L4_HARD`, `L5_INSANE`, or `L6_EXTREME`.
Human approval locks those values. The coordinator must not infer or change a
locked intensity during execution.

For every human-reviewable version of a non-trivial plan, use
`.agents/skills/SKILL.md` (`lavish-plan-review`) to create or refresh one local
annotatable companion in `.lavish/`. The Markdown plan remains canonical;
annotations are feedback and never start execution or replace human approval.

- Never report an implementation complete without recorded results from the relevant tests and quality checks.
- Never report any implementation complete without evidence from the Playwright
  MCP server `playwright_qa_2` from the running web application. Use only its
  structured interactions: navigate, snapshot, click, type/fill form, press
  keys, upload files, wait, resize, screenshot, and verification. Do not use
  `browser_run_code`, `browser_run_code_unsafe`, `browser_evaluate`, or
  arbitrary JavaScript/Playwright code. Do not use another Playwright MCP
  server, another browser-control mechanism, or a non-Playwright browser tool.
  Record the URL, scenario, observed result, viewport where relevant, and screenshots for
  visual changes. For backend-only work, exercise the closest web journey that
  consumes the changed behavior.

- For high-risk changes, run `.agents/skills/adversarial-review/SKILL.md` with
  the read-only `.agents/agents/adversarial-qa.md` after normal QA and before
  merge. The adversarial verdict must be `PASS`; `FAIL` and `INCONCLUSIVE`
  block merge. The reviewer must challenge invariants, boundaries, weak tests,
  fixtures, failures/timeouts, stale state, concurrency, security/data leaks,
  and applicable UI behavior rather than merely rerun green tests.

### Feature discussion before implementation

For non-trivial feature requests, invoke the project skill
`.agents/skills/feature-discussion/SKILL.md` before implementation. It starts
with current-checkout inspection, asks exactly one architecture question at a
time, and records the approved design in `CONTEXT.md`, `docs/adr/`, and
  `docs/features/<feature-slug>.md` before stopping for user approval. It is not
  needed for typo fixes, formatting, simple renames, or isolated one-line bug
  fixes. After approval, create the executable plan through `alexey-workflow`.

### SaaS UI skill chain

For **every UI task**, complete this mandatory nested pipeline during the
canonical implementation and testing stages:

```text
design-system-style-intelligence → frontend-design-director → react-shadcn-ui-contract → visual QA
```

The first two establish or update `DESIGN.md`; the contract skill governs all
new SaaS React UI. For the temporary legacy Jinja2 surfaces, apply the first
two design stages and use `ui-design` only for the existing implementation
mechanics. Do not write UI code until the applicable design stages are complete.
Run `omo:visual-qa` after every UI change and do not treat source inspection as
visual verification.
