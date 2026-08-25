---
name: adversarial-review
description: Independent, read-only review that actively tries to falsify an implementation and its tests before merge, especially for security, persistence, concurrency, migration, RAG, billing, widget, and UI changes.
---

# Adversarial Review

## Purpose

Adversarial review is a separate challenge gate after implementation and normal
QA. It is not a second confirmation pass. The reviewer assumes that a green
test suite may be incomplete, weakly asserted, incorrectly mocked, or blind to
state and security boundaries, and actively searches for a counterexample.

## When it is mandatory

Run this skill before merge for every high-risk change and whenever an owner,
architect, or QA engineer requests it. High-risk changes in RAG-Studio include:

- authentication, sessions, CSRF, Origin checks, identity or role resolution;
- workspace, Personal Lab, Agent, Widget, billing, entitlement, or quota scope;
- ingestion, deletion, replacement, re-indexing, Qdrant collections, caches,
  checkpoints, migrations, rollback, or data retention;
- streaming, cancellation, retry, idempotency, timeouts, queues, or concurrent
  requests;
- provider secrets, encryption, audit logging, redaction, or public endpoints;
- retrieval, citations, chunking, reranking, prompt construction, or evaluation;
- React route/shell/auth changes and any UI change with state, responsive,
  accessibility, localization, or browser-security implications.

For low-risk documentation or isolated copy changes, the architect may record
the gate as not applicable with a reason. A high-risk change cannot merge until
this skill returns `PASS`.

## Inputs and independence

The reviewer receives the requirement/ACs, implementation diff, tests, normal
QA evidence, and the affected web journey. It must inspect source, tests,
fixtures, mocks, configuration, and evidence independently. It must not rely on
the implementer's summary or only rerun the happy path.

The reviewer is read-only. It must not edit production code or tests, weaken or
delete assertions, commit, change fixtures, alter credentials, mutate runtime
data, or approve an unmeasured claim. Browser checks use only the repository's
configured Playwright MCP tools and follow the project's prohibition on
arbitrary browser JavaScript.

## Challenge protocol

Try to disprove the implementation in each applicable area:

1. **Business invariants:** identify the invariant, then attempt an invalid
   state, forbidden transition, stale actor, or partial operation.
2. **Boundaries:** test empty, maximum, minimum, duplicate, malformed, expired,
   missing, reordered, repeated, and near-limit inputs.
3. **Tests and fixtures:** inspect assertions for tautologies, missing negative
   checks, over-broad mocks, unrealistic fixtures, unasserted response bodies,
   and tests that never exercise the real adapter or persistence boundary.
4. **Errors and time:** challenge timeout, cancellation, retry, backpressure,
   provider failure, database outage, partial write, and recovery semantics.
5. **State:** look for stale caches, invalidation gaps, restart behavior,
   replay/idempotency bugs, cross-request leakage, and stale browser tabs.
6. **Concurrency:** repeat operations, interleave actors, race updates, and
   compare behavior under the repository's stated concurrency/load threshold.
7. **Security and privacy:** attempt cross-user/tenant access, forged selectors,
   hostile Origin, missing CSRF, secret leakage, unsafe logs, path exposure,
   and privilege escalation without attacking external systems.
8. **UI:** inspect loading, empty, error, denied, disabled, keyboard, locale,
   responsive, focus, overflow, navigation, and truthful recovery states.

For every suspected weakness, produce a minimal reproduction or a concrete
reason it cannot be reproduced. Distinguish a product defect from a defective
test, a missing oracle, and an environment limitation.

## Verdicts and merge rule

- `PASS`: the reviewer attempted the applicable challenges, found no blocking
  counterexample, and attached artifact-backed evidence.
- `FAIL`: a reproducible invariant violation, security/data leak, incorrect
  behavior, inadequate test oracle, or missing required evidence was found.
- `INCONCLUSIVE`: the review could not exercise a required challenge because of
  missing tooling, unavailable fixtures, stale/contradictory artifacts, or an
  unmeasured critical claim.

`FAIL` and `INCONCLUSIVE` both block merge. The owner must fix the finding or
explicitly change the requirement/risk classification and rerun the gate. A
later run must use fresh evidence against the final tree.

## Required report

Return a Markdown report and machine-readable verdict with this shape:

```json
{
  "review": "adversarial-review",
  "verdict": "PASS | FAIL | INCONCLUSIVE",
  "commitOrTree": "<exact SHA or working-tree fingerprint>",
  "scope": ["FR-...", "files or journey"],
  "challenges": [
    {
      "area": "security | invariant | boundary | tests | errors | state | concurrency | ui",
      "hypothesis": "What could be false",
      "attempt": "Command, test, browser journey, or inspection performed",
      "result": "Counterexample or why it held",
      "evidence": ["absolute/path/to/artifact", "test::name"]
    }
  ],
  "findings": [
    {
      "id": "ADV-001",
      "severity": "critical | high | medium | low",
      "file": "absolute/path or test/artifact",
      "problem": "Concrete falsifiable finding",
      "reproduction": "Exact bounded reproduction",
      "requiredAction": "Fix or requirement decision"
    }
  ],
  "limitations": ["Only genuine environment or scope limits"],
  "mergeBlockers": ["Every FAIL or INCONCLUSIVE blocker"]
}
```

The report must name exact commands, test results, URLs/scenarios and
viewports for browser evidence, fixture/data-preservation boundaries, secret
redaction status, and any skipped challenge with its reason. Never include
credentials, cookies, tokens, raw provider secrets, private prompts, or raw
documents in the report.
