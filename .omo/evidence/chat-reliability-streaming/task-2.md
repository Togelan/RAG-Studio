# Task 2 — persistent data safety

- `README.md` explains Compose volume persistence, why previous uploads/sessions reappear, supported UI deletion, and backup-first full reset.
- Session/checkpointer deletion failures return a safe non-success response; feedback/audit files resolve below `RAG_STUDIO_DATA_ROOT`.
- Tests used isolated data roots outside `rag-data`; no live SQLite or upload content was deleted.

Verdict: PASS.
