from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.api.mvp_publication_runtime import load_publication_enabled


def test_publication_runtime_gate_defaults_to_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("RAG_STUDIO_PUBLICATION_ENABLED", raising=False)

    assert load_publication_enabled() is False


def test_publication_runtime_gate_accepts_only_explicit_true(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RAG_STUDIO_PUBLICATION_ENABLED", " TRUE ")

    assert load_publication_enabled() is True


def test_publication_runtime_gate_rejects_ambiguous_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RAG_STUDIO_PUBLICATION_ENABLED", "yes")

    with pytest.raises(ValidationError):
        load_publication_enabled()
