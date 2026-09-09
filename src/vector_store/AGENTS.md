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
| Tenant isolation/cache | `tenant_store.py`, `tenant_cache.py` | Validate scope and collection; never accept browser-selected storage. |
| Strategy metadata | `strategy_payloads.py` | Canonical document/chunk payload builders. |

## Conventions

- Use domain records and contracts across module boundaries; contain raw Qdrant
  calls in adapter/translation code.
- Persist strategy and chunking metadata with document-index and vector payloads.
- Embedded Qdrant is local-first and intentionally single-container.
- Collection/search/upsert/delete operations flow through `VectorStore` and
  `VectorSearcher` protocols; callers do not construct SDK records.
- Preserve signed cursor, stable snapshot, page-size, and bounded search limits.
- Tenant cache keys, collection names, and search limits are validated domain
  values; keep cache hits and retrieval results tenant-bound.

## Anti-patterns

- Treat SDK and transport errors as unavailable/sanitized domain failures.
- Never delete old document data before a new replacement batch is committed.
- Do not leak Qdrant URLs, paths, payload text, or raw exception strings.
- Keep point-ID derivation in translation/persistence helpers; callers provide
  stable document identity rather than choosing random IDs.
- Do not mutate canonical payload metadata in retrieval-specific code.
- Do not let a route or client construct arbitrary collection names or point IDs.

## Verification focus

Run `pytest tests/vector_store tests/api/test_pagination_api.py
tests/api/test_document_index_pagination.py -v`; include rollback, cancellation,
cursor tampering, snapshot bounds, and legacy payload cases when relevant.
