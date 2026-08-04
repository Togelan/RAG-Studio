# RAG-Studio Agent Guide

## Purpose and architecture

RAG-Studio is a Python 3.14 local-first RAG application: FastAPI/Jinja2 UI in
`src/api/`, LangGraph orchestration in `src/graph/`, ingestion in
`src/ingestion/`, retrieval in `src/retrieve/`, and Qdrant access in
`src/vector_store/`. Tests mirror these areas under `tests/`.

Read `.agents/copilot-instructions.md` and the relevant source and tests before
editing. That file remains the canonical project architecture, Definition of
Ready/Done, security, and coding-convention reference. The existing specialist
guidance lives in `.agents/skills/`, and the existing BA, architect, developer,
and QA roles remain documented in `.agents/agents/`.

**MUST USE ONLY THE ACTUAL CODE IN THE CURRENT CHECKOUT.** Do not inspect,
modify, create, switch, or rely on alternate, stale, prunable, or deleted
branches/worktrees—or cached session memory—as the source of truth unless the
user explicitly requests it.

## Canonical Codex workflow

For work that needs implementation, follow **understand → plan with LazyCodex →
implement → test → review → update Graphify → commit** in this order:

1. Understand the actual current checkout; use `$init-deep` when the repository
   shape or local guidance has changed.
2. Plan with LazyCodex using `$ulw-plan "<feature or bug>"` to create a decision-complete plan. Do not
   write product code during planning.
3. Implement with `$start-work [plan-name]` to execute the approved plan in small, atomic,
   reversible changes.
4. Test with `$ulw-loop "Verify the implementation, run all relevant tests, and fix remaining issues"`
   to gather verification evidence and resolve remaining issues.
5. Review with `$review-work` for the post-implementation review.
6. Update Graphify using the team's existing local workflow only when architecture
   or code-graph output needs refreshing; do not replace it with LazyCodex.
7. Commit only after review and relevant verification pass.

Use `$remove-ai-slops` only for behavior-preserving cleanup after tests are
green; it is not a substitute for implementation or review.

## Feature discussion gate

For non-trivial feature requests, use the project skill
`.agents/skills/feature-discussion/SKILL.md` first. A request such as “I want
to add ...” should begin with repository inspection and a one-question-at-a-
time architecture discussion. After consensus, the skill records stable
context in `CONTEXT.md`, important decisions in `docs/adr/`, and the approved
design in `docs/features/<feature-slug>.md`, then stops for user approval.

The skill is not required for typo fixes, formatting, simple renames, or
isolated one-line bug fixes. After the user approves the documents, the user
manually invokes `$ulw-plan`; do not automatically invoke `$ulw-plan`,
`$start-work`, `$ulw-loop`, or `$review-work` from the discussion skill.

## `$architect` single-prompt dispatch

When a user message starts with `$architect`, treat it as a request for the
project architect workflow—not as a request to implement product code directly.
This is the preferred front door for feature work in this repository.

1. Read the requested FR in `system_spec.md`, this file, and
   `.agents/copilot-instructions.md`. Return a Definition of Ready (DoR)
   verdict against the existing checklist.
2. If the FR is ready, create a bounded, file-scoped plan (use `$ulw-plan`
   when the LazyCodex skill is available). The plan must name acceptance
   criteria, affected files, tests, and verification commands.
3. Create one implementation subtask with the developer responsibilities in
   `.agents/agents/developer.md`. Give it only the files and acceptance
   criteria required by the plan. In Codex, use a LazyCodex worker role when
   available; otherwise describe the developer role explicitly in the task.
4. After the implementation subtask finishes, create an independent
   verification subtask using `.agents/agents/qa.md` and the LazyCodex QA role
   when available. QA must inspect the actual diff and run relevant tests; it
   must not rely only on the developer's report.
5. Return: DoR verdict, bounded plan, implementation summary, test/quality
   results, and blockers. Do not commit, merge, reset, discard, or overwrite
   changes unless the user explicitly requests it.

If the FR is not ready, stop after the DoR verdict and list the exact missing
requirements. Do not create implementation or QA subtasks. Keep subtasks
non-overlapping and do not let parallel agents edit the same files.

## Mandatory engineering decision evidence

For every non-trivial implementation, the plan, developer handoff, and QA
verdict must answer all of the following with measured or testable evidence:

1. Why this solution fits the current architecture and requirement.
2. How it behaves under the stated concurrency/load threshold, including the
   bounded failure mode when capacity is exhausted.
3. At least two considered alternatives, why they were rejected, and what
   future condition would justify revisiting them.
4. Why the change is safe: data preservation, secret/error redaction,
   cancellation/rollback behavior, and the exact automated checks performed.

Assertions such as "scalable", "safe", or "best" without a benchmark, limit,
test, or explicit trade-off are not completion evidence.

## Verification

Never claim completion without running the checks relevant to the change. The
baseline repository checks are:

```powershell
pytest tests/ -v
ruff check .
ruff format --check .
mypy --strict src/
bandit -r src/
docker compose build
```

Run targeted tests first; run the full suite and the applicable quality checks
before handoff. Preserve the existing tests, scripts, and Docker workflow.

## Safety and coexistence

- LazyCodex is a Codex-harness workflow only; never add it to
  `requirements.txt`, `pyproject.toml`, or application runtime images.
- Graphify remains the project-specific graph-analysis workflow. Its local
  output is `graphify-out/`, intentionally ignored by Git. Do not delete,
  disable, or commit that output, and do not add duplicate hooks or agents.
- Prefer existing patterns over new abstractions. Respect `src/`/`tests/`
  boundaries, strict typing, public docstrings, and the project file-size
  limits.
- Do not modify `.env`, deployment credentials, production data, or unrelated
  files. Ask before destructive operations or major architectural changes.
- Preserve unrelated working-tree changes. Use the existing project roles and
  skills when they add domain expertise; LazyCodex owns planning, execution,
  verification, and review orchestration in Codex.
