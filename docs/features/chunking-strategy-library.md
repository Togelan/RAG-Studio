# Chunking strategy library

## 1. Problem statement

RAG-Studio currently exposes one chunking behavior and global size/overlap
controls. Users need a transparent strategy library so they can choose how
documents are indexed and how retrieval context is assembled. The application
must remain a local, single-container personal RAG with bounded CPU, memory,
disk, and ingestion failure behavior.

## 2. Requirements and non-goals

### Requirements

- Add global strategy selection for `static`, `recursive`, `parent_document`,
  and `sentence_window`.
- Show only the selected strategy's parameters in the Settings UI.
- Keep `recursive` as the default and preserve the current behavior for legacy
  settings and documents.
- Use bounded preset controls and strategy-specific validation.
- Reuse the existing FR-010 Skip/Re-ingest All flow when strategy changes.
- Make re-ingestion non-destructive per document.
- Preserve CSV row-based ingestion.
- Support mixed-strategy retrieval from one searchable Qdrant collection.
- Persist strategy metadata and show it in the document table and citations.
- Keep final `top_k` semantics consistent across strategies.
- Mark CSV rows with the actual strategy `csv_row`, regardless of the selected
  text strategy.
- Use citation fallback `location_unavailable` when a parser cannot provide a
  usable source location range.
- Run the 50,000-point benchmark as informational evidence under the actual
  `docker-compose.yml` limits of 4 GB memory and 2 CPU cores.

### Non-goals

- No SaaS, multi-tenancy, distributed workers, queues, or new service.
- No Qdrant version upgrade in this feature.
- No second embedding, sentence-tokenization, or reranker model initially.
- No per-document strategy overrides in version one.

## 3. Current architecture and request flow

Settings are loaded and saved through `GET/POST /api/settings` and currently
persist flat `chunk_size` and `chunk_overlap` fields. The Settings page loads
those values, detects changes, and uses the FR-010 modal to skip or re-ingest.

Text ingestion flows through `src/ingestion/router.py`: parse the upload,
call `chunk_text`, generate dense and sparse vectors with the existing local
embedder, create Qdrant payloads, and atomically replace a document through the
vector-store adapter. CSV ingestion calls `chunk_csv_rows` and preserves row
metadata.

Hybrid retrieval embeds the query, searches named dense and sparse vectors in
one Qdrant collection, fuses results with RRF, optionally reranks with
FlashRank, and returns point payload text and metadata. The collection may
contain documents indexed with different strategies; retrieval expands
parent-document and sentence-window search units, deduplicates them, and
passes only final context units to reranking and generation.

## 4. Proposed architecture

Add a strategy dispatcher in the ingestion boundary. `static` performs fixed
character slicing with overlap. `recursive` retains the current separator
aware splitter. `parent_document` creates sentence children within paragraph
parents, merges short sentences up to the child limit, and bounds oversized
parents. `sentence_window` creates sentence points and expands matches within
the same paragraph by the configured window.

Use one Qdrant document collection. Search units carry enough payload metadata
to expand results without a second collection lookup. Retrieval expands and
deduplicates before reranking/generation and trims to the final context-unit
`top_k` and hard context budget.

## 5. Domain model and ownership

The global `ChunkingSettings` owns the active strategy and its validated
parameters. A persisted document owns its immutable strategy metadata for the
index version that produced its points. A `SearchUnit` is the embedded point;
a `ContextUnit` is the final text returned to the LLM. Ingestion owns
SearchUnit creation; retrieval owns ContextUnit expansion and deduplication.

## 6. Files/modules likely to change

- `src/api/routes/settings.py`: nested settings model, legacy migration, change
  detection, response contract.
- `src/api/templates/settings.html`: strategy selector and conditional panels.
- `src/api/static/js/app.js`: strategy state, conditional controls, save and
  re-ingestion behavior.
- `src/api/locales/en.json`, `src/api/locales/ru.json`: labels, help text,
  errors, and document strategy display.
