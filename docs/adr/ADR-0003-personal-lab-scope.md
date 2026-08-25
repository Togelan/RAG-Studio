# ADR-0003: Isolate Personal Lab behind opaque per-user scopes

- Status: Accepted
- Date: 2026-08-22
- Scope: Group 2, partial FR-023 delivery (AC-023.1 only)

## Context

FR-023 requires the full personal RAG workflow in the unified React UI while
keeping its documents, settings, sessions, and provider-key boundary private.
The existing local workflow persists host-global Legacy data. Group 1 is
terminal at `942ee67d651bf0202583c29e98acaedcbf11b523`: its final receipt,
five-lane review manifest, cleanup receipt, plan cells, and Boulder state all
bind that closure. This ADR defines the next delivery boundary; it does not
implement it or migrate existing data.

## Decision

Group 2 delivers only FR-023 AC-023.1. After trusted BFF identity
revalidation, the server resolves a stable opaque per-user Personal Lab scope
and uses it for every Personal persistence and execution boundary. React
Personal Lab calls are cookie-authenticated, same-origin and CSRF-protected
`/api/personal/*` requests; the client cannot select a scope.

Host-global Legacy APIs and data remain available only in explicit
`local + legacy` operator mode. They are not mounted alongside multi-user
React Personal Lab mode. Group 2 performs no automatic import, claim,
transformation, exposure, or deletion of Legacy data. Legacy purge is Group 12
work and requires verified parity, verified backup/export, and a separate
purge confirmation.

FR-023 AC-023.2 Agent promotion/copy is deferred to Group 5. Group 2 neither
creates an Agent nor presents a disabled or misleading promotion control.

## Alternatives considered

1. Reuse host-global Legacy storage behind React routes. Rejected because a
   trusted identity could not enforce two-user isolation and React mode could
   expose one user's data to another. Revisit only if a future migration proves
   Legacy stores have become cryptographically and transactionally scoped with
   the same server-side guarantees.
2. Automatically claim or copy Legacy data into the first authenticated
   Personal Lab. Rejected because ownership is ambiguous and the action could
   disclose, transform, or irreversibly mix data and provider configuration.
   Revisit only with a separately approved, user-confirmed import contract,
   preview, audit trail, cancellation behavior, and rollback proof.
3. Deliver Agent promotion in Group 2. Rejected because it needs the Group 5
   Agent, authorization, snapshot, idempotency, and rollback contracts. Revisit
   when those contracts and their explicit confirmation UX are implemented.

## Consequences

The Group 2 implementation must add an explicit scope registry and route
composition seam before adapting settings, knowledge, retrieval, and chat.
Every lookup, cache/checkpoint key, collection name, job key, and resource
authorization check must include the resolved scope; foreign or expired
resources return sanitized `404`, unauthenticated calls `401`, and invalid
Origin/CSRF mutations `403`.

The dependency chain is intentional: Group 1's closed authenticated React
shell enables Group 2's private parity; Group 2 then enables later Group 5
promotion without giving it premature data-moving behavior. The primary risk
is cross-user disclosure through a missed persistence seam, so two-identity
negative tests and Legacy byte/count hashes are required before parity claims.

## Safety and rollback

No existing Legacy object is mutated by scope provisioning or Personal Lab
operations. Provider secrets remain server-side and encrypted/masked; evidence,
logs, responses, graph state, and fixtures must not contain plaintext secrets,
raw provider errors, cookies, CSRF values, or source content. Failed writes
retain prior complete Personal state, live work is bounded and cancellable, and
rollback switches the operator to `local + legacy` mode without deletion.

## Revisit conditions

Revisit this decision if measured scoped collection/storage overhead breaches
the Compose 4 GiB/2 CPU profile or ten-concurrent-request target, if a
policy-approved explicit Legacy import is accepted, or when Group 5 supplies
the Agent-promotion transaction contract. Any such change needs an ADR update,
two-identity evidence, and a new rollback assessment.
