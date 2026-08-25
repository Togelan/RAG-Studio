# ADR-0004: Independent adversarial QA gate

## Status

Accepted

## Context

Normal tests and review establish intended behavior, but they can share the
same assumptions as the implementation. RAG-Studio has high-impact boundaries
where a superficially green suite can still miss cross-identity leakage,
stale state, replacement rollback failure, concurrency races, weak fixtures,
or misleading UI recovery. The project needs an independent attempt to
disprove high-risk changes before merge.

## Decision

Add the read-only `adversarial-qa` agent and `adversarial-review` skill after
normal implementation and standard QA for high-risk changes. The reviewer
receives the actual final diff and evidence, challenges the areas defined by the
skill, and returns artifact-backed `PASS`, `FAIL`, or `INCONCLUSIVE`.

Only `PASS` permits merge. `FAIL` and `INCONCLUSIVE` block merge until the
finding is fixed, the requirement is explicitly revised, or the missing
evidence/tooling is supplied and the review is rerun on fresh evidence.

Ownership remains clear: @dev fixes implementation defects, @qa owns normal
functional/quality verification, @architect owns risk classification and merge
decisions, and adversarial-qa only reports independent findings. The owner
escalates requirement ambiguity to @architect/BA and security or data-leak
findings immediately; no reviewer silently downgrades them.

## Alternatives considered

1. **Rely on the existing @qa pass.** Rejected because the implementer and
   normal verifier can share fixtures, assumptions, and happy-path oracles.
   Revisit only if an external, independent assurance process replaces this
   gate with equivalent evidence.
2. **Run only broad fuzz/property tests in CI.** Rejected because fuzzing alone
   does not inspect mocks, UI truthfulness, migration boundaries, or missing
   security assertions. Revisit when the repository has maintained property
   suites covering those dimensions and an equivalent independent reviewer.
3. **Make adversarial QA mandatory for every documentation/copy change.**
   Rejected as disproportionate; low-risk changes may record “not applicable,”
   while high-risk classifications remain mandatory.

## Consequences

The gate adds review time and may block a merge when tooling or fixtures are
insufficient, which is intentional. In return, the project records explicit
counterexample attempts, exposes weak tests before merge, and keeps security,
data preservation, cancellation, concurrency, and UI recovery claims bounded.
The reviewer is read-only, so remediation remains with the normal owners and
does not create competing production edits.
