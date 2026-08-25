# Ingestion Guide

## Scope

`src/ingestion/` owns upload validation, parsing, chunking, embeddings,
document identity, and safe re-ingestion orchestration.

## Where To Look

| Task | Location | Notes |
| --- | --- | --- |
| HTTP ingestion flow | `router.py` | Owns upload actions and stored-file bookkeeping. |
| Personal Knowledge flow | `personal_router.py`, `personal_storage.py` | Uses only the authenticated server-resolved Personal Lab scope. |
| Strategy selection | `chunking_dispatch.py`, `strategies.py` | Preserve registered strategy names and bounds. |
| Strategy configuration | `chunking_models.py`, `chunking_settings.py` | Version and fingerprint persisted settings. |
| Parsing and embeddings | `parser.py`, `embedder.py` | Preserve source metadata and cancellation. |
| Chunk limits/segmentation | `chunk_limits.py`, `chunking_segmentation.py` | Keep size and overlap boundaries deterministic. |
| File admission/storage | `document_admission.py` | Own path traversal and filename checks. |

## Conventions

- Every stored chunk retains document identity, strategy, fingerprint, location,
  and chunking settings needed by retrieval and re-ingestion.
- CSV remains row-based and uses its `csv_row` marker; do not route it through
  text chunking strategies.
- Replacement must publish the new complete document before stale data is
  removed, with rollback on failure or cancellation.
- Strategy settings are scoped per Personal Lab and nested under `chunking`.
  Legacy settings remain global; missing Legacy strategy metadata means
  `recursive` and migrates lazily.
- Static/recursive/parent sizes are characters; sentence-window sizes are
  sentence counts. `top_k` downstream counts final context units.

## Anti-patterns

- Validate ownership and traversal boundaries before reading stored files.
- Bound chunk counts and request work; do not bypass the existing limits.
- Do not clear an existing document/index before its replacement is complete.
- Do not send CSV rows through text strategies or drop `csv_row` metadata.
- Do not cache a failed model initialization or translate cancellation into a
  generic model/ingestion failure.
- Do not accept Personal Lab scope, collection, raw-file root, cursor scope, or
  progress ownership from a browser-controlled value.

## Verification focus

Run `pytest tests/ingestion tests/api/test_settings_reingest.py -v`; include
locking, filename security, strategy migration, metadata, cancellation, and
replacement-failure cases for affected flows.
