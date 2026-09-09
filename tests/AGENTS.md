# Test Guide

## Overview

`tests/` mirrors production domains and proves HTTP contracts, graph behavior,
ingestion/replacement safety, retrieval bounds, storage translation, deployment,
security, JavaScript SSE parsing, and the full local RAG pipeline.

## Structure

| Scope | Coverage |
| --- | --- |
| `api/` | FastAPI/TestClient, UI HTML/assets, SSE, settings, rate limits. |
| `graph/` | Topology, nodes, providers, retries, sessions, timeouts. |
| `ingestion/` | Parsing, strategies, embeddings, locking, filename security. |
| `retrieve/` | Expansion, budgets, reranking, failure fallback. |
| `vector_store/` | Contracts, Qdrant translation, replacement, pagination. |
| `e2e/` | Real temporary Qdrant, embeddings, checkpoints, graph. |
| `qa/`, `supabase/` | Disposable QA runtime and Postgres/schema contracts. |
| Root/`js/` | Cross-cutting security/deployment/paths and SSE parser. |

## Conventions

- Match tests to the owning source domain; name behavior and failure mode, not
  implementation steps. Keep Arrange/Act/Assert visible in complex cases.
- Use `pytest` async support, `tmp_path`, `monkeypatch`, and injected protocols.
  External LLM/Qdrant calls are mocked except explicit E2E/benchmark coverage.
- Keep test modules ≤300 lines. Split by behavior before adding to existing
  oversized modules; do not use their current size as precedent.
- Fixtures stay local until genuinely shared. Put shared domain fakes/factories
  in scoped `conftest.py` or helper modules, never import from another test file.
- Root `conftest.py` sets collection-time rate-limit isolation; dedicated
  rate-limit tests must override it deliberately.
- Registered markers are `unit`, `integration`, and `e2e`; strict markers are on.
- API route tests live in `tests/api/`; its local guide covers TestClient,
  dependency overrides, SaaS identity, billing, publication, and SSE contracts.

## Anti-patterns and required safety evidence

- Assert bounded capacity/load behavior and the exact exhausted-capacity result.
- Assert cancellation/rollback leaves prior data usable and no partial publish.
- Assert secrets, user text, paths, and raw provider/SDK errors are redacted.
- Assert legacy payload/config migration and deterministic metadata/citations.
- Use disposable data roots for embedded Qdrant and checkpoint tests.
- Apply Supabase migrations only in disposable Postgres; test ordering, RLS,
  permissions, rollback, preservation, and quota/concurrency invariants.

## Commands

```powershell
pytest tests/<domain> -v
pytest tests/ -v
node tests/js/test_sse_parser.mjs
```

Run targeted tests first. Full quality/type/security/Docker checks remain in the
root guide; Browser confirmation remains mandatory for implemented behavior.
