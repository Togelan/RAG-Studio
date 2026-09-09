# Scripts Agent Guide

## Scope

`scripts/` contains manual benchmarks, model setup, fake-provider launchers,
and disposable QA orchestration. Scripts may mutate runtime state even though
they are not application code.

## Where To Look

| Task | Location | Notes |
| --- | --- | --- |
| Fake UI server | `run_chat_ui_fake.py` | Deterministic provider for browser QA. |
| Streaming benchmark | `benchmark_chat_streaming.py` | Real-socket bounded SSE/load checks. |
| Retrieval benchmark | `benchmark_personal_lab_retrieval.py` | Identity isolation, concurrency, p95 threshold. |
| Chunking benchmark | `benchmark_chunking_strategies.py` | Informational local-Qdrant comparison. |
| Model setup | `download_models.py` | Uses project-anchored `src.paths` caches. |
| Disposable QA | `qa/` | Isolated Stage 2/3, resilience, Stripe, and teardown workflows. |

## Conventions

- Use explicit data roots, ports, project names, and evidence directories. Keep
  waits bounded and reports/receipts sanitized.
- Benchmarks must state workload, concurrency, threshold, and failure result;
  do not describe unmeasured behavior as scalable or safe.
- Fake-provider and Stage 2 runs are credential-free where possible. Live Stripe
  runs are test-mode only and require strict preflight.
- Route persistent model/data paths through `src.paths`; do not rely on CWD.

## Anti-patterns

- Never use broad Docker cleanup, prune, unscoped volume removal, or restart
  checks that destroy persistence. Cleanup must be project/label scoped.
- Do not modify `.env`, operator credentials, production data, or unrelated
  evidence. Existing dirty script changes are user-owned.
- Do not print cookies, CSRF values, provider errors, file paths, raw prompts,
  document text, hosted-session tokens, or sensitive identifiers.
- Do not silently change benchmark load, timeout, quota, or concurrency bounds.

## Commands

```powershell
python scripts/qa/run_resilience_fake_qa.py --self-test --users 10
python scripts/benchmark_chat_streaming.py
python scripts/benchmark_chunking_strategies.py
```

For Docker/Stage 3, follow `scripts/qa/` and `docs/deployment/` instructions;
serialize Compose operations with `COMPOSE_PARALLEL_LIMIT=1`.
