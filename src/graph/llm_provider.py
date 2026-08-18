from __future__ import annotations

import os
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from typing import Protocol

from langchain_core.messages import BaseMessage, BaseMessageChunk
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from src.graph.retry import RetryingLLMProvider, RetryPolicy


@dataclass(frozen=True, slots=True)
class LLMProviderConfig:
    provider: str
    base_url: str | None
    model: str
    api_key: SecretStr | None
    temperature: float
    max_tokens: int
    deadline: float


class LLMProvider(Protocol):
    async def ainvoke(self, messages: Sequence[BaseMessage]) -> BaseMessage: ...

    def astream(
        self,
        messages: Sequence[BaseMessage],
    ) -> AsyncIterator[BaseMessageChunk]: ...


class LLMProviderFactory(Protocol):
    def __call__(self, config: LLMProviderConfig) -> LLMProvider: ...


class _ChatOpenAIAdapter:
    def __init__(self, config: LLMProviderConfig) -> None:
        self._client = ChatOpenAI(
            model=config.model,
            api_key=config.api_key,
            base_url=config.base_url,
            temperature=config.temperature,
            max_tokens=config.max_tokens,  # type: ignore[call-arg]  # LangChain stub omits supported kwarg.
            timeout=config.deadline,
        )

    async def ainvoke(self, messages: Sequence[BaseMessage]) -> BaseMessage:
        return await self._client.ainvoke(list(messages))

    async def astream(
        self,
        messages: Sequence[BaseMessage],
    ) -> AsyncIterator[BaseMessageChunk]:
        async for chunk in self._client.astream(list(messages)):
            yield chunk


class ChatOpenAIProvider:
    def __init__(self, config: LLMProviderConfig) -> None:
        self._client = RetryingLLMProvider(
            _ChatOpenAIAdapter(config),
            policy=RetryPolicy(deadline=config.deadline),
        )

    async def ainvoke(self, messages: Sequence[BaseMessage]) -> BaseMessage:
        return await self._client.ainvoke(list(messages))

    async def astream(
        self,
        messages: Sequence[BaseMessage],
    ) -> AsyncIterator[BaseMessageChunk]:
        async for chunk in self._client.astream(list(messages)):
            yield chunk


class OpenAIProviderFactory:
    def __call__(self, config: LLMProviderConfig) -> LLMProvider:
        return ChatOpenAIProvider(config)


def provider_base_url(provider: str) -> str | None:
    match provider:
        case "deepseek":
            return os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
        case "anthropic":
            return "https://api.anthropic.com/v1"
        case "ollama":
            return os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
        case _:
            return None
