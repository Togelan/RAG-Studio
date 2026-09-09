# QA Scripts Guide

## Scope

`scripts/qa/` owns deterministic fake runtimes and high-risk Docker/Stage 3
verification. It is an operational boundary, not a second production app.

## Where To Look

| Task | Location | Notes |
| --- | --- | --- |
| Isolated server | `stage2_qa_runtime.py`, `stage2_qa_app.py` | Guarded serve/cleanup and fake FastAPI app. |
| Stage 2 state | `stage2_qa_state.py`, `stage2_qa_documents.py` | Deterministic state, snapshots, re-ingest, restore. |
| Resilience | `run_resilience_fake_qa.py` | Credential-free, exactly 10-user contract. |
| Personal Lab QA | `group2_personal_lab_qa.ps1` | SaaS/legacy lifecycle, outages, rollback, receipts. |
| Billing/widget QA | `mvp_stage3_stripe_qa.ps1` | Signed fixtures, optional test-mode Stripe, teardown. |

## Conventions

- Stage 2 roots are disposable, lease-marked, private, and rejected when
  populated or unsafe. Cleanup requires a matching lease and a stopped server.
- Docker harnesses use unique project names, exact labels, serialized Compose
  actions, bounded health checks, and sanitized JSON receipts.
- Restart and dependency-failure scenarios preserve volumes and verify the
  target app remains healthy. Teardown removes only generated resources.
- Live Stripe flows restore the operator environment and require webhook-ledger
  evidence before Portal checks.

## Anti-patterns

- Never broaden cleanup to unrelated containers, networks, volumes, images,
  evidence roots, or project state. Never use Docker prune.
- Do not run live/test harnesses with production credentials or emit secrets,
  cookies, CSRF values, raw provider errors, or filesystem paths.
- Do not replace production behavior with fake-runtime behavior in `src/`.
- Do not claim a QA pass without the receipt, exact scenario, measured bound,
  observed failure behavior, and preserved-data check.

## Commands

```powershell
python scripts/qa/run_resilience_fake_qa.py --self-test --users 10
pwsh scripts/qa/mvp_stage3_stripe_qa.ps1 -Scenario Preflight -StripeMode SignedFixture
```

For Compose, inspect Docker `version` and `ps -a` first and set
`COMPOSE_PARALLEL_LIMIT=1`; use the deployment runbook for the full sequence.
