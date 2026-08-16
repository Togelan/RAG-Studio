# Multi-tenant SaaS migration

## 1. Problem statement

Transform RAG-Studio from its current local-first personal RAG application into
a locally runnable, hosting-ready SaaS that lets companies create a shared
knowledge chatbot, test it in an advanced web application, and embed it safely
on approved websites.

## 2. Requirements and non-goals

### Requirements

- Provide a React/TypeScript/Tailwind/shadcn SaaS frontend with responsive
  desktop and mobile behavior.
- Support Supabase authentication, workspaces, invitations, and `owner`,
  `admin`, and `member` roles.
- Restrict source upload, deletion, and re-indexing to owners and admins.
- Use one Qdrant collection per workspace and server-side workspace resolution.
- Retain FastAPI, LangGraph, and the RAG pipeline behind a FastAPI BFF.
- Provide a public Shadow-DOM widget with per-chatbot public key,
  approved-origin allowlist, rate limiting, and local-development localhost
  support.
- Provide Stripe test-mode subscriptions: 14-day trial, three plans, and
  limits for active chatbots, indexed storage, and public-widget messages.
- Process validated Stripe webhooks idempotently as the entitlement source of
  truth.
- Run the full customer flow locally through Docker Compose and be ready for
  later hosting through environment configuration, health checks, persistent
  storage, and deployment documentation.
- Apply the mandatory UI pipeline to every UI task and use user-provided visual
  references before UI implementation.

### Non-goals

- Do not automatically migrate existing local documents, vectors, settings, or
  API keys; start with empty SaaS workspaces and explicit import.
- Do not deploy or provision production services in this stage.
- Do not build full microservices before measured load or operational evidence
  requires extraction.
- Do not support arbitrary custom roles, enterprise SSO, or production charges
  in the first stage.

## Delivery stages and FR traceability

The current `system_spec.md` defines `FR-001` through `FR-020`, each with
independently testable Gherkin acceptance criteria and traceability entries.
`FR-012` is the approved authority for the Stage 2 React migration and its
existing-function parity boundary; `FR-013` through `FR-020` remain Stage 3
requirements and must not be implemented implicitly during Stage 2.
Every plan task must name one owning FR and list every existing FR it modifies.
Task IDs are not substitutes for FR numbers.

Every implementation task also has a mandatory in-app `@Browser` completion
scenario. After automated checks pass, developer and independent QA each
exercise the affected journey in the running web application and record the
URL, steps, observed result, viewport where relevant, and screenshots for
visual changes.

### Stage 1 — Completed chunking-strategy baseline

This stage is closed and is not reimplemented by the migration plan. It remains
a regression baseline.

| Task | Owning FR | Existing FRs modified | State |
|---|---|---|---|
| Strategy selection, validation, and metadata | `FR-011` | `FR-001`, `FR-005` | Existing, completed |
| Safe strategy re-ingestion | `FR-011` | `FR-010` | Existing, completed |
| Mixed-strategy retrieval and context limits | `FR-011` | `FR-002` | Existing, completed |
| CSV marker, citation fallback, and local benchmark evidence | `FR-011` | `FR-001`, `FR-002`, `FR-008` | Existing, completed |

### Stage 2 — UI migration with existing-function parity

Stage 2 replaces the Jinja/vanilla presentation layer while preserving the
behavior already covered by `FR-001` through `FR-011`. It must not add fake
authentication, billing, tenant, or widget controls ahead of Stage 3.

| Task | Owning FR | Existing FRs modified | Requirement type |
|---|---|---|---|
| React application shell, design tokens, shadcn primitives, Lucide policy, responsive states, and legacy-route cutover | `FR-012` | `FR-007`, `FR-008`, `FR-009` | New FR |
| Welcome-page parity and new approved visual composition | `FR-004` | `FR-012` | Existing FR modified by UI migration |
| Settings, uploads, document management, and chunk controls parity | `FR-005` | `FR-010`, `FR-011`, `FR-012` | Existing FR modified by UI migration |
| Streaming chat, citations, feedback, cancellation, and session parity | `FR-006` | `FR-003`, `FR-012` | Existing FR modified by UI migration |
| Navigation, accessibility, responsive/mobile behavior, and route parity | `FR-007` | `FR-012` | Existing FR modified by UI migration |
| React i18n parity for all migrated routes | `FR-009` | `FR-012` | Existing FR modified by UI migration |

Every Stage 2 task uses
`design-system-style-intelligence → frontend-design-director →
react-shadcn-ui-contract → omo:visual-qa`. Reference images must be placed in
`docs/design/references/saas-ui/`; [`DESIGN.md`](../../DESIGN.md) records which
references govern which surfaces and the approved tokens, layout grammar,
interaction rules, accessibility, responsive behavior, visual exclusions, and
legacy-style removal boundary.

### Stage 3 — SaaS capabilities required by migration.md

