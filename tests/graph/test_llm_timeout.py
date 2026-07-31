"""Tests for defensive LLM request timeout configuration."""

import pytest

from src.graph.nodes import DEFAULT_LLM_REQUEST_TIMEOUT, get_llm_request_timeout


def test_missing_timeout_uses_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LLM_REQUEST_TIMEOUT", raising=False)

    assert get_llm_request_timeout() == DEFAULT_LLM_REQUEST_TIMEOUT


@pytest.mark.parametrize("value", ["0", "-1", "nan", "inf", "-inf", "invalid"])
def test_invalid_or_non_positive_timeout_uses_default(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("LLM_REQUEST_TIMEOUT", value)

    assert get_llm_request_timeout() == DEFAULT_LLM_REQUEST_TIMEOUT


@pytest.mark.parametrize("value, expected", [("0.25", 0.25), ("90", 90.0)])
def test_finite_positive_timeout_is_accepted(
    monkeypatch: pytest.MonkeyPatch, value: str, expected: float
) -> None:
    monkeypatch.setenv("LLM_REQUEST_TIMEOUT", value)

    assert get_llm_request_timeout() == expected
