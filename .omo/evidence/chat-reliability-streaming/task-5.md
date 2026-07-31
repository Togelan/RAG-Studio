# Task 5 — browser stream lifecycle

- In-app browser against the delayed fake provider displayed `Привет, это потоковый ` before completion, then the complete cited answer.
- Stop removed the partial assistant node and restored controls; navigation to Settings during a stream did not crash.
- Switching from session `e67074d0-37da-4992-9d90-777ee1a31ce1` to `844cfce8-7f52-4ed6-a6ec-89508775b0ca` during generation left no streaming node or partial assistant message and rendered only the selected session's persisted messages.
- `node tests/js/test_sse_parser.mjs` passed fragmented UTF-8, CRLF, and malformed-frame checks.

Verdict: PASS.