- `src/ingestion/chunker.py`: static splitter, dispatcher, sentence and
  paragraph segmentation, parent/window builders.
- `src/ingestion/router.py`: strategy settings flow, payload metadata,
  per-document replacement, progress and failure reporting.
- `src/vector_store/models.py`, `src/vector_store/adapter.py`: strategy-aware
  document metadata and payload translation.
- `src/retrieve/orchestrator.py` and related retrieval code: expansion,
  deduplication, context budgets, and citation ranges.
- Relevant ingestion, settings, vector-store, retrieval, i18n, and UI tests.

No application code is changed during this discussion phase.

## 7. API and database changes

Persist a nested object while reading legacy fields:

```json
{
  "chunking": {
    "schema_version": 1,
    "strategy": "recursive",
    "chunk_size": 512,
    "chunk_overlap": 64
  }
}
```

Strategy-specific examples include `parent_size` for parent-document and
`window_sentences` for sentence-window. Inactive strategy values are not sent
as active configuration. Existing flat fields remain readable during migration.

Qdrant payloads add strategy, schema version, search-unit type, parent/sentence
identifiers, and location ranges as applicable. Existing points without these
fields are interpreted as legacy recursive points. CSV rows retain their row
and header metadata and use the actual strategy marker `csv_row`, even when a
different global text strategy is selected. A citation whose parser cannot
provide a usable location range uses `location_unavailable`; the system never
invents an offset. No relational database or schema migration is required.

## 8. Security analysis

Validate all strategy names and numeric presets at the Pydantic/API boundary.
Enforce overlap and parent/window bounds, maximum chunks per document, maximum
expanded context, and maximum parent text. Do not expose document content in
logs. Preserve existing secret redaction and API-key handling. Treat expanded
document text as untrusted prompt input and retain existing prompt-injection
robustness tests. Keep Qdrant local by default and do not introduce new
networked dependencies.

## 9. Scalability and heavy-load analysis

The acceptance profile is the actual `docker-compose.yml` configuration: 4 GB
memory and 2 CPU cores, with local persistent storage. The 50,000 indexed
point benchmark is informational, not a hard acceptance gate or a universal
SLA. Measure ingestion duration, peak memory, persisted payload size, p95
hybrid retrieval latency, and chat behavior during ingestion, and report the
observed limits and failures. The existing 10-user NFR is a resilience bound,
not a SaaS scaling target.

Parent text duplication is bounded by parent presets. Sentence strategies can
increase point counts, so embedding batches and per-document chunk counts stay
bounded. Retrieval oversampling is bounded before expansion; final contexts are
deduplicated and limited by `top_k` and a hard character/token budget.

Qdrant 1.18 introduces memory reporting, low-memory mode, and resident-memory
guardrails that are relevant to future local diagnostics, but the feature must
not depend on an unverified Qdrant upgrade. Validate behavior against the
current embedded client/runtime first.

## 10. Error-handling strategy

Malformed or poorly formatted text uses deterministic paragraph/sentence
fallbacks and then bounded character splitting. A strategy configuration error
is rejected without changing saved settings. A failed document re-ingestion
keeps the previous document index and records a sanitized failure code. Other
documents continue. Resource exhaustion stops the affected operation at its
bound and reports a recoverable error; it must not clear the whole index.

## 11. Observability strategy

Extend existing progress and audit logging with strategy, search-unit count,
context expansion count, duration, and sanitized failure codes. Show strategy
and parameters in the document table. Do not add Prometheus/OpenTelemetry or a
metrics service for this local product. Preserve source/location metadata for
citations and troubleshooting.

## 12. Testing strategy

- Unit tests for each splitter, bounds, overlap, paragraph/sentence fallback,
  CSV preservation, deterministic IDs, and strategy metadata.
- API tests for nested settings, legacy flat migration, invalid combinations,
  conditional change detection, and response compatibility.
- Integration tests for one mixed-strategy Qdrant collection, parent/window
  expansion, deduplication, final `top_k`, CSV `csv_row` metadata,
  `location_unavailable` citations, and per-document replacement failure.
