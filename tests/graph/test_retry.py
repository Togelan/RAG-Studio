from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from typing import assert_never

import anyio
import httpx
import pytest
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    BaseMessageChunk,
    HumanMessage,
)
from openai import APIStatusError

from src.graph.retry import (
    ProviderFailureError,
    RetryConfigurationError,
    RetryingLLMProvider,
    RetryPolicy,
)


@dataclass(slots=True)  # noqa: MUTABLE_OK
class PinProvider:
    """Accumulate provider calls for observable assertions."""

    calls: list[tuple[str, ...]] = field(default_factory=list)

    async def ainvoke(self, messages: Sequence[BaseMessage]) -> BaseMessage:
        self.calls.append(tuple(str(message.content) for message in messages))
        return AIMessage(content="exact-output")

    async def astream(
        self,
        messages: Sequence[BaseMessage],
    ) -> AsyncIterator[BaseMessageChunk]:
        del messages
        if False:
            yield BaseMessageChunk(content="")


@dataclass(slots=True)  # noqa: MUTABLE_OK
class FakeClock:
    """Advance deterministic time while recording requested sleeps."""

    now: float = 0.0
    delays: list[float] = field(default_factory=list)

    def monotonic(self) -> float:
        return self.now

    async def sleep(self, delay: float) -> None:
        self.delays.append(delay)
        self.now += delay


@dataclass(slots=True)  # noqa: MUTABLE_OK
class FailingThenSuccessfulProvider:
    """Consume a scripted failure counter across retry attempts."""

    failures_remaining: int
    calls: int = 0

    async def ainvoke(self, messages: Sequence[BaseMessage]) -> BaseMessage:
        del messages
        self.calls += 1
        if self.failures_remaining:
            self.failures_remaining -= 1
            raise TimeoutError
        return AIMessage(content="recovered")

    async def astream(
        self,
        messages: Sequence[BaseMessage],
    ) -> AsyncIterator[BaseMessageChunk]:
        del messages
        if False:
            yield BaseMessageChunk(content="")


@dataclass(slots=True)  # noqa: MUTABLE_OK
class ScriptedStreamProvider:
    """Consume ordered stream attempts while recording call count."""

    attempts: list[list[str | Exception]]
    calls: int = 0

    async def ainvoke(self, messages: Sequence[BaseMessage]) -> BaseMessage:
        del messages
        raise NotImplementedError

    async def astream(
        self,
        messages: Sequence[BaseMessage],
    ) -> AsyncIterator[BaseMessageChunk]:
        del messages
        events = self.attempts[self.calls]
        self.calls += 1
        for event in events:
            match event:
                case str() as token:
                    yield AIMessageChunk(content=token)
                case Exception() as error:
                    raise error
                case unreachable:
                    assert_never(unreachable)


@dataclass(slots=True)  # noqa: MUTABLE_OK
class TimedFailureProvider:
    """Advance the fake clock during each provider attempt."""

    clock: FakeClock
    elapsed: float
    calls: int = 0

    async def ainvoke(self, messages: Sequence[BaseMessage]) -> BaseMessage:
        del messages
        self.calls += 1
        self.clock.now += self.elapsed
        raise TimeoutError

    async def astream(
        self,
        messages: Sequence[BaseMessage],
    ) -> AsyncIterator[BaseMessageChunk]:
        del messages
        if False:
            yield BaseMessageChunk(content="")


@dataclass(slots=True)  # noqa: MUTABLE_OK
class PermanentFailureProvider:
    """Record one permanent provider failure invocation."""

    error: Exception
    calls: int = 0

    async def ainvoke(self, messages: Sequence[BaseMessage]) -> BaseMessage:
        del messages
        self.calls += 1
        raise self.error

    async def astream(
        self,
        messages: Sequence[BaseMessage],
    ) -> AsyncIterator[BaseMessageChunk]:
        del messages
        if False:
            yield BaseMessageChunk(content="")


def status_error(status_code: int) -> APIStatusError:
    request = httpx.Request("POST", "https://provider.invalid/chat")
    response = httpx.Response(status_code, request=request)
    return APIStatusError("redacted-test-error", response=response, body=None)


@pytest.mark.asyncio
async def test_provider_contract_pin_has_one_call_and_exact_output() -> None:
    provider = PinProvider()
    messages = [HumanMessage(content="exact-input")]

    response = await provider.ainvoke(messages)

    assert response.content == "exact-output"
    assert provider.calls == [("exact-input",)]


@pytest.mark.asyncio
async def test_retry_boundary_uses_three_attempts_and_exact_backoff() -> None:
    clock = FakeClock()
    provider = FailingThenSuccessfulProvider(failures_remaining=2)
    retrying = RetryingLLMProvider(
        provider,
        policy=RetryPolicy(),
        monotonic=clock.monotonic,
        sleep=clock.sleep,
        random=lambda: 0.0,
    )

    response = await retrying.ainvoke([HumanMessage(content="retry")])

    assert response.content == "recovered"
    assert provider.calls == 3
    assert clock.delays == [0.25, 0.5]


