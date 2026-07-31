---
slug: chat-reliability-streaming
status: awaiting-approval
intent: clear
review_required: false
pending-action: write .omo/plans/chat-reliability-streaming.md
approach: preserve persistent user data; repair the checkpointer boundary and cancellation lifecycle; replace simulated output with bounded real provider-token SSE; add decision-evidence requirements to canonical project guidance.
---

# Draft: chat-reliability-streaming

## Components (topology ledger)
<!-- Lock the SHAPE before depth. One row per top-level component that can succeed or fail independently. -->
<!-- id | outcome (one line) | status: active|deferred | evidence path -->

## Open assumptions (announced defaults)
<!-- Record any default you adopt instead of asking, so the user can veto it at the gate. -->
<!-- assumption | adopted default | rationale | reversible? -->

## Findings (cited - path:lines)

## Decisions (with rationale)

## Scope IN

## Scope OUT (Must NOT have)

## Open questions

## Approval gate
status: drafting
<!-- When exploration is exhausted and unknowns are answered, set status: awaiting-approval. -->
<!-- That durable record is the loop guard: on a later turn read it and resume at the gate instead of re-running exploration. -->

| Component | Outcome | Status | Evidence |
| --- | --- | --- | --- |
| Persisted runtime data | Explain and safely preserve prior uploads and chats; provide supported cleanup | active | docker-compose.yml:26-43; src/api/routes/chat.py:96-160, 614-723; src/ingestion/router.py:962-968 |
| New-session reliability | Remove malformed persistence/state failures and make errors diagnosable without leaking content | active | src/graph/builder.py:266-558, 629-675; src/api/routes/chat.py:282-402 |
| Navigation and cancellation | A stream cannot corrupt another session or crash when leaving chat | active | src/api/static/js/chat.js:20-179, 752-898; src/api/routes/chat.py:282-402 |
| Genuine streaming and load limits | Deliver provider token output with bounded concurrency, cancellation, and responsive rendering | active | src/api/routes/chat.py:261-402; src/graph/nodes.py:407-438; src/api/static/js/chat.js:109-194 |
| Engineering decision evidence | Require rationale, alternatives, resilience, and safety evidence before implementation/DoD | active | AGENTS.md; .agents/copilot-instructions.md; .agents/agents/*.md |

## Open assumptions (announced defaults)

| Assumption | Adopted default | Rationale | Reversible? |
| --- | --- | --- | --- |
| Existing raw uploads and sessions | Preserve them; never auto-delete runtime volume content | User confirmed volume persistence is acceptable; automatic cleanup destroys user data | no |
| Data cleanup | Add/document supported per-document and per-session deletion; only offer a separate explicit full-volume reset workflow | Avoids deleting unknown user data or mutating SQLite directly | yes |
| Streaming transport | Retain POST + fetch + SSE | Fits one-way LLM tokens and current stack; WebSockets add proxy/session complexity without a demonstrated need | yes |
| Stream admission | Bounded global capacity plus one active stream per session, with fast 429/503 and Retry-After | Meets 10-concurrent-user NFR without unbounded work/queues and prevents cross-session races | yes |
| Test strategy | Tests-after with focused unit/integration/browser/lifecycle tests and a 10-session benchmark | Existing tests establish partial SSE/session coverage; new regression cases require deterministic fakes | yes |

## Findings (cited - path:lines)

- `raw_test_data.md` and `??? ????? ????` are persisted user/runtime state in `rag-data`, not Docker image seed data: Dockerfile copies `src/`; `.dockerignore` excludes data; Compose bind-mounts `rag-data`; audit/session title files contain the prior records.
- Current SSE is simulated: the route awaits whole-graph `ainvoke`, splits the completed answer, and sleeps between words. The browser also discards fragmented SSE frames and re-renders the whole conversation per token.
- The new-session TypeError cannot be reconstructed from retained logs. The custom full `AsyncSqliteSaver` protocol is the highest-risk serialization boundary; an upstream stock-saver pattern is available for comparison. The plan will not claim the exact root cause until a reproducing regression test identifies it.
- Navigation/session switching lacks AbortController use, page lifecycle cancellation, server disconnect detection, and a request/session identity guard.
- The existing user-edited `AGENTS.md`, `.agents/copilot-instructions.md`, and `README.md` are dirty worktree inputs; preserve their content and avoid overwriting unrelated changes.

## Decisions (with rationale)

- Repair persistence using the smallest compatible stock-saver/serializer approach, plus strict graph-result boundary validation and redacted stage/type logging. It reduces long-term maintenance risk versus retaining a hand-written full saver protocol.
- Stream only after retrieval/grounding prerequisites and retain final validation/cache writes. Never bypass RAG safeguards merely to reduce time-to-first-token.
- Treat cancellation as a first-class normal state: abort client request, propagate `CancelledError`, stop work on disconnect, and do not save partial assistant messages unless an explicit resumable design is later requested.
- Apply the decision-evidence policy in the canonical instructions and role-specific BA/architect/developer/QA guidance, including two considered alternatives, bounded-load behavior, and safety evidence.

## Scope IN

- Provenance UX/docs and non-destructive cleanup guidance for persistent uploads/chats.
- New-session persistence regression and error-observability repair.
- Cancellation-safe navigation/session switching.
- Real provider-token SSE, frame-safe browser parsing, throttled rendering, bounded admission, progress/heartbeats, and benchmark evidence.
- Project instruction/role updates implementing the requested rationale/load/alternatives/safety requirement.

## Scope OUT (Must NOT have)

- Automatic deletion or reset of `rag-data`, existing uploads, sessions, Qdrant points, or SQLite state.
- Replacing FastAPI/LangGraph/Jinja2/vanilla JavaScript or adding WebSockets without a new requirement.
- Returning raw server tracebacks, user prompts, or API keys to the browser/logs.
- Claiming a specific TypeError root cause without a reproduction.

## Open questions

None. The persistent-data decision is resolved by the user's "if volume so ok" statement; all other choices have safe reversible defaults.

## Approval gate
status: awaiting-approval
Approach: build a regression-first reliability and genuine-streaming plan that preserves user data, moves risky checkpoint serialization toward the supported saver behavior, makes cancellation/load behavior bounded, and embeds decision evidence in canonical guidance.
Next workflow action: after approval, create `.omo/plans/chat-reliability-streaming.md`; then start execution only through the separately requested `ulw-loop` worker workflow.