| Task | Owning FR | Existing FRs modified | Requirement type |
|---|---|---|---|
| Supabase authentication, workspaces, invitations, and owner/admin/member RBAC | `FR-013` | `FR-008`, `FR-009` | New FR |
| FastAPI BFF authorization and separate Qdrant collection per workspace | `FR-014` | `FR-001`, `FR-002`, `FR-003`, `FR-005`, `FR-006`, `FR-008`, `FR-010`, `FR-011` | New cross-cutting FR |
| Workspace chatbot creation, configuration, testing, and lifecycle | `FR-015` | `FR-003`, `FR-005`, `FR-006`, `FR-009` | New FR |
| Shadow-DOM embeddable widget, public keys, origin allowlist, rate limits, and theme tokens | `FR-016` | `FR-003`, `FR-006`, `FR-008`, `FR-009` | New FR |
| Stripe test-mode trial, three plans, webhook entitlements, usage metering, and gated features | `FR-017` | `FR-008`, `FR-009` | New FR |
| SaaS landing page, product explanation, pricing, FAQ, and conversion journey | `FR-018` | `FR-004`, `FR-007`, `FR-009`, `FR-017` | New FR plus existing UI modifications |
| Full local Compose environment and hosting-ready configuration, persistence, health, backup, and rollback | `FR-019` | `FR-008` and applicable NFRs | New deployment FR |
| Launch demo: customer test journey and written tutorial with verified screenshots, or video walkthrough | `FR-020` | `FR-004` through `FR-019` as traceability only | New deliverable FR |

Stage 3 UI subtasks also cite `FR-012` as the UI-system modifier and must pass
the mandatory UI pipeline. Stage 3 cannot be called complete from backend tests
alone; its customer journeys must work through the React interface and widget.

## 3. Current architecture and request flow

The current checkout serves Jinja templates from FastAPI and stores local
settings and documents alongside an embedded/local Qdrant collection. Upload,
ingestion, retrieval, streaming chat, and settings are owned by existing
`src/api`, `src/ingestion`, `src/retrieve`, `src/graph`, and
`src/vector_store` modules. Tests currently exercise the local UI, settings,
and Qdrant boundaries. There is no authenticated workspace request context.

## 4. Proposed architecture

```text
React SaaS frontend and Shadow-DOM widget
                 |
                 v
             FastAPI BFF
       /         |          \
Supabase auth  LangGraph RAG  Stripe webhook/entitlements
and workspace       |                  |
data            per-workspace Qdrant collections
                 |
          bounded ingestion worker
```

The modular monolith keeps these responsibilities deployable together locally
but separable later. Every privileged request derives workspace identity and
permissions on the server before touching relational records or Qdrant.

## 5. Domain model and ownership

Supabase owns users, workspaces, memberships, invitations, plans, subscriptions,
usage records, chatbot configuration, and approved widget origins. FastAPI owns
authorization decisions, plan-limit enforcement, Stripe event processing,
workspace collection naming/resolution, RAG request orchestration, and
sanitized errors. Qdrant owns only one collection per workspace's vector index.

`owner` manages billing/deletion/ownership/members; `admin` manages sources,
chatbots, widgets, and invitations; `member` can test/use chatbots. A public
widget is an anonymous caller with a public key and approved origin, never an
employee membership.

## 6. Files/modules likely to change

- New frontend workspace/package for React application and widget build.
- `DESIGN.md` and `docs/design/references/saas-ui/` for the approved reference
  inventory and extracted design system.
- `docker-compose.yml`, `Dockerfile`, `.env.example`, and deployment docs for
  local SaaS dependencies and hosting configuration.
- `src/api/` for BFF routes, authentication dependencies, authorization,
  webhook handling, rate limits, streaming, health checks, and legacy routing.
- `src/graph/`, `src/ingestion/`, `src/retrieve/`, and `src/vector_store/` for
  workspace-scoped orchestration and separate collection management.
- New Supabase migrations/policies and billing/usage persistence layer.
- Tests for API authorization, tenant isolation, Stripe webhooks, widgets,
  mobile UI, and end-to-end local Compose workflows.

Exact file paths and frontend build tooling require the implementation plan;
no production code is changed by this design document.

## 7. API and database changes

Introduce workspace-scoped authenticated APIs for membership, sources,
chatbots, widget configuration, billing portal/checkout, and usage. Introduce
a separate public-widget API that accepts only a public widget key and browser
origin, never a privileged workspace identifier from the client.

Supabase stores workspace UUIDs and membership roles. A deterministic internal
workspace UUID derives a non-human-readable Qdrant collection name. Stripe
events are stored by event ID before side effects to provide idempotency. Plan
limits are enforced server-side for active chatbots, indexed storage, and
monthly widget messages.

## 8. Security analysis

Authorize every privileged operation server-side using verified Supabase
identity, membership, and role; never trust a browser-selected workspace or
collection. Use separate collections as defense in depth, but do not treat
their name as authorization. Validate widget keys and origins server-side;
return sanitized authorization errors and rate-limit public traffic. Store all
service keys in environment variables, redact them from logs, validate Stripe
webhook signatures, and make webhook effects idempotent.

## 9. Scalability and heavy-load analysis

