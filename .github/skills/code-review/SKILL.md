---
name: code-review
description: Structured code review invoked by @qa or manually. Checks naming conventions, cyclomatic complexity, error handling, docstrings, and tech stack adherence. Returns findings with severity levels (critical, warning, suggestion).
---

# Code Review Skill

## When to Use

Invoke this skill when:
- @qa runs the full QA pipeline (Phase 4 — Code Review).
- @architect requests a review before merging.
- The user says "review this code", "code review", or "check my code".
- After @dev returns `DEV_RESULT` and you want to verify code quality.

---

## Review Checklist

### 1. Naming Conventions

| Rule | Severity | Description |
|------|----------|-------------|
| Snake_case for functions and variables | `warning` | `def my_function()` not `def MyFunction()` or `def myFunction()` |
| PascalCase for classes | `warning` | `class QdrantStore` not `class qdrant_store` |
| UPPER_CASE for constants | `warning` | `MAX_CHUNK_SIZE` not `max_chunk_size` |
| Private prefix `_` for internal functions | `suggestion` | `def _internal_helper()` for module-private helpers |
| Descriptive names (no single-letter vars except loops) | `warning` | `for chunk in chunks:` not `for c in cs:` |
| No abbreviations in public API | `suggestion` | `get_document()` not `get_doc()` unless `doc` is a well-known domain term |

### 2. Cyclomatic Complexity

| Threshold | Severity | Action |
|-----------|----------|--------|
| 1–5 | — | OK, no action needed |
| 6–10 | `suggestion` | Consider extracting helper functions |
| 11–15 | `warning` | Should refactor — extract conditionals or loops |
| 16+ | `critical` | Must refactor before merge |

Count branches manually or use `radon cc src/ -a`:

```bash
pip install radon
radon cc src/ -a -s
```

### 3. Error Handling

| Check | Severity if Missing |
|-------|---------------------|
| All `await` calls inside `try/except` blocks (for external services) | `critical` |
| Specific exception types caught (never bare `except:`) | `warning` |
| Error messages include context (what operation failed, why) | `suggestion` |
| FastAPI endpoints return proper HTTP status codes (4xx/5xx) | `warning` |
| No `pass` in except blocks (swallowing errors silently) | `critical` |
| LangGraph nodes return graceful fallbacks, not unhandled exceptions | `critical` |

```python
# CORRECT
try:
    results = await client.search(...)
except qdrant_client.http.exceptions.UnexpectedResponse as e:
    logger.error(f"Qdrant search failed for query '{query}': {e}")
    raise HTTPException(status_code=502, detail="Vector store unavailable")

# WRONG
try:
    results = await client.search(...)
except:
    pass  # Silent failure, no logging, no fallback
```

### 4. Docstrings

| Check | Severity if Missing |
|-------|---------------------|
| All public functions have docstrings | `warning` |
| Docstring includes `Args:` and `Returns:` sections (Google style) | `suggestion` |
| Docstring describes *why*, not just *what* | `suggestion` |
| Module-level docstring at top of each file | `suggestion` |

```python
# CORRECT (Google-style docstring)
async def upsert_chunks(
    client: AsyncQdrantClient,
    chunks: list[dict[str, object]],
    collection_name: str,
) -> int:
    """Insert or update document chunks in Qdrant.

    Uses UUID5 deterministic IDs to enable idempotent upserts.

    Args:
        client: An initialized AsyncQdrantClient instance.
        chunks: List of chunk dicts, each with keys: text, metadata, dense_vector, sparse_vector.
        collection_name: The target Qdrant collection name.

    Returns:
        The number of points successfully upserted.
    """
```

### 5. Tech Stack Adherence

| Check | Severity if Violated |
|-------|----------------------|
| Async/await used for all FastAPI endpoints and LangGraph nodes | `critical` |
| pydantic models used for all request/response schemas | `critical` |
| `uuid.uuid5()` used for Qdrant point IDs | `warning` |
| Type hints on all function signatures | `warning` |
| No hard-coded secrets (API keys, tokens) | `critical` |
| `from __future__ import annotations` at top of each file | `suggestion` |
| No file exceeds 500 lines | `warning` |

