# Group 2 Personal Lab: approved partial FR-023 contract

## 1. Problem statement

The unified React shell needs a private Personal Lab with the existing RAG
workflow, but the current Legacy persistence is host-global. Group 2 must
deliver private parity without silently assigning or moving existing data.

## 2. Requirements and non-goals

This is FR-023 AC-023.1 only: private identity-scoped documents, RAG settings,
retrieval/citations, streaming/cancellation/reattach, feedback, and sessions
in React. It excludes automatic Legacy migration/deletion, Workspace knowledge,
billing, Widgets, and AC-023.2 Agent promotion/copy, which Group 5 owns.

## 3. Current architecture and request flow

Group 1 supplies the cookie-authenticated React `/app` shell and explicit
Legacy rollback. The Legacy settings, ingestion, vectors, and chat paths are
host-global. The FastAPI BFF is the trusted boundary; browser-held state cannot
authorize a Personal Lab resource.

## 4. Proposed architecture

Resolve a stable opaque server-owned scope only after BFF identity
revalidation. Mount React-only Personal Lab APIs below `/api/personal/*` and
adapt the existing workflow behind that scope. Valid runtime combinations are
`saas + react` (Personal/BFF APIs) and `local + legacy` (host-global Legacy
APIs); cross-combinations fail startup with a sanitized configuration action.

## 5. Domain model and ownership

`personal_labs(id, user_id unique, created_at)` maps an authenticated user to
an opaque scope. The API layer owns identity, CSRF/Origin, route composition,
and scope resolution; ingestion owns scoped source formation; vector storage
owns scoped collections; graph/chat own scoped execution/checkpoints; React
only renders and calls the trusted boundary.

## 6. Files/modules likely to change

Later todos own the scoped API composition, settings, graph execution,
ingestion/retrieval, chat state, and React Personal Lab adapters described in
`.omo/plans/group-2-personal-lab.md`. This Todo intentionally changes no
product module.

## 7. API and database changes

The future registry provides a server-generated UUID scope. `/api/personal/*`
replaces Personal React use of Legacy host-global APIs. Legacy APIs are 404 in
React mode and Personal APIs are absent in Legacy mode. No database or route is
created by this documentation task.

## 8. Security analysis

Every Personal read or mutation derives scope from the verified identity, never
from URL selectors, local storage, or client state. Unsafe requests require
same-origin CSRF validation. Missing authentication is `401`, bad Origin/CSRF
is `403`, and foreign/expired resources are `404`. Secrets are encrypted,
server-only, masked on reads, and absent from logs/evidence/checkpoints.

## 9. Scalability and heavy-load analysis

The bounded target remains the Compose 4 GiB/2 CPU profile and ten concurrent
scoped requests, with retrieval p95 under three seconds where the fixture and
machine permit. Scope inclusion prevents cache/checkpoint collisions; overload
must be measured and return bounded sanitized `503` with `Retry-After`, not
unbounded work. No performance result is claimed by this Todo.

## 10. Error-handling strategy

Scope provisioning is transactional. Settings and document replacement publish
only complete validated state; failures retain prior state. Stream jobs are
bounded/cancellable and not restart-persistent; a post-restart reattach is a
sanitized `404`. Provider and storage failures are redacted.

## 11. Observability strategy

Record only redacted scope-safe identifiers and outcomes. Future evidence must
include two-identity isolation results, Legacy pre/post hashes, capacity
measurements, status codes, and cancellation cleanup without secrets, source
text, cookies, or CSRF values.

## 12. Testing strategy

Later implementation requires positive/negative two-identity API tests,
Legacy hash/count preservation, scoped persistence/restart tests, frontend
tests, and an authenticated EN/RU Browser matrix. This Todo's executable
compatibility checks are the Group 1 Legacy API pytest and React route Vitest
suite recorded in its evidence.

## 13. Migration and rollback plan

There is no migration in Group 2. Existing Legacy data remains untouched.
Rollback selects explicit `local + legacy` operator mode; Group 12 alone may
consider purge after parity, verified backup/export, and separate confirmation.

## 14. Unresolved assumptions

Cross-device Personal synchronization remains TBD. The exact Group 5 promotion
policy and transaction are deferred. Scoped collection/storage overhead must be
measured on the supported Compose profile before any capacity claim.

## 15. Explicit acceptance criteria

Group 2 may claim only AC-023.1 after the full private parity and two-identity
evidence pass. It may not claim FR-023 complete or AC-023.2 complete. Personal
operations must not mutate or expose Legacy data, and any future purge must
meet the Group 12 safeguards.

## 16. Manual testing scenarios

With synthetic identities and source labels, verify user A can upload, change
settings, chat, cancel, and resume only A's Personal Lab while user B receives
sanitized denial/absence for every A resource. Verify React mode has no Legacy
data APIs, then switch to explicit Legacy mode and confirm the pre-existing
Legacy count/hash is unchanged. Confirm no Agent-promotion control implies a
completed copy.

## Alternatives and revisit conditions

Host-global React reuse and automatic Legacy claiming were rejected because
they cannot prove ownership/isolation; revisit only with the ADR's explicit
scope or import guarantees. Early Agent promotion was rejected until Group 5
delivers authorization, preview, idempotency, cancellation, and rollback.
