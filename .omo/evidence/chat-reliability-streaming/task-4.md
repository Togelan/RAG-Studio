# Task 4 — true bounded streaming

- `stream_rag_graph` consumes LangGraph provider chunks, accumulates the completed answer server-side, and emits cached answers through the same protocol.
- `StreamLifecycleManager` enforces one stream per session and ten total streams with release in cancellation/failure/finalization paths.
- Real-socket benchmark: 10/10 HTTP 200; max active 10; p50 TTFT 95.59 ms; p95 TTFT 103.51 ms; p95 end-to-end 180.65 ms; overflow `503` with `Retry-After: 1`; same-session conflict `409`; RSS 189,718,528 bytes.

Verdict: PASS.
