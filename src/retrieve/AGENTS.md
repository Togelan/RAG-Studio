# Retrieval Guide

## Overview

`src/retrieve/` converts dense+sparse search hits into bounded, deduplicated,
citation-ready context units, then optionally reranks them for the graph.

## Where to look

| Task | Location | Notes |
| --- | --- | --- |
| Hybrid search/reranking | `orchestrator.py` | Qdrant RRF, FlashRank, safe fallback. |
| Strategy expansion | `context_expansion.py` | Parent/window expansion and final bounds. |
| Storage contracts | `src/vector_store/contracts.py` | Inject `VectorSearcher`; no SDK shapes. |
| Embedding contracts | `src/ingestion/embedding.py` | Retrieval consumes protocol values only. |

## Conventions

- `top_k` counts final context units, not raw child points. Enforce both the
  final result cap and character budget after expansion/deduplication.
- Expand `parent_document` from parent payloads and `sentence_window` from
  window payloads; unknown/missing strategy metadata is legacy `recursive`.
- CSV stays one row per context and reports location unavailable rather than
  manufacturing character offsets.
- Deduplicate deterministically by document, strategy, and expanded range/text;
  prefer higher score and stable point-ID ordering.
- Preserve source/location metadata for citations through reranking.
- Reranker absence/OOM may fall back to bounded RRF results; search absence or
  sanitized failure returns an empty result, never partial unbounded context.

## Anti-patterns

- Do not construct Qdrant SDK queries/results outside the vector-store adapter.
- Do not rerank raw child hits before strategy expansion and deduplication.
- Do not drop citation metadata, exceed the context budget, or log raw query,
  document text, model paths, provider exceptions, or transport details.
- Do not make retrieval own chunk formation or persisted strategy settings.

## Verification focus

Run `pytest tests/retrieve tests/graph/test_nodes.py -v`; cover legacy payloads,
all strategies, deterministic deduplication, budgets, score thresholds,
reranker fallback, empty/error results, and citation locations.
