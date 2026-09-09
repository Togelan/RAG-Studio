# ADR-0005: Publish one Personal Lab widget with one Stripe MVP plan

## Status

Accepted

## Context

The approved React Personal Lab is the MVP's authenticated RAG surface. It
already keeps settings, knowledge, sessions, execution, and citations behind a
server-resolved opaque identity scope, while Legacy data remains separate under
ADR-0003. FR-MVP-001 is the sole owning requirement for this bounded customer
validation slice.

The next customer-validation milestone needs a real, locally testable payment
flow and a website widget over that knowledge without prematurely implementing
the later multi-workspace, multi-role, multi-chatbot product. FR-016 and
FR-017 define the eventual broader product, including multiple plans and
workspace-owned chatbots. The MVP must be smaller while preserving the
security properties that cannot be deferred.

## Decision

MVP v1 will provide one `$10 USD/month` Stripe test-mode subscription through
Stripe-hosted Checkout and the Stripe Customer Portal. FastAPI, using a
server-only restricted Stripe API key, creates checkout and portal sessions.
Signed, idempotently persisted webhooks alone create or change entitlement;
return URLs only drive user experience.

An authenticated Personal Lab user may explicitly publish one widget that
queries the same server-resolved Personal Lab scope. Publish and disable are
reversible configuration actions. The widget key identifies one published
configuration but is not a secret. Every widget request must match its single
explicit approved origin before FastAPI resolves scope, entitlement, or RAG
resources. No wildcards or implicit localhost aliases are accepted.

The widget is a standalone Shadow-DOM package and public FastAPI boundary. It
does not reuse the Legacy UI or grant a browser authority over collection,
scope, settings, or provider credentials.

## Future-contract relationship matrix

FR-MVP-001 does not complete or weaken the following future requirements:

| Future contract | MVP v1 decision | Deferred behavior |
| --- | --- | --- |
| FR-016 | Reuse only its isolation and fail-closed public-admission intent for one Personal Lab widget. | Workspace owner/admin authority, workspace/chatbot resolution, multi-widget management, and the full widget lifecycle. |
| FR-017 | Use one `$10 USD/month` Stripe test-mode recurring Price, hosted Checkout/Portal, and signed idempotent webhooks. | Trial, three-plan catalogue, plan changes, usage pricing, tax, production payments, Account Owner authority, and Account-wide limits. |
| FR-023 | Use only AC-023.1's opaque, server-resolved React Personal Lab scope. | AC-023.2 Agent promotion, hidden data movement, Workspace sharing, and Legacy migration. |
| FR-029 | Project entitlement only to decide whether this single public Personal Lab widget may run. | Account billing placeholder, Account Owner authority, and workspace/agent/member/resource entitlement enforcement. |

The no-Legacy authority boundary is non-negotiable: MVP requests may not
import, mutate, migrate, expose, or retrieve Legacy documents, vectors,
settings, sessions, caches/checkpoints, feedback, uploads, or provider keys.

## Alternatives considered

1. **Copy Personal Lab knowledge to a published index.** Rejected for MVP
   because it adds synchronization, replacement, deletion, rollback, and
   duplicate-storage rules. Revisit when users need immutable publication
   snapshots or independent public retention.
2. **Reuse the existing workspace-chatbot implementation.** Rejected because
   it is workspace/role based and would either invent a workspace for a
   Personal Lab user or weaken the documented Personal Lab boundary. Revisit
   after the workspace and agent delivery is complete.
3. **Static payment UI or redirect-confirmed billing.** Rejected because it
   cannot demonstrate a real purchase journey and lets browser-controlled
   state imply paid access. Revisit only for an explicitly labelled mock demo.
4. **Implement the full three-plan FR-017 catalog now.** Rejected for speed.
   Revisit when MVP feedback requires plan changes, quotas, trials, or usage
   billing.

## Consequences

The implementation must add a small server-owned billing catalog and webhook
ledger, a Personal Lab publication record, a public widget request boundary,
and a React management surface in the current design system. It must enforce
one configuration per Personal Lab, a single exact origin, entitlement before
public RAG work, bounded rate limiting, sanitized errors, and immediate
disable.

Stripe secrets and webhook secrets stay in environment/secret storage and are
never rendered, logged, committed, or returned. The implementation uses a
Stripe client instance, omits `payment_method_types`, and does not enable
automatic tax until a Stripe Tax registration has been configured. Stripe
test-mode Product/Price identifiers remain deploy-time configuration.

## Safety and rollback

No Legacy, Personal Lab document, vector, session, provider-secret, or chat
record is copied or mutated by payment configuration. Disabling a widget
blocks new public requests without deleting Personal Lab knowledge. Deleting
the publication configuration revokes its key. An unavailable Stripe or
webhook endpoint preserves the last verified entitlement and returns a stable
sanitized state.

Rollback removes the published widget and billing controls while preserving
the existing authenticated Personal Lab and its data. Before a destructive
schema reversal, export the billing/publication ledger or retain it as an
inactive record; never infer entitlement from a redirect or recreate billing
history.

## Revisit conditions

Revisit this decision when adding a second widget, multiple origins,
multi-user ownership, Personal-to-Agent promotion, production Stripe charges,
tax registration, quota-based pricing, or immutable published snapshots.
