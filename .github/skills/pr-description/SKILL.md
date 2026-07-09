---
name: pr-description
description: Generates clean, structured pull request descriptions by analyzing git diffs. Triggered by "create a PR", "summarize changes for a PR", or "write PR description".
---

# PR Description Skill

## When to Use

Invoke this skill when the user says any of:
- "create a PR"
- "summarize changes for a PR"
- "write PR description"
- "generate PR description"
- "what should go in the PR description?"

---

## Workflow

### Step 1: Gather the Diff

Run the following command to get the full diff against the base branch:

```bash
git diff main --stat
```

Then get the detailed diff:

```bash
git diff main
```

If `main` is not the base branch, ask the user which branch to diff against.

### Step 2: Analyze the Changes

From the diff output, extract:
- **Changed files** — list every file added, modified, or deleted.
- **Change categories** — group changes by module (`src/api/`, `src/graph/`, `src/vector_store/`, `src/ingestion/`, `tests/`, `.github/`).
- **Key modifications** — summarize what changed in each file (new functions, refactors, fixes).
- **New dependencies** — any new packages or libraries introduced.
- **Breaking changes** — any API changes, schema migrations, or config format changes.

### Step 3: Determine the PR Type

Classify the PR into one of:

| Type | Prefix | When to Use |
|------|--------|-------------|
| `feat` | `feat:` | New feature or FR implementation |
| `fix` | `fix:` | Bug fix |
| `refactor` | `refactor:` | Code restructuring without feature changes |
| `docs` | `docs:` | Documentation only |
| `chore` | `chore:` | Tooling, CI, dependencies |
| `test` | `test:` | Adding or updating tests only |
| `perf` | `perf:` | Performance improvements |
| `security` | `security:` | Security fixes |

### Step 4: Write the PR Title

Format: `<type>: <imperative verb phrase>`

Examples:
- `feat: Add hybrid search with RRF fusion to Qdrant retriever`
- `fix: Resolve UUID5 collision when chunk index overflows`
- `refactor: Extract chunking logic into separate module`
- `chore: Add ruff, mypy, and bandit to QA pipeline`

Rules:
- Use imperative mood ("Add" not "Added").
- Keep under 72 characters.
- Capitalize after the colon.
- No period at the end.

### Step 5: Write the PR Body

Use this exact template:

```markdown
## Summary

<2-3 sentences describing the purpose of this PR. What problem does it solve?>

## Changes

### Added
- <list of new files, features, functions>

### Modified
- <list of changed files with brief description of what changed>

### Removed
- <list of deleted files or features>

## Files Changed

| File | Change | Module |
|------|--------|--------|
| `src/api/routes/chat.py` | Modified | `api` |
| `tests/api/test_chat.py` | Added | `tests` |

## Testing

- [ ] `pytest tests/ -v` passes (X/Y tests)
- [ ] `ruff check .` passes
- [ ] `mypy --strict src/` passes
- [ ] `bandit -r src/` passes
- [ ] RAGAS thresholds met (if applicable)

## Screenshots / Evidence

<If UI changes: paste before/after screenshots>
<If API changes: paste curl examples or response diffs>

## Linked Issues

- Closes #<issue number>
- Relates to FR-<XXX>

## Checklist

- [ ] All type hints present
- [ ] All public functions have docstrings
- [ ] No hard-coded secrets
- [ ] No file exceeds 500 lines
- [ ] Environment variables used for config
```

### Step 6: Output

Present the PR title and body to the user. Offer to copy it to clipboard or create the PR via `gh pr create`.

---

## Example Output

**PR Title:**
```
feat: Add ingestion pipeline with chunking and Qdrant upsert
```

**PR Body:**
```markdown
## Summary

Implements FR-001: Document Ingestion Pipeline. Adds a FastAPI endpoint for uploading documents, a chunking service that splits text into 512-token segments with 10% overlap, and a Qdrant upsert service using UUID5 deterministic IDs.

## Changes

### Added
- `src/ingestion/ingest.py` — FastAPI router with `/ingest` POST endpoint
- `src/ingestion/chunker.py` — RecursiveCharacterTextSplitter wrapper (512 tokens, 64 overlap)
- `src/vector_store/upsert.py` — Async Qdrant upsert with UUID5 IDs
- `tests/ingestion/test_ingest.py` — 4 tests covering AC-001.1 and AC-001.2

### Modified
- `src/api/main.py` — Registered ingestion router

## Files Changed

| File | Change | Module |
|------|--------|--------|
| `src/ingestion/__init__.py` | Added | `ingestion` |
| `src/ingestion/ingest.py` | Added | `ingestion` |
| `src/ingestion/chunker.py` | Added | `ingestion` |
| `src/vector_store/upsert.py` | Added | `vector_store` |
| `src/api/main.py` | Modified | `api` |
| `tests/ingestion/__init__.py` | Added | `tests` |
| `tests/ingestion/test_ingest.py` | Added | `tests` |

## Testing

- [x] `pytest tests/ -v` passes (6/6 tests)
- [x] `ruff check .` passes
- [x] `mypy --strict src/` passes
- [x] `bandit -r src/` passes

## Linked Issues

- Closes FR-001
```

---

## Anti-Patterns to Avoid

- **Vague titles** — "Fix stuff" or "Update code". Be specific.
- **No testing section** — always include test results.
- **Missing linked issues** — always link to FRs or issues.
- **Too much detail** — the diff is already visible; focus on *why* not *what*.
- **No file list** — always include a changed-files table.