### 6. Code Smells

| Smell | Severity | Description |
|-------|----------|-------------|
| Duplicated code (>5 lines identical) | `warning` | Extract shared logic into a utility function |
| Magic numbers (unexplained literals) | `warning` | Use named constants (e.g., `MAX_CHUNK_SIZE = 512`) |
| Too many parameters (>5) | `suggestion` | Consider grouping into a pydantic model or dataclass |
| Deep nesting (>3 levels) | `warning` | Use early returns or extract nested blocks |
| Side effects in getters/properties | `warning` | Properties should not mutate state |
| Dead code (unused imports, functions, variables) | `warning` | Remove or document why kept |

---

## Review Output Format

Return findings in this structure:

```json
{
  "module": "src/ingestion/",
  "filesReviewed": [
    "src/ingestion/ingest.py",
    "src/ingestion/chunker.py",
    "src/ingestion/parser.py"
  ],
  "summary": {
    "critical": 0,
    "warning": 3,
    "suggestion": 5
  },
  "findings": [
    {
      "file": "src/ingestion/chunker.py",
      "line": 42,
      "severity": "warning",
      "category": "complexity",
      "message": "Function `split_document` has cyclomatic complexity of 12. Consider extracting the page-detection logic into `_detect_page_breaks()`.",
      "recommendation": "Extract page boundary detection into a separate helper function to reduce branching."
    },
    {
      "file": "src/ingestion/ingest.py",
      "line": 78,
      "severity": "suggestion",
      "category": "docstring",
      "message": "Function `ingest_file` is missing a docstring. Add a Google-style docstring with Args and Returns.",
      "recommendation": "Add:\n\"\"\"Ingest a single file into the RAG pipeline.\n\nArgs:\n    file: The uploaded file object.\n    collection_name: Target Qdrant collection.\n\nReturns:\n    IngestionResult with doc_id and chunk count.\n\"\"\""
    },
    {
      "file": "src/ingestion/parser.py",
      "line": 15,
      "severity": "warning",
      "category": "error-handling",
      "message": "Bare `except:` on line 15 catches all exceptions including KeyboardInterrupt. Catch specific exception types.",
      "recommendation": "Replace `except:` with `except (ValueError, IOError, PDFParseError) as e:`."
    }
  ],
  "overallVerdict": "APPROVE_WITH_SUGGESTIONS"
}
```

### Severity Levels

| Severity | Meaning | Required Action |
|----------|---------|-----------------|
| `critical` | Must fix before merge | Block merge until resolved |
| `warning` | Should fix before merge | Fix or provide documented justification |
| `suggestion` | Nice to have | Optional, at @dev's discretion |

### Overall Verdicts

| Verdict | Meaning |
|---------|---------|
| `APPROVE` | No findings or only suggestions. Ready to merge. |
| `APPROVE_WITH_SUGGESTIONS` | Warnings present. @architect decides if they are blocking. |
| `REQUEST_CHANGES` | Critical findings present. Must fix before re-review. |

---

## How to Perform the Review

1. **Read** `.github/copilot-instructions.md` for current conventions.
2. **Run** `git diff main --name-only` to identify changed files.
3. **Read** each changed file in full.
4. **Apply** the checklist above to each file.
5. **Run** automated checks where possible:
   ```bash
   ruff check src/
   mypy --strict src/
   radon cc src/ -a -s   # cyclomatic complexity
   ```
6. **Compile** findings into the structured JSON output.
7. **Assign** an overall verdict.

---

## Integration with QA Pipeline

When invoked by @qa, the code review is Phase 4 of the QA workflow. The review output is embedded in `QA_VERDICT.codeReview`:

```json
{
  "codeReview": {
    "invoked": true,
    "summary": {"critical": 0, "warning": 3, "suggestion": 5},
    "findings": [...],
    "overallVerdict": "APPROVE_WITH_SUGGESTIONS"
  }
}
```

If `overallVerdict` is `REQUEST_CHANGES`, @qa must set `QA_VERDICT.verdict` to `FAIL` regardless of other results.
