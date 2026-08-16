# Source Guide

## Scope

`src/` holds production-only Python for the local-first FastAPI application.
Keep module ownership aligned with the root guide: API, graph, ingestion,
retrieval, generation, and vector storage are separate boundaries.

## Structure

| Boundary | Owns | Does not own |
| --- | --- | --- |
| `api/` | HTTP, app wiring, settings, current UI | Chunk/search/storage algorithms |
| `graph/` | RAG state, nodes, routing, sessions | HTTP response contracts |
| `ingestion/` | Admission through embedded chunks | Qdrant SDK translation |
| `retrieve/` | Search orchestration and final contexts | Raw document parsing |
| `vector_store/` | Domain storage contracts and Qdrant | Route/business policy |
| `generate/` | Reserved generation boundary | Current graph-node implementation |

## Where To Look

| Task | Location | Notes |
| --- | --- | --- |
| Application startup and router registration | `api/main.py` | Owns lifespan and service wiring. |
| Request validation and HTTP contracts | `api/` | Routes stay thin; dependencies own shared wiring. |
| Ingestion and re-ingestion | `ingestion/` | Preserve chunk metadata and replacement rollback semantics. |
| Retrieval orchestration | `retrieve/`, `graph/` | Keep bounded contexts, citations, and cancellation behavior. |
| Qdrant boundary | `vector_store/` | Use vendor-neutral contracts and sanitized errors. |

## Conventions

- Keep FastAPI handlers asynchronous and delegate domain work to their owning
  module rather than duplicating storage or chunking logic.
- Route persistent path decisions through `src.paths`; pass resolved paths into
  owning modules rather than recomputing them.
- The running product is one Docker container with embedded persistent Qdrant.
- Cross-boundary dependencies use protocols/domain records rather than vendor
  SDK types. Inject embedders, vector stores, and providers for tests.
- Keep bounded concurrency and cancellation behavior explicit at every async
  resource boundary.

## Anti-patterns

- Never log plaintext secrets or return provider exception text to callers.
- Preserve document replacement rollback and cancellation propagation.
- Do not add application code outside the established top-level source areas.
- Do not import from `tests/`, duplicate canonical metadata builders, or bypass
  the API/vector-store dependency boundaries.
- Do not silently broaden context, retry, pagination, chunk, or job limits.
