# Ingestion Guide

## Scope

`src/ingestion/` owns upload validation, parsing, chunking, embeddings,
document identity, and safe re-ingestion orchestration.

## Where To Look

| Task | Location | Notes |
| --- | --- | --- |
| HTTP ingestion flow | `router.py` | Owns upload actions and stored-file bookkeeping. |
| Strategy selection | `chunking_dispatch.py`, `strategies.py` | Preserve registered strategy names and bounds. |
| Strategy configuration | `chunking_models.py`, `chunking_settings.py` | Version and fingerprint persisted settings. |
| Parsing and embeddings | `parser.py`, `embedder.py` | Preserve source metadata and cancellation. |
| Chunk limits/segmentation | `chunk_limits.py`, `chunking_segmentation.py` | Keep size and overlap boundaries deterministic. |

## Conventions

- Every stored chunk retains document identity, strategy, fingerprint, location,
  and chunking settings needed by retrieval and re-ingestion.
- CSV remains row-based and uses its `csv_row` marker; do not route it through
  text chunking strategies.
- Replacement must publish the new complete document before stale data is
  removed, with rollback on failure or cancellation.

## Safety

- Validate ownership and traversal boundaries before reading stored files.
- Bound chunk counts and request work; do not bypass the existing limits.
