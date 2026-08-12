# Source Guide

## Scope

`src/` holds production-only Python for the local-first FastAPI application.
Keep module ownership aligned with the root guide: API, graph, ingestion,
retrieval, generation, and vector storage are separate boundaries.

## Where To Look

| Task | Location | Notes |
| --- | --- | --- |
| Application startup and router registration | `api/main.py` | Owns lifespan and service wiring. |
| Request validation and HTTP contracts | `api/` | Routes stay thin; dependencies own shared wiring. |
| Ingestion and re-ingestion | `ingestion/` | Preserve chunk metadata and replacement rollback semantics. |
| Retrieval orchestration | `retrieve/`, `graph/` | Keep bounded contexts, citations, and cancellation behavior. |
| Qdrant boundary | `vector_store/` | Use vendor-neutral contracts and sanitized errors. |

## Conventions

- Python 3.14, strict MyPy, complete type annotations, and public docstrings.
- Keep FastAPI handlers asynchronous and delegate domain work to their owning
  module rather than duplicating storage or chunking logic.
- Default paths must use `src.paths`; never derive persistent paths from CWD.
- The running product is one Docker container with embedded persistent Qdrant.

## Safety

- Never log plaintext secrets or return provider exception text to callers.
- Preserve document replacement rollback and cancellation propagation.
- Do not add application code outside the established top-level source areas.
