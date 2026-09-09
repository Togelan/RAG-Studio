# MVP v1: Personal Lab billing and embeddable widget

## 1. Problem statement

RAG-Studio needs a fast, demonstrable customer MVP on the existing React UI:
an authenticated user manages private Personal Lab knowledge and chat, can
complete a Stripe test payment, and can publish a working website widget over
that same knowledge. The existing Legacy UI is not part of this delivery.

## 2. Requirements and non-goals

### Owning requirement and future-contract boundary

**FR-MVP-001** in `system_spec.md` owns this delivery. Its three independently
testable Gherkin controls are: AC-MVP-001.1 (React Personal Lab preservation
and no-Legacy authority), AC-MVP-001.2 (one webhook-authoritative Stripe
test-mode entitlement), and AC-MVP-001.3 (one fail-closed public widget).
They are an MVP v1 variation, not evidence that the broader future contracts
are complete or weaker.

### Future-contract deferment matrix

| Future contract | MVP v1 uses | Explicitly deferred |
| --- | --- | --- |
| FR-016 | Shadow-DOM isolation and public admission only for one Personal Lab widget with one exact origin. | Workspace owner/admin authority, workspace/chatbot resolution, multi-widget management, and the wider widget lifecycle. |
| FR-017 | One `$10 USD/month` Stripe test-mode recurring Price, hosted Checkout/Portal, and signed idempotent webhook processing. | Trial, three-plan catalogue, plan changes, usage pricing, tax, production payments, Account Owner authority, and Account-wide limits. |
| FR-023 | Only AC-023.1's server-resolved private React Personal Lab scope. | AC-023.2 Agent promotion, hidden data movement, Workspace sharing, and Legacy migration. |
| FR-029 | A Personal Lab entitlement projection that gates this one widget. | Account billing placeholder, Account Owner authority, and workspace/agent/member/resource entitlement enforcement. |

No request in this delivery may import, mutate, migrate, expose, or retrieve
Legacy data. The public widget receives neither Personal Lab scope/collection
selection nor provider, private-session, or billing authority.

### Requirements

- Preserve the existing authenticated React Personal Lab: settings, document
  upload/replacement/re-indexing, chat sessions, streaming, and citations.
- Provide one `$10 USD/month` Stripe test-mode subscription through hosted
  Checkout and Customer Portal.
- Change entitlement only from verified, idempotent Stripe webhooks.
- Let the authenticated Personal Lab owner publish and disable one
  Shadow-DOM widget over that same scope.
- Require exactly one explicit approved origin per widget configuration and
  enforce it server-side before public RAG work.
- Keep all product UI within the current React RAG-Studio design system.

### Non-goals

- No Legacy data import, mutation, migration, or public exposure.
- No workspace, role, invitation, Agent-promotion, or shared-knowledge work.
- No three-plan catalog, trial, usage billing, production payments, tax
  collection, multiple widgets, wildcard origins, or published-data copy.
- No custom card form, browser-held Stripe secret, or browser-authoritative
  entitlement.

## 3. Current architecture and request flow

React calls cookie-authenticated, same-origin, CSRF-protected
`/api/personal/*` APIs. FastAPI revalidates identity and derives an opaque
Personal Lab scope; ingestion, vector storage, settings, chat checkpoints,
sessions, streaming, and citations use that scope. Legacy is an explicit,
separate operator mode.

Workspace chatbot modules exist, but their workspace/role contracts do not
apply to Personal Lab and must not become an accidental source of authority.
There is no Stripe or public widget route, record, or frontend in the current
checkout.

## 4. Proposed architecture

Create a minimal modular-monolith vertical slice:

1. A server-owned versioned MVP billing catalog resolves the one configured
   Stripe Price ID and its display value.
2. Authenticated React billing controls call CSRF-protected BFF endpoints.
   The BFF uses a restricted Stripe client to create hosted Checkout and
   Customer Portal sessions.
3. A signature-verified webhook endpoint records each event ID idempotently
   and updates the last verified Personal Lab entitlement.
4. An authenticated Personal Lab publication control creates, reads, disables,
   or revokes one widget configuration with one exact allowed origin.
5. The isolated widget custom element receives its public key and asks a
   public BFF endpoint to resolve origin, publication state, entitlement,
   rate-limit allowance, Personal Lab scope, then the existing RAG execution
   path. It never receives collection identifiers, provider secrets, session
   authority, or billing authority.

