# RAG-Studio architectural context

## Product boundary

RAG-Studio is a single-container, local-first personal RAG application. It is
not a SaaS or multi-tenant platform. Qdrant runs in embedded/local mode with
persistent storage; dense embeddings, BM25 embeddings, and FlashRank
reranking run locally. Only the configured answer-generation provider is an
external service.

## Chunking terminology

- **Static**: fixed character boundaries with configured overlap; no semantic
  separator selection.
- **Recursive**: the existing separator-aware splitter using paragraph,
  newline, sentence, space, and character fallbacks. This is the legacy
  default behavior.
- **Parent document**: sentence children are embedded and searched; the
  containing paragraph or bounded parent segment is returned. Child and parent
  metadata are retained together.
- **Sentence window**: sentence-level points are searched and expanded to a
  bounded set of neighboring sentences within the same paragraph.
- **Context unit**: the final deduplicated text passed to the LLM. `top_k`
  counts context units, not raw child points.

## Ownership and boundaries

`src/ingestion/` owns parsing, strategy selection, chunk formation, and
strategy metadata. `src/api/routes/settings.py` owns the persisted global
chunking configuration. `src/api/templates/settings.html` and the settings
JavaScript own conditional strategy controls. `src/vector_store/` owns Qdrant
translation, payload persistence, and bounded search. `src/retrieve/` owns
strategy-aware expansion, deduplication, reranking input, and final context
limits.

## Stable decisions

- Strategy selection is global for the project, not per document.
- Changing strategy keeps the existing FR-010 Skip/Re-ingest All behavior.
- Re-ingestion should replace documents one at a time without clearing the
  existing index first; failed documents retain their prior index.
- Existing documents without a strategy field are treated as legacy
  `recursive` and are migrated lazily.
- Static, recursive, and parent-document size controls use characters.
  Sentence-window controls use sentence counts.
- CSV files remain row-based and retain their current row metadata regardless
  of the selected text strategy.
- Strategy-specific settings are stored under a nested `chunking` object.
- The default strategy is `recursive`.
- Parent-document defaults are child `512` chars, child overlap `64`, parent
  `2048` chars. Sentence-window default is `±2` sentences. All controls are
  bounded presets.
- The document table exposes each document's actual strategy and parameters.
- Citations describe the final expanded context and preserve source/location
  ranges.

## Operational target

The host profile may provide Docker Desktop with 6 GB available memory, 4 CPU
cores, and at least 10 GB free disk; those host values are context only and are
not the benchmark or acceptance profile. The benchmark and operational target
are the Compose-limited service profile enforced by `docker-compose.yml`: 4 GB
memory and 2 CPU cores, with at least 10 GB free disk. Under that Compose
profile, the 50,000 indexed-point benchmark is informational, with p95
retrieval below 3 seconds reported where the machine and corpus permit;
memory, ingestion duration, and failure behavior are measured rather than
assumed.
