# API Guide

## Scope

`src/api/` contains FastAPI composition, routes, request models, templates,
static assets, and local encrypted settings/secrets handling.

## Where To Look

| Task | Location | Notes |
| --- | --- | --- |
| App lifecycle and route registration | `main.py` | Keep startup/shutdown ordering intact. |
| Shared dependencies and secret storage | `dependencies.py` | Encrypt at rest; redact error paths. |
| HTTP endpoint behavior | `routes/` | Match existing response/status contracts. |
| SaaS/Personal Lab boundaries | `routes/saas_*.py`, `routes/mvp_*.py`, `personal_lab_*.py` | Resolve identity/scope server-side; keep billing/publication projections safe. |
| UI assets/locales | `templates/`, `static/`, `locales/` | Legacy Jinja/vanilla JS contract. |
| Chat jobs/streaming | `chat_jobs.py`, `chat_stream.py`, `routes/chat.py` | Bounded jobs and SSE. |
| Rate limiting | `rate_limiter.py` | Per-IP sliding windows; `/health` exempt. |

## Conventions

- Route handlers validate and translate HTTP concerns; domain logic belongs in
  `ingestion`, `retrieve`, `graph`, or `vector_store`.
- Use injected dependencies for Qdrant/vector store access.
- Health/status endpoints must degrade safely when a backing service is absent.
- Settings changes that affect chunking require the re-ingest safety flow.
- Public widget routes require exact-origin proof, admission/quota reservation,
  bounded streaming, and proof-bound cancellation; widget keys are identifiers.
- Keep the startup chain ordered: Qdrant readiness, graph/checkpointer creation,
  chat-job shutdown, graph close, then Qdrant close.
- Preserve status codes, response models, SSE names/payloads, no-buffering
  headers, request/session IDs, and cancellation/reattach semantics.

## Legacy UI contract

- Pages are `/`, `/settings`, and `/chat`; templates share `base.html`.
- Preserve `data-i18n*` and `data-testid` hooks and exact `en.json`/`ru.json`
  key parity. Locale changes dispatch `ragstudio:locale-changed`.
- Chat script order is `app.js` → `sse.js` → `chat.js`; globals are
  `RAGStudio`, `RAGSse`, and `ChatApp` until the approved React parity stage.
- Preserve cache-version query strings unless regression tests change with them.
- Run the mandatory root UI design pipeline and Browser evidence for UI changes.

## Anti-patterns

- Never expose API keys, decrypted secrets, filesystem paths, or provider
  exception text in responses or logs.
- Never infer roles, entitlements, billing state, or publication authority from
  browser parameters, redirects, cookies, or public widget identifiers.
- Keep local-only origin and rate-limiting behavior intact.
- Never render unescaped user content, retry a stream after tokens were emitted,
  or remove stale-request/AbortController guards.
- Do not place ingestion, retrieval, graph, or raw Qdrant logic in route handlers.
