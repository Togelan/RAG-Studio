# Adversarial QA workflow

## Goal

Give RAG-Studio an independent pre-merge attempt to falsify high-risk changes,
not another checklist that only confirms passing tests.

## Gate sequence

1. @architect classifies the change and records the affected FRs, risk, and
   required web journey.
2. @dev implements and returns `DEV_RESULT`.
3. @qa runs the normal AC, quality, security, RAGAS, and configured Playwright
   checks and returns `QA_VERDICT`.
4. `adversarial-qa` reads the final diff, requirements, tests, fixtures, and QA
   evidence and actively attacks the assumptions.
5. @architect reviews the structured report. Only `PASS` may proceed to merge;
   `FAIL` or `INCONCLUSIVE` returns to remediation or explicit requirement/tool
   escalation.
6. After a fix, rerun normal QA and adversarial QA against fresh evidence.

## Mandatory scope

The gate is mandatory for authentication/CSRF/Origin, identity and roles,
Personal Lab/Workspace/Agent/Widget/billing/quota, ingestion/re-index/delete,
Qdrant/vector/cache/checkpoint/migration/rollback, streaming/cancellation/
concurrency, provider secrets/encryption/redaction, retrieval/citations,
public endpoints, and stateful or responsive React UI changes. It is optional
for isolated documentation or copy changes when @architect records why.

## Challenge coverage

The reviewer must cover applicable business invariants, boundary values, weak
test oracles, incorrect mocks/fixtures, timeout/error behavior, stale caches,
repeated and concurrent requests, security/data-leak paths, persistence and
rollback, and UI loading/empty/error/denied/accessibility/locale/responsive
states. It must record exact commands, test names, artifacts, URLs/scenarios,
viewports, and redaction results without exposing secrets or private data.

## Invocation

The architect invokes the agent with a self-contained handoff, for example:

```text
@adversarial-qa Review FR-023 against the final current tree.
Read the implementation diff, tests, fixtures, normal QA evidence, and the
affected Personal Lab browser journey. Follow the adversarial-review skill.
Do not edit files or data. Return the required structured report.
```

The report is stored under `.omo/evidence/<feature>/adversarial-qa/` and is
linked from the review/merge record. No credentials, cookies, provider keys,
raw prompts, documents, or raw error payloads may appear in evidence.
