"""Repository-wide pytest isolation defaults."""

from __future__ import annotations

import os

# Application modules are imported during test collection, before fixtures can
# adjust middleware settings. Keep rate limiting enabled in dedicated middleware
# tests while preventing unrelated endpoint tests from sharing one TestClient IP
# quota across the complete suite.
os.environ.setdefault("RAG_STUDIO_CHAT_RPM_LIMIT", "100000")
os.environ.setdefault("RAG_STUDIO_UPLOAD_RPM_LIMIT", "100000")
os.environ.setdefault("RAG_STUDIO_GENERAL_RPM_LIMIT", "100000")
