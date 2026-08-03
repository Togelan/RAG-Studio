from __future__ import annotations

import logging
import random as random_module
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Final, Literal, Protocol

import anyio
import httpx
from langchain_core.messages import BaseMessage, BaseMessageChunk
from openai import APIConnectionError, APIStatusError, APITimeoutError

logger = logging.getLogger(__name__)

RETRYABLE_STATUS_CODES: Final = frozenset({429, 500, 502, 503, 504})

type FailureCode = Literal[
    "provider_temporary_unavailable",
    "provider_request_failed",
]
type ProviderStage = Literal["invoke", "stream"]


class Provider(Protocol):
    async def ainvoke(self, messages: Sequence[BaseMessage]) -> BaseMessage: ...

    def astream(
        self,
        messages: Sequence[BaseMessage],
    ) -> AsyncIterator[BaseMessageChunk]: ...


class RetryConfigurationError(ValueError):
    __slots__ = ("field",)

    def __init__(self, field: str) -> None:
        self.field = field
        super().__init__(field)

    def __str__(self) -> str:
        return f"invalid retry configuration field: {self.field}"


class ProviderFailureError(Exception):
    __slots__ = ("attempt", "code", "retryable", "stage")

    def __init__(
        self,
        *,
        code: FailureCode,
        retryable: bool,
        stage: ProviderStage,
        attempt: int,
    ) -> None:
        self.code = code
        self.retryable = retryable
        self.stage = stage
        self.attempt = attempt
        super().__init__(code)

    def __str__(self) -> str:
        return self.code


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    total_attempts: int = 3
    base_delay: float = 0.25
    multiplier: float = 2.0
    max_delay: float = 1.0
    jitter_ratio: float = 0.25
    deadline: float = 15.0

    def __post_init__(self) -> None:
        fields = (
            ("total_attempts", self.total_attempts == 3),
            ("base_delay", self.base_delay > 0),
            ("multiplier", self.multiplier >= 1),
            ("max_delay", self.max_delay >= self.base_delay),
            ("jitter_ratio", 0 <= self.jitter_ratio <= 0.25),
            ("deadline", self.deadline > 0),
        )
        for field_name, valid in fields:
            if not valid:
                raise RetryConfigurationError(field=field_name)

    def delay(self, retry_number: int, random_value: float) -> float:
        bounded_random = min(1.0, max(0.0, random_value))
        exponential = self.base_delay * self.multiplier ** (retry_number - 1)
        base = min(self.max_delay, exponential)
        jittered = base * (1 + self.jitter_ratio * bounded_random)
        return min(self.max_delay, jittered)


class RetryingLLMProvider:
    def __init__(
        self,
        provider: Provider,
        *,
        policy: RetryPolicy,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = anyio.sleep,
        random: Callable[[], float] = random_module.random,
    ) -> None:
        self._provider = provider
        self._policy = policy
        self._monotonic = monotonic
        self._sleep = sleep
        self._random = random

    async def ainvoke(self, messages: Sequence[BaseMessage]) -> BaseMessage:
        started_at = self._monotonic()
        for attempt in range(1, self._policy.total_attempts + 1):
            remaining = self._remaining(started_at)
            if remaining <= 0:
                raise self._terminal("invoke", attempt, retryable=True)
            try:
                with anyio.fail_after(remaining):
                    return await self._provider.ainvoke(messages)
            except Exception as error:  # noqa: BLE001, BROAD_EXCEPT_OK - typed boundary redacts SDK failures.
                await self._handle_failure(error, "invoke", attempt, started_at)
        raise AssertionError("unreachable retry loop")

    async def astream(
        self,
        messages: Sequence[BaseMessage],
    ) -> AsyncIterator[BaseMessageChunk]:
        started_at = self._monotonic()
        emitted_token = False
        for attempt in range(1, self._policy.total_attempts + 1):
            remaining = self._remaining(started_at)
            if remaining <= 0:
                raise self._terminal("stream", attempt, retryable=True)
            try:
                with anyio.fail_after(remaining):
                    async for chunk in self._provider.astream(messages):
                        content = chunk.content
                        if isinstance(content, str) and content:
                            emitted_token = True
                        yield chunk
                return
            except Exception as error:  # noqa: BLE001, BROAD_EXCEPT_OK - typed boundary redacts SDK failures.
                if emitted_token:
                    raise self._terminal(
                        "stream",
                        attempt,
                        retryable=_is_retryable(error),
                    ) from None
                await self._handle_failure(error, "stream", attempt, started_at)

    def _remaining(self, started_at: float) -> float:
        return self._policy.deadline - (self._monotonic() - started_at)

    async def _handle_failure(
        self,
        error: Exception,
        stage: ProviderStage,
        attempt: int,
        started_at: float,
    ) -> None:
        retryable = _is_retryable(error)
        logger.warning(
            "Provider request failed: stage=%s type=%s attempt=%d",
            stage,
            type(error).__name__,
            attempt,
        )
        if not retryable or attempt >= self._policy.total_attempts:
            raise self._terminal(stage, attempt, retryable=retryable) from None

        delay = self._policy.delay(attempt, self._random())
        if delay >= self._remaining(started_at):
            raise self._terminal(stage, attempt, retryable=True) from None
        await self._sleep(delay)

    @staticmethod
    def _terminal(
        stage: ProviderStage,
        attempt: int,
        *,
        retryable: bool,
    ) -> ProviderFailureError:
        code: FailureCode = (
            "provider_temporary_unavailable" if retryable else "provider_request_failed"
        )
        return ProviderFailureError(
            code=code,
            retryable=retryable,
            stage=stage,
            attempt=attempt,
        )


def _is_retryable(error: Exception) -> bool:
    match error:  # noqa: MATCH_OK - exceptions are an open external SDK hierarchy.
        case APITimeoutError() | APIConnectionError():
            return True
        case APIStatusError(status_code=status_code):
            return status_code in RETRYABLE_STATUS_CODES
        case (
            httpx.TimeoutException()
            | httpx.ConnectError()
            | TimeoutError()
            | ConnectionError()
        ):
            return True
        case _:
            return False
