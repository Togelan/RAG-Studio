# Task 3 — checkpoint and graph compatibility

- Graph outputs and stream payloads are normalized at mapping/list boundaries; malformed integer output produces a sanitized error rather than `'int' object is not subscriptable`.
- Restart/Unicode/checkpointer tests passed in the 337-test isolated regression set.
- Checkpointer logging records stage and exception type only, not prompt text, keys, or raw exception details.

Verdict: PASS.