## 5. Domain model and ownership

| Domain | Owner | Key responsibility |
| --- | --- | --- |
| Personal Lab scope | existing API/registry | Resolve opaque identity scope; never trust the browser selector. |
| Billing catalog and entitlement | API billing module + Supabase | Map configured Price ID to one plan; persist last verified webhook state. |
| Stripe interaction | API billing module | Checkout/Portal session creation and verified webhook processing. |
| Widget publication | API widget module + Supabase | One Personal Lab configuration, exact origin, key lifecycle, enabled state. |
| Widget runtime | isolated `widget/` package | Shadow-DOM UI and bounded public calls only. |
| React management | `frontend/` | Render billing and publication state; no payment, scope, or authorization decisions. |

## 6. Files/modules likely to change

- `src/api/`: billing catalog/client/webhook routes, widget-publication routes,
  public widget RAG boundary, composition and environment validation.
- `src/graph/`, `src/retrieve/`, `src/vector_store/`: only an explicitly scoped
  adapter needed to execute the existing RAG path for a verified publication.
- `supabase/migrations/`: billing entitlement/event ledger and widget
  publication records with ownership and uniqueness constraints.
- `frontend/src/`: Personal Lab billing/publication surfaces, API clients,
  routes, copy, and tests in the existing design system.
- `widget/`: isolated custom element, CSS, build configuration, and host-page
  fixtures.
- `tests/`, `frontend/tests/`, and widget tests: unit, API, integration,
  browser-contract, and host-page coverage.

## 7. API and database changes

Authenticated endpoints require the current session and CSRF protection:

- `GET /api/personal/billing` returns sanitized plan, usage, and last verified
  entitlement state.
- `POST /api/personal/billing/checkout` returns a hosted Checkout URL.
- `POST /api/personal/billing/portal` returns a hosted Customer Portal URL.
- `GET/PUT/DELETE /api/personal/widget-publication` manages one explicit
  origin and publication state; `PUT` is idempotent and never exposes a
  secret.

The Stripe webhook endpoint accepts raw request bytes, verifies its signature,
and records the Stripe event ID before making an idempotent entitlement update.
Public widget endpoints accept a key and browser Origin, but do not accept a
Personal Lab, collection, or entitlement identifier.

## 8. Security analysis

- Use server-only restricted Stripe credentials and a distinct webhook secret;
  never expose either to React, the widget, logs, errors, fixtures, commits,
  or `.env.example` values.
- Treat Stripe redirects as presentation only; signed webhooks are the
  entitlement authority and must tolerate replay/out-of-order delivery.
- Public keys are identifiers, not authenticators. Require enabled
  publication, exact approved Origin, entitlement, request rate limits, and
  monthly MVP message budget before RAG execution.
- Require CSRF and identity revalidation for every authenticated state change.
- Return sanitized `401`, `403`, `404`, `409`, `429`, or `503` states without
  leaking provider errors, scopes, source content, or Stripe internals.
- Use a Shadow DOM with documented semantic theme tokens; host CSS and widget
  overlay styles must not escape their boundary.

## 9. Scalability and heavy-load analysis

The target stays Compose-limited 4 GiB/2 CPU with ten concurrent scoped
requests. Public requests are rate-limited before graph/retrieval work and
bounded by the existing job/cancellation model. The one-plan MVP uses a fixed
monthly public-message limit stored in the server catalog rather than adding
usage-based billing infrastructure. Measure retrieval p95 and rejection
behavior with an enabled widget; do not claim capacity without results.

## 10. Error-handling strategy

Invalid webhook signatures do no write. Duplicate webhook events converge to
one record. Stripe unavailability retains the last verified entitlement and
renders a recoverable state. Disabled, unknown, or origin-mismatched widgets
are rejected before RAG work. Document replacement/re-indexing keeps existing
Personal Lab atomic replacement behavior; publication never copies documents.
Widget streams use the existing bounded/cancellable execution semantics and
render a sanitized terminal error.

## 11. Observability strategy

Record redacted event IDs, publication IDs, normalized origin hashes, outcome
codes, rate-limit decisions, entitlement transitions, latency, and stream
terminal state. Do not record secrets, raw Stripe payloads, cookies, CSRF
tokens, source text, prompts, or collection names. Report webhook duplicate
and signature-failure counters separately.

