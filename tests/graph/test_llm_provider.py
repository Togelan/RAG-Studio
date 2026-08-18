from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, HumanMessage
from pydantic import SecretStr

from src.graph.llm_provider import (
    LLMProviderConfig,
    OpenAIProviderFactory,
    provider_base_url,
)
from src.graph.nodes import analyzer_node, generate_from_retrieval_node, validate_node
from src.graph.state import RAGState


class _FakeProvider:
    def __init__(self, response: str) -> None:
        self._response = response

    async def ainvoke(self, messages: Sequence[BaseMessage]) -> BaseMessage:
        return AIMessage(content=self._response)

    async def astream(
        self,
        messages: Sequence[BaseMessage],
    ) -> AsyncIterator[AIMessageChunk]:
        yield AIMessageChunk(content=self._response)


class _RecordingFactory:
    def __init__(self, response: str) -> None:
        self.configs: list[LLMProviderConfig] = []
        self._response = response

    def __call__(self, config: LLMProviderConfig) -> _FakeProvider:
        self.configs.append(config)
        return _FakeProvider(self._response)


def _state() -> RAGState:
    return {
        "messages": [HumanMessage(content="Question")],
        "query": "Question",
        "intent": "",
        "cache_hit": False,
        "cached_answer": None,
        "retrieved_docs": [],
        "reranked_docs": [],
        "generated_from": "",
        "final_answer": None,
        "faithfulness_score": 0.0,
        "validation_passed": False,
        "session_id": "provider-test",
        "user_api_key": "secret-value",
        "provider": "deepseek",
        "model_name": "model-under-test",
        "temperature": 0.61,
        "max_tokens": 733,
        "system_prompt": "",
    }


def test_chat_openai_adapter_forwards_typed_config() -> None:
    config = LLMProviderConfig(
        provider="deepseek",
        base_url="https://provider.invalid/v1",
        model="model-under-test",
        api_key=SecretStr("secret-value"),
        temperature=0.61,
        max_tokens=733,
        deadline=17.5,
    )

    with patch("src.graph.llm_provider.ChatOpenAI") as chat_openai:
        OpenAIProviderFactory()(config)

    chat_openai.assert_called_once_with(
        model="model-under-test",
        api_key=config.api_key,
        base_url="https://provider.invalid/v1",
        temperature=0.61,
        max_tokens=733,
        timeout=17.5,
    )


def test_deepseek_uses_explicit_server_endpoint_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: the isolated Stage 3 provider endpoint is configured server-side.
    monkeypatch.setenv("DEEPSEEK_BASE_URL", "http://stage3-fake-deepseek:8080/v1")

    # When: the DeepSeek provider endpoint is resolved for graph execution.
    endpoint = provider_base_url("deepseek")

    # Then: the explicit local endpoint is used instead of the production API.
    assert endpoint == "http://stage3-fake-deepseek:8080/v1"


@pytest.mark.asyncio
async def test_analyzer_forwards_state_config_to_factory() -> None:
    factory = _RecordingFactory("standalone")

    with patch("src.graph.nodes.LLM_REQUEST_TIMEOUT", 17.5):
        result = await analyzer_node(_state(), provider_factory=factory)

    assert result["intent"] == "standalone_question"
    assert factory.configs == [
        LLMProviderConfig(
            provider="deepseek",
            base_url="https://api.deepseek.com/v1",
            model="model-under-test",
            api_key=SecretStr("secret-value"),
            temperature=0.0,
            max_tokens=733,
            deadline=17.5,
        )
    ]


@pytest.mark.asyncio
async def test_generation_forwards_temperature_to_factory() -> None:
    factory = _RecordingFactory("Generated answer")

    with patch("src.graph.nodes.get_stream_writer", return_value=MagicMock()):
        result = await generate_from_retrieval_node(
            _state(),
            provider_factory=factory,
        )

    assert result["final_answer"] == "Generated answer"
    assert factory.configs[0].temperature == 0.61


@pytest.mark.asyncio
async def test_validator_forwards_bounded_config_to_factory() -> None:
    factory = _RecordingFactory("0.9")
    state = _state()
    state["generated_from"] = "retrieval"
    state["final_answer"] = "Grounded"
    state["retrieved_docs"] = [{"text": "Grounded", "score": 1.0, "metadata": {}}]

    with patch("src.graph.nodes.LLM_REQUEST_TIMEOUT", 17.5):
        result = await validate_node(state, provider_factory=factory)

    assert result["validation_passed"] is True
    assert factory.configs[0].temperature == 0.0
    assert factory.configs[0].deadline == 17.5
