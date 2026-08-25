from __future__ import annotations

import json
from pathlib import Path


def _locale(locale: str) -> dict[str, str]:
    source = Path(__file__).parents[2] / "src" / "api" / "locales" / f"{locale}.json"
    return json.loads(source.read_text(encoding="utf-8"))


def test_personal_lab_locale_keys_have_exact_en_ru_parity() -> None:
    # Given: the backend-owned English and Russian locale maps.
    english = _locale("en")
    russian = _locale("ru")

    # When/Then: both languages expose the exact same Personal Lab contract.
    assert english.keys() == russian.keys()
    assert {
        "nav_knowledge",
        "personal_home_scope",
        "personal_home_path_title",
        "personal_home_knowledge",
        "personal_home_settings",
        "personal_home_chat",
        "personal_knowledge_region",
        "personal_knowledge_handoff",
    } <= english.keys()
    assert all(english[key].strip() and russian[key].strip() for key in english)
