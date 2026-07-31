# API test isolation worker

- Scope: `tests/api/test_chat_reliability.py` only, plus this evidence file.
- The `client` fixture sets `RAG_STUDIO_DATA_ROOT` to a unique `tmp_path` child
  before entering `TestClient`. App lifespan startup therefore opens its SQLite
  checkpointer outside the bind-mounted workspace and cannot touch runtime
  `rag-data`/`data`.
- This makes the Docker regression deterministic: without the fixture override,
  lifespan uses the workspace-backed data root and can reproduce the recorded
  SQLite disk I/O/locking failure; with it, SQLite is created in pytest-managed
  temporary storage.

Verification, 2026-07-31:

```text
docker run --rm -e PYTHONDONTWRITEBYTECODE=1 -v C:\\WORK\\MyCODE\\RAG-Studio:/workspace -w /workspace --entrypoint python rag-studio:latest -m pytest -p no:cacheprovider tests/graph/test_session.py tests/api/test_chat_reliability.py -q
6 passed, 65 warnings in 7.28s
```

No commit was created because the integration worktree contains unrelated
uncommitted production changes.
