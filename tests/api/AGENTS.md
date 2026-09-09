# API Test Guide

## Scope

`tests/api/` is the largest integration boundary: FastAPI routes, application
composition, auth/tenancy, streaming, settings, billing, publication, UI, and
deployment contracts.

## Where To Look

| Task | Location | Notes |
| --- | --- | --- |
| App/route composition | `test_app.py`, route-focused modules | Build isolated apps and override dependencies. |
| Streaming/cancellation | `test_chat_*.py`, `test_mvp_widget_stream*.py` | Assert SSE protocol, redaction, cleanup, and reattach behavior. |
| SaaS persistence | `test_mvp_*_postgres.py` | Apply the full migration stack in disposable Postgres. |

## Conventions

- Build isolated `create_app()` instances and override/inject Qdrant, graph,
  provider, auth, storage, and runtime dependencies. Avoid shared mutable app
  state between cases.
- Assert status codes, response models, headers, SSE event names/payloads,
  cancellation/reattach behavior, and safe error text—not just happy-path JSON.
- Keep identity, workspace, role, collection, entitlement, and publication
  tests negative as well as positive; browser identifiers are not authority.
- Use purpose-built fakes for external services. Use Postgres-specific files for
  migration-backed behavior and tests under `tests/e2e/` for real pipeline flows.
- New route behavior should include bounded capacity/load, redaction, rollback,
  and cancellation coverage where applicable.

## Anti-patterns

- Do not import production code from another test module or rely on test order.
- Never assert raw provider/SDK exception text, secrets, paths, cookies, tokens,
  prompts, or document content in responses or evidence.
- Do not weaken the shared rate-limit isolation fixture; override it explicitly
  only when testing the limiter itself.
- Do not use broad mocks when a narrow protocol fake can verify the boundary.
- Keep route-contract fixtures local to this boundary unless another test domain
  genuinely consumes the same protocol.

## Commands

```powershell
pytest tests/api -v
pytest tests/api/test_mvp_* -v
```
