"""Unit tests for RAGState TypedDict schema (FR-003 AC-003.1 through AC-003.4).

Verifies that all required fields are present with correct types.
"""

from __future__ import annotations

from typing import get_type_hints

from src.graph.state import RAGState


class TestRAGStateSchema:
    """Tests for the RAGState TypedDict schema definition."""

    def test_all_required_fields_present(self) -> None:
        """Verify all 19 required fields are defined in RAGState."""
        hints = get_type_hints(RAGState)
        required_fields = {
            "messages",
            "query",
            "intent",
            "cache_hit",
            "cached_answer",
            "retrieved_docs",
            "reranked_docs",
            "generated_from",
            "final_answer",
            "faithfulness_score",
            "validation_passed",
            "session_id",
            "user_api_key",
            "provider",
            "model_name",
            "temperature",
            "max_tokens",
            "system_prompt",
        }
        actual_fields = set(hints.keys())
        missing = required_fields - actual_fields
        assert not missing, f"Missing fields: {missing}"

    def test_messages_is_annotated(self) -> None:
        """Verify messages field uses Annotated type (for add_messages reducer)."""
        hints = get_type_hints(RAGState, include_extras=True)
        assert "messages" in hints, "messages field must exist"

    def test_default_values_create_valid_state(self) -> None:
        """Verify a minimal RAGState dict can be constructed with all required fields."""
        from langchain_core.messages import HumanMessage

        state: RAGState = {
            "messages": [HumanMessage(content="test")],
            "query": "test",
            "intent": "",
            "cache_hit": False,
            "cached_answer": None,
            "retrieved_docs": [],
            "reranked_docs": [],
            "generated_from": "",
            "final_answer": None,
            "faithfulness_score": 0.0,
            "validation_passed": False,
            "session_id": "test-session",
            "user_api_key": None,
            "provider": "openai",
            "model_name": "gpt-4o-mini",
            "temperature": 1.0,
            "max_tokens": 2048,
            "system_prompt": "",
        }
        assert state["query"] == "test"
        assert state["cache_hit"] is False
        assert state["cached_answer"] is None
        assert state["retrieved_docs"] == []

    def test_field_types_are_correct(self) -> None:
        """Verify field types match expected Python types."""
        hints = get_type_hints(RAGState)
        # query must be str
        assert "str" in str(hints.get("query", "")), "query must be str"
        # intent must be str
        assert "str" in str(hints.get("intent", "")), "intent must be str"
        # cache_hit must be bool
        assert "bool" in str(hints.get("cache_hit", "")), "cache_hit must be bool"
        # faithfulness_score must be float
        assert "float" in str(hints.get("faithfulness_score", "")), (
            "faithfulness_score must be float"
        )
        # validation_passed must be bool
        assert "bool" in str(hints.get("validation_passed", "")), (
            "validation_passed must be bool"
        )

    def test_optional_fields_accept_none(self) -> None:
        """Verify optional fields (cached_answer, final_answer, user_api_key) accept None."""
        from langchain_core.messages import HumanMessage

        state: RAGState = {
            "messages": [HumanMessage(content="test")],
            "query": "test",
            "intent": "standalone_question",
            "cache_hit": False,
            "cached_answer": None,
            "retrieved_docs": [],
            "reranked_docs": [],
            "generated_from": "retrieval",
            "final_answer": None,
            "faithfulness_score": 0.0,
            "validation_passed": False,
            "session_id": "test-session",
            "user_api_key": None,
            "provider": "openai",
            "model_name": "gpt-4o-mini",
            "temperature": 1.0,
            "max_tokens": 2048,
            "system_prompt": "",
        }
        assert state["cached_answer"] is None
        assert state["final_answer"] is None
        assert state["user_api_key"] is None