- UI/i18n tests for strategy-first controls, inactive parameter visibility,
  draft-value preservation, document strategy display, and re-ingestion flow.
- Security tests for oversized parameters, untrusted text, secret/error
  redaction, and prompt-injection behavior.
- Informational benchmark/manual test at 50,000 points under the actual
  Compose profile (4 GB/2 CPU), recording resource and failure measurements
  without labeling the result a universal pass or SLA.

## 13. Migration and rollback plan

Read legacy flat settings as recursive settings and write the nested form on
the next successful save. Treat legacy points as recursive without rebuilding
them solely for metadata. New uploads use the selected global strategy. A
strategy change uses the existing Skip/Re-ingest All confirmation; re-ingest is
per-document and non-destructive. Rollback disables new strategies and retains
the recursive path and existing payloads.

The Qdrant dependency/runtime upgrade is a separate change with its own
compatibility, storage, and rollback verification.

## 14. Unresolved assumptions

- Exact parser behavior for paragraph boundaries in every supported document
  format requires characterization tests.
- The 50,000-point benchmark result depends on the user's actual CPU, memory,
  disk, and corpus; the stated profile is the baseline, not a universal SLA.
- The current embedded Qdrant client must be checked for availability of any
  Qdrant 1.18 memory controls before they are exposed.
- Citation location ranges may be unavailable for formats that lose page or
  section offsets during extraction; emit `location_unavailable` in that case.
- Mixed-strategy retrieval is intentionally one collection-wide contract;
  document-specific configuration remains out of scope for version one.

## 15. Explicit acceptance criteria

1. Settings can select `static`, `recursive`, `parent_document`, or
   `sentence_window`; only active strategy parameters are visible and
   validated.
2. Existing recursive behavior remains the default and legacy documents are
   classified as recursive without forced rebuild.
3. Static splitting is fixed-size with overlap; recursive splitting preserves
   the current separator behavior.
4. Parent-document searches sentence children and returns bounded, deduplicated
   paragraph/parent context with child/parent metadata.
5. Sentence-window searches sentences and returns bounded same-paragraph
   windows with deduplicated sentence ranges.
6. CSV rows remain atomic with existing metadata.
7. `top_k` counts final contexts sent to the LLM.
8. Strategy changes retain Skip/Re-ingest All behavior, and re-ingestion never
   clears the whole index before successful per-document replacement.
9. Existing and new document rows/citations show accurate strategy and
   strategy-specific location metadata, including CSV `csv_row` and the
   `location_unavailable` fallback.
10. Retrieval can mix strategies in one searchable collection while returning
    only deduplicated, bounded final context units.
11. Tests cover validation, migration, security, failures, and an informational
    50,000-point benchmark under the actual 4 GB/2 CPU Compose limits.

## 16. Manual testing scenarios

1. Open Settings, select each strategy, verify only its parameters appear, and
   switch back to confirm unsaved values are preserved.
2. Save a strategy change with no documents and verify silent save.
3. Save a strategy change with documents, choose Skip, and verify old documents
   retain their strategy while a new upload uses the selected strategy.
4. Choose Re-ingest All, interrupt or make one source unreadable, and verify
   other documents continue while the failed document's previous index remains.
5. Upload a long paragraph using parent-document and verify search returns one
   deduplicated paragraph context with child/parent citation metadata.
6. Query a sentence-window document near a paragraph boundary and verify the
   window does not cross into the next paragraph.
7. Upload a CSV and verify rows, headers, and row metadata remain intact under
   every selected strategy, with actual strategy marker `csv_row`.
8. Query a collection containing documents indexed with multiple strategies and
   verify expansion, deduplication, final `top_k`, and citations; use
   `location_unavailable` when a source range is absent.
9. Run the informational 50,000-point benchmark under the actual 4 GB/2 CPU
   Compose profile and record memory, disk, ingestion duration, p95 retrieval
   latency, chat behavior during ingestion, and any bounded failures.
