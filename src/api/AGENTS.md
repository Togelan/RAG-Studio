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
| UI assets | `templates/`, `static/` | Preserve the established Jinja2/vanilla JS design. |
| Chat session limits | `chat_state.py`, `routes/chat.py` | Preserve bounded cache and job semantics. |

## Conventions

- Route handlers validate and translate HTTP concerns; domain logic belongs in
  `ingestion`, `retrieve`, `graph`, or `vector_store`.
- Use injected dependencies for Qdrant/vector store access.
- Health/status endpoints must degrade safely when a backing service is absent.
- Settings changes that affect chunking require the re-ingest safety flow.

## Safety

- Never expose API keys, decrypted secrets, filesystem paths, or provider
  exception text in responses or logs.
- Keep local-only origin and rate-limiting behavior intact.
