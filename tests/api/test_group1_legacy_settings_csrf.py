from __future__ import annotations

from pathlib import Path


def test_legacy_settings_save_establishes_and_sends_double_submit_csrf_proof() -> None:
    script = Path("src/api/static/js/app.js").read_text(encoding="utf-8")

    assert "fetch('/api/saas/auth/csrf')" in script
    assert "'X-CSRF-Token': csrfToken" in script
