from __future__ import annotations

import tomllib
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def test_ruff_excludes_only_the_protected_non_utf8_debug_journal() -> None:
    configuration = tomllib.loads(
        (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )
    ruff_configuration = configuration["tool"]["ruff"]
    assert ruff_configuration["extend-exclude"] == [".debug-journal.md"]