The first-stage local acceptance target is ten concurrent authenticated or
public-widget requests. Measure p95 retrieval/chat latency, ingestion duration,
collection creation time, vector/storage usage, and memory under the actual
Compose limits. Bound uploads, chunks, concurrent generations, ingestion queue
depth, widget requests, and webhook retries. Capacity exhaustion must reject
work with sanitized `429` or `503` responses; it must never cross workspace
boundaries or silently drop paid entitlement changes.

The modular monolith is chosen over microservices until measurements show an
ingestion backlog, independent scaling need, or operational ownership boundary
that justifies extraction.

## 10. Error-handling strategy

Reject unauthenticated, unauthorized, invalid-origin, over-limit, and invalid
webhook requests before invoking RAG or Qdrant. Use bounded retries only for
idempotent external operations. Preserve existing collection content when a
document re-index fails; report a sanitized status and retain the prior index.
Stripe webhook retries are safe through stored event IDs. Cancelled chats and
ingestions release capacity and leave no partially committed entitlement or
collection mapping.

## 11. Observability strategy

Emit structured, redacted events for request ID, workspace ID hash, role,
operation, plan-limit decision, collection operation, widget origin verdict,
Stripe event ID, latency, and sanitized failure code. Keep LangSmith traces for
RAG behavior without recording secrets or unnecessary source content. Local
Compose health checks report dependency readiness; hosting documentation names
the expected log, trace, and backup surfaces.

## 12. Testing strategy

- Unit tests for role/entitlement/origin decisions, deterministic collection
  names, usage counters, webhook idempotency, and error redaction.
- Integration tests proving no user can access another workspace's sources,
  chatbots, Qdrant collection, billing actions, or widget configuration.
- Stripe test-mode tests for trial, checkout, webhook retries, plan change,
  cancellation, and limit enforcement.
- End-to-end local Compose tests for owner/admin/member flows, widget requests,
  upload/re-index behavior, and all three plan limits.
- Browser tests and `omo:visual-qa` for the mandatory UI pipeline, responsive
  desktop/mobile layouts, focus, keyboard access, reduced motion, and visual
  fidelity to user-supplied references.
- Load evidence at ten concurrent requests with bounded overload behavior.

## 13. Migration and rollback plan

Leave the existing local application and data untouched. Create empty SaaS
workspaces and provide explicit imports after launch. Introduce SaaS routing and
services behind reversible configuration/feature flags while legacy pages
remain available. A rollback disables SaaS entry points and widgets without
deleting Supabase records, Qdrant collections, imported documents, or Stripe
test data; recovery uses documented backups and retained mappings.

## 14. Unresolved assumptions

- Exact plan prices and quantitative quotas are not yet chosen; the measured
  dimensions are fixed, but their values belong in the implementation plan.
- Local Supabase runtime versus a dedicated development Supabase project must
  be selected during planning based on reproducibility and developer setup.
- The production host, email provider for invitations, and custom-domain flow
  are intentionally deferred.
- The approved visual references and design direction are recorded in
  [`DESIGN.md`](../../DESIGN.md). The exact UI package versions and any future
  light-mode decision remain implementation-planning concerns.

## 15. Explicit acceptance criteria

1. A local customer can create an account and a workspace, invite users, and
   exercise owner/admin/member permissions.
2. Only owners and admins can upload, delete, or re-index workspace knowledge.
3. Each workspace resolves only to its own Qdrant collection, and cross-workspace
   API, vector, billing, and widget access is rejected by automated tests.
4. A public widget works only with its configured public key from an approved
   origin; development localhost is allowed only in development configuration.
5. Stripe test-mode trial/subscription lifecycle updates server-side
   entitlements through idempotent webhook processing.
6. Plan limits for chatbots, storage, and widget messages are enforced
   server-side with clear bounded failure responses.
7. The full flow runs locally with documented configuration and is ready for
   hosting without code changes for environment URLs or credentials.
8. The new UI is responsive and passes the mandatory design/visual-QA pipeline.
9. Existing local data remains unchanged unless a user explicitly imports it.
10. At ten concurrent requests, overload remains bounded and no tenant boundary
    is bypassed.
11. Every implementation-plan task cites an owning FR from `system_spec.md` and
    lists any existing FRs whose behavior or acceptance criteria it modifies.

## 16. Manual testing scenarios

1. Run the local stack, create a workspace, invite an admin and member, and
   verify their navigation and permissions differ as specified.
2. Confirm a member cannot upload, delete, or re-index; confirm an admin can.
3. Create two workspaces, index different facts, and prove each chat and widget
   can return only its own facts.
4. Embed a widget on an approved local origin, then try an unapproved origin
   and a copied key; verify the latter is rejected and logged safely.
5. Complete a Stripe test-mode trial/checkout/plan change/cancellation and
   replay a webhook; verify entitlement state changes once.
6. Exhaust each plan limit and verify a clear `429` or `403` response without
   partial ingestion or billing corruption.
7. Test every UI route on desktop and small mobile viewports with keyboard and
   reduced-motion preferences; compare it against the supplied design references.
8. Restart local services and verify persistent workspace, collection, and
   entitlement data recover as documented.
