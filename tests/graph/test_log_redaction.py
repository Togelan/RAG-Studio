"""Regression coverage for graph log redaction."""

from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from _pytest.logging import LogCaptureFixture
from langchain_core.messages import HumanMessage

from src.graph.nodes import analyzer_node
from src.graph.state import RAGState


@pytest.mark.asyncio
async def test_analyzer_log_excludes_user_query(
    caplog: LogCaptureFixture,
) -> None:
    """Analyzer telemetry records classification without user input."""
    # Given: a user query that must not enter the operator log stream.
    user_query = "private-stage3-log-redaction-sentinel"
    response = SimpleNamespace(content="standalone")
    llm = MagicMock()
    llm.ainvoke = AsyncMock(return_value=response)
    state: RAGState = {
        "messages": [HumanMessage(content=user_query)],
        "query": user_query,
        "intent": "",
        "cache_hit": False,
        "cached_answer": None,
        "retrieved_docs": [],
        "reranked_docs": [],
        "generated_from": "",
        "final_answer": None,
        "faithfulness_score": 0.0,
        "validation_passed": False,
        "session_id": "log-redaction-session",
        "user_api_key": None,
        "provider": "deepseek",
        "model_name": "stage3-deterministic",
        "temperature": 0.0,
        "max_tokens": 32,
        "system_prompt": "",
    }

    # When: the analyzer classifies the request.
    with (
        caplog.at_level(logging.INFO),
        patch(
            "src.graph.llm_provider.ChatOpenAI",
            return_value=llm,
        ),
    ):
        result = await analyzer_node(state)

    # Then: the classification is logged without the submitted content.
    assert result["intent"] == "standalone_question"
    assert user_query not in caplog.text
    assert "Analyzer: intent=standalone_question" in caplog.text