@pytest.mark.asyncio
async def test_retry_policy_uses_exact_maximum_jitter_delays() -> None:
    clock = FakeClock()
    provider = FailingThenSuccessfulProvider(failures_remaining=2)
    retrying = RetryingLLMProvider(
        provider,
        policy=RetryPolicy(),
        monotonic=clock.monotonic,
        sleep=clock.sleep,
        random=lambda: 1.0,
    )

    response = await retrying.ainvoke([HumanMessage(content="retry")])

    assert response.content == "recovered"
    assert provider.calls == 3
    assert clock.delays == [0.3125, 0.625]


@pytest.mark.asyncio
async def test_deadline_stops_before_sleep_or_second_call() -> None:
    clock = FakeClock()
    provider = TimedFailureProvider(clock=clock, elapsed=14.8)
    retrying = RetryingLLMProvider(
        provider,
        policy=RetryPolicy(),
        monotonic=clock.monotonic,
        sleep=clock.sleep,
        random=lambda: 0.0,
    )

    with pytest.raises(ProviderFailureError) as raised:
        await retrying.ainvoke([HumanMessage(content="deadline")])

    assert raised.value.code == "provider_temporary_unavailable"
    assert provider.calls == 1
    assert clock.delays == []


@pytest.mark.asyncio
async def test_permanent_provider_error_fails_once() -> None:
    provider = PermanentFailureProvider(error=status_error(401))
    retrying = RetryingLLMProvider(provider, policy=RetryPolicy())

    with pytest.raises(ProviderFailureError) as raised:
        await retrying.ainvoke([HumanMessage(content="auth")])

    assert raised.value.code == "provider_request_failed"
    assert raised.value.retryable is False
    assert provider.calls == 1


@pytest.mark.asyncio
async def test_malformed_provider_output_is_safe_and_never_retried() -> None:
    provider = PermanentFailureProvider(
        error=ValueError("malformed-output-secret-must-not-leak")
    )
    retrying = RetryingLLMProvider(provider, policy=RetryPolicy())

    with pytest.raises(ProviderFailureError) as raised:
        await retrying.ainvoke([HumanMessage(content="malformed")])

    assert raised.value.code == "provider_request_failed"
    assert raised.value.retryable is False
    assert "malformed-output-secret-must-not-leak" not in str(raised.value)
    assert provider.calls == 1


@pytest.mark.asyncio
async def test_pre_token_stream_failure_recovers_without_duplicate_tokens() -> None:
    clock = FakeClock()
    provider = ScriptedStreamProvider(
        attempts=[[TimeoutError()], ["ordered-", "tokens"]]
    )
    retrying = RetryingLLMProvider(
        provider,
        policy=RetryPolicy(),
        monotonic=clock.monotonic,
        sleep=clock.sleep,
        random=lambda: 0.0,
    )

    tokens = [
        str(chunk.content)
        async for chunk in retrying.astream([HumanMessage(content="stream")])
    ]

    assert tokens == ["ordered-", "tokens"]
    assert provider.calls == 2
    assert clock.delays == [0.25]


@pytest.mark.asyncio
async def test_post_token_stream_failure_never_retries() -> None:
    provider = ScriptedStreamProvider(attempts=[["partial", TimeoutError()]])
    retrying = RetryingLLMProvider(provider, policy=RetryPolicy())
    tokens: list[str] = []

    with pytest.raises(ProviderFailureError) as raised:
        async for chunk in retrying.astream([HumanMessage(content="stream")]):
            tokens.append(str(chunk.content))

    assert tokens == ["partial"]
    assert raised.value.code == "provider_temporary_unavailable"
    assert provider.calls == 1


@pytest.mark.asyncio
async def test_cancellation_is_propagated_after_one_call() -> None:
    cancellation = anyio.get_cancelled_exc_class()
    calls = 0

    class CancelledProvider(PinProvider):
        async def ainvoke(self, messages: Sequence[BaseMessage]) -> BaseMessage:
            nonlocal calls
            del messages
            calls += 1
            raise cancellation

    retrying = RetryingLLMProvider(CancelledProvider(), policy=RetryPolicy())

    with pytest.raises(cancellation):
        await retrying.ainvoke([HumanMessage(content="cancel")])

    assert calls == 1


def test_malformed_retry_configuration_is_rejected() -> None:
    with pytest.raises(RetryConfigurationError) as raised:
        RetryPolicy(total_attempts=4)

    assert raised.value.field == "total_attempts"


def test_retry_delay_never_exceeds_one_second_after_jitter() -> None:
    policy = RetryPolicy()

    delay = policy.delay(retry_number=4, random_value=1.0)

    assert delay == 1.0


@pytest.mark.asyncio
async def test_ten_concurrent_deadlines_release_all_slots() -> None:
    limiter = anyio.CapacityLimiter(10)
    outcomes: list[str] = []

    async def run_session() -> None:
        clock = FakeClock()
        provider = TimedFailureProvider(clock=clock, elapsed=15.0)
        retrying = RetryingLLMProvider(
            provider,
            policy=RetryPolicy(),
            monotonic=clock.monotonic,
            sleep=clock.sleep,
        )
        async with limiter:
            with pytest.raises(ProviderFailureError) as raised:
                await retrying.ainvoke([HumanMessage(content="load")])
            outcomes.append(raised.value.code)

    async with anyio.create_task_group() as task_group:
        for _ in range(10):
            task_group.start_soon(run_session)

    assert outcomes == ["provider_temporary_unavailable"] * 10
    assert limiter.borrowed_tokens == 0
