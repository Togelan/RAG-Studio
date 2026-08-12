# Vector Store Guide

## Scope

`src/vector_store/` is the Qdrant adapter boundary for collection lifecycle,
document replacement, search, pagination, and payload translation.

## Where To Look

| Task | Location | Notes |
| --- | --- | --- |
| Application contracts and values | `contracts.py`, `models.py` | Keep callers independent of Qdrant SDK shapes. |
| SDK adapter and client lifecycle | `adapter.py`, `client.py` | Embedded mode persists through `src.paths`. |
| Qdrant conversion/errors | `qdrant_translation.py` | Sanitize provider failures to typed domain errors. |
| Re-ingestion atomicity | `document_replacement.py` | Preserve rollback and cancellation handling. |
| Document/chunk listing | `pagination.py`, `document_index.py` | Keep cursor/snapshot bounds stable. |

## Conventions

- Use domain records and contracts across module boundaries; contain raw Qdrant
  calls in adapter/translation code.
- Persist strategy and chunking metadata with document-index and vector payloads.
- Embedded Qdrant is local-first and intentionally single-container.

## Safety

- Treat SDK and transport errors as unavailable/sanitized domain failures.
- Never delete old document data before a new replacement batch is committed.
