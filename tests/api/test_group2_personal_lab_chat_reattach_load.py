from __future__ import annotations

from collections.abc import AsyncGenerator, Awaitable, Callable
from time import monotonic
from uuid import UUID, uuid4

import anyio
import pytest

from src.api.personal_chat_jobs import (
    PersonalChatJobNotFoundError,
    PersonalChatJobRegistry,
)


async def _drain(events: AsyncGenerator[str]) -> tuple[str, ...]:
    return tuple([event async for event in events])


@pytest.mark.anyio
async def test_ten_scoped_jobs_reattach_or_cancel_within_bounds_without_leakage() -> (
    None
):
    scopes = tuple(uuid4() for _ in range(10))
    sessions = tuple(str(uuid4()) for _ in range(10))
    releases = tuple(anyio.Event() for _ in range(10))
    jobs = PersonalChatJobRegistry(capacity=10)
    initial: list[AsyncGenerator[str]] = []

    def producer(
        index: int,
    ) -> Callable[[Callable[[str], Awaitable[None]]], Awaitable[None]]:
        async def produce(publish: Callable[[str], Awaitable[None]]) -> None:
            await publish(f'event: start\ndata: {{"slot":{index}}}\n\n')
            await releases[index].wait()
            await publish(f'event: done\ndata: {{"slot":{index},"done":true}}\n\n')

        return produce

    for index, (scope_id, session_id) in enumerate(zip(scopes, sessions, strict=True)):
        initial.append(
            await jobs.start(
                scope_id,
                session_id,
                producer(index),
                buffer_max_bytes=4096,
            )
        )

    for stream in initial:
        assert "event: start" in await anext(stream)
        await stream.aclose()

    for index in range(5):
        started = monotonic()
        assert await jobs.cancel_and_wait(scopes[index], sessions[index]) is True
        assert monotonic() - started <= 2.0

    subscriptions = {
        index: await jobs.subscribe(scopes[index], sessions[index])
        for index in range(5, 10)
    }
    with pytest.raises(PersonalChatJobNotFoundError):
        await jobs.subscribe(UUID(int=0), sessions[9])

    async def receive(index: int) -> tuple[str, ...]:
        with anyio.fail_after(10):
            return await _drain(subscriptions[index])

    results: dict[int, tuple[str, ...]] = {}

    async def collect(index: int) -> None:
        results[index] = await receive(index)

    async with anyio.create_task_group() as task_group:
        for index in range(5, 10):
            task_group.start_soon(collect, index)
        for release in releases[5:]:
            release.set()

    for index, events in results.items():
        combined = "".join(events)
        assert f'"slot":{index}' in combined
        assert all(
            f'"slot":{other}' not in combined for other in range(10) if other != index
        )

    await jobs.shutdown()