## 12. Testing strategy

- Unit tests for catalog mapping, origin normalization/exact matching,
  idempotency, entitlement transitions, webhook signatures, and rate limits.
- API tests for unauthenticated/CSRF/foreign publication rejection, disabled
  widget behavior, wrong-origin rejection, no-RAG-on-rejection, duplicate and
  out-of-order webhook convergence, and Stripe redaction.
- Frontend tests for current React billing/publication states, error/loading
  handling, keyboard access, EN/RU copy, and no legacy UI dependency.
- Widget component/host fixture tests for Shadow-DOM isolation, open/close,
  stream, citation, error, offline, rate-limit, and reduced-motion behavior.
- Structured Playwright MCP `playwright_qa_2` QA only: desktop/mobile
  authenticated Personal Lab journey, hosted test checkout/portal redirect
  return, approved/rejected origin host pages, publish/disable recovery, and
  visual screenshots. No raw browser JavaScript.
- Normal QA, adversarial QA, and review-work are mandatory because billing,
  widgets, public endpoints, streaming, and stateful React are high risk.

## 13. Migration and rollback plan

This delivery adds independent billing and publication records only. It never
migrates Legacy data or copies Personal Lab knowledge. Rollback disables the
widget/public routes and hides the React controls while retaining the current
Personal Lab. Preserve the webhook/event and publication ledger for audit;
do not remove it merely because a feature flag is rolled back.

## 14. Unresolved assumptions

- The owner must supply separate Stripe test restricted key, webhook secret,
  Product/Price ID, return URLs, and Customer Portal configuration outside
  source control.
- The exact fixed monthly public-message limit needs selection in the
  implementation plan; it must be server-configured and tested.
- Production Stripe Tax, active registrations, live keys, and live domains are
  explicitly out of scope. Tax collection must not be enabled before that work.
- Future multi-widget, multi-origin, workspace, Agent promotion, quota, and
  plan-catalog behavior requires a new ADR or an update to this one.

## 15. Explicit acceptance criteria

1. A signed-in Personal Lab user retains private React settings, documents,
   re-indexing, chat sessions, streaming, and citations before and after
   billing/widget configuration.
2. The UI displays one `$10 USD/month` plan and opens Stripe test Checkout;
   only a verified webhook creates paid entitlement.
3. Customer Portal opens only for the authenticated owner of the matching
   Personal Lab billing record.
4. The user can publish one widget with one exact origin and later disable or
   revoke it without changing Personal Lab knowledge.
5. A valid host page renders an accessible Shadow-DOM widget that streams RAG
   answers and citations from its published Personal Lab scope.
6. Wrong origin, disabled/unknown key, missing entitlement, excessive rate,
   invalid webhook, and duplicate webhook requests are bounded, sanitized, and
   do not consume RAG/billing resources incorrectly.
7. The React surfaces and widget meet the existing design, responsive, i18n,
   accessibility, structured Playwright, adversarial QA, and review gates.

## 16. Manual testing scenarios

1. Sign in using a local QA account, configure the Personal Lab, upload
   documents, select a chunking strategy, re-index, ask a question, reload,
   and confirm the session, stream, and citations persist.
2. Open Billing, start Checkout with a Stripe test card, return to the app,
   deliver the signed test webhook, and observe paid state only after the
   webhook. Open Customer Portal and return safely.
3. Publish one widget with the exact local host origin. Load the host fixture,
   open the widget, ask a question, observe streaming and citations, then
   disable the publication and confirm new public requests stop.
4. Load the same key from a different origin, a disabled key, and an expired
   rate-limit state; confirm sanitized failure without source or scope leakage.
5. Repeat the checkout webhook and deliver a later cancellation/out-of-order
   event; confirm entitlement converges and the public widget is blocked when
   required.

## Alternatives and revisit conditions

Direct Personal Lab publication is selected over copied knowledge for speed;
revisit for immutable public snapshots or independent retention. Stripe
Checkout/Portal is selected over a custom card form for security and speed;
revisit only for a demonstrated custom-payment requirement. One plan is
selected over a full catalog for MVP delivery; revisit when customer validation
requires trials, tiers, quotas, or usage-based billing.
