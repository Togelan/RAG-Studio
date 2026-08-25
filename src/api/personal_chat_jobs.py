"""Bounded process-local live jobs keyed by Personal Lab scope and session."""

from __future__ import annotations

import asyncio  # noqa: ANYIO_OK
import logging
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Final, Protocol
from uuid import UUID

type PublishPersonalEvent = Callable[[str], Awaitable[None]]
type PersonalJobProducer = Callable[[PublishPersonalEvent], Awaitable[None]]
type PersonalJobKey = tuple[UUID, str]

_TERMINAL_RESERVE_BYTES: Final = 256
_ERROR_EVENT: Final = (
    'event: error\ndata: {"code":"response_failed",'
    '"message":"Response could not be completed.","retryable":true}\n\n'
)
_DONE_EVENT: Final = 'event: done\ndata: {"done":true,"completed":false}\n\n'
logger = logging.getLogger(__name__)


class PersonalChatJobAuthority(Protocol):
    """Contract required from a process-local Personal Chat job registry."""

    async def start(
        self,
        scope_id: UUID,
        session_id: str,
        producer: PersonalJobProducer,
        *,
        buffer_max_bytes: int,
    ) -> AsyncGenerator[str]: ...

    async def subscribe(
        self, scope_id: UUID, session_id: str
    ) -> AsyncGenerator[str]: ...

    async def cancel_and_wait(self, scope_id: UUID, session_id: str) -> bool: ...

    async def shutdown(self) -> None: ...


class PersonalChatJobNotFoundError(LookupError):
    """Raised when no current-process job belongs to the requested scope."""


class PersonalChatJobConflictError(RuntimeError):
    """Raised when the same scoped session already has a live job."""


class PersonalChatJobCapacityError(RuntimeError):
    """Raised when the bounded process-wide job capacity is exhausted."""


class PersonalChatJobBufferError(RuntimeError):
    """Raised when bounded replay storage cannot accept another event."""


class PersonalChatJobConfigurationError(ValueError):
    """Raised for unsafe process-local job limits."""


@dataclass(slots=True)  # noqa: MUTABLE_OK
class _PersonalChatJob:
    key: PersonalJobKey
    buffer_max_bytes: int
    events: list[str] = field(default_factory=list)
    buffered_bytes: int = 0
    terminal: bool = False
    changed: asyncio.Condition = field(default_factory=asyncio.Condition)
    task: asyncio.Task[None] | None = None

    async def publish(self, event: str) -> None:
        encoded_size = len(event.encode("utf-8"))
        async with self.changed:
            if (
                self.buffered_bytes + encoded_size + _TERMINAL_RESERVE_BYTES
                > self.buffer_max_bytes
            ):
                raise PersonalChatJobBufferError
            self.events.append(event)
            self.buffered_bytes += encoded_size
            self.changed.notify_all()

    async def publish_failure(self) -> None:
        """Publish a bounded sanitized failure and terminal event."""
        async with self.changed:
            for event in (_ERROR_EVENT, _DONE_EVENT):
                size = len(event.encode("utf-8"))
                if self.buffered_bytes + size > self.buffer_max_bytes:
                    break
                self.events.append(event)
                self.buffered_bytes += size
            self.changed.notify_all()

    async def finish(self) -> None:
        async with self.changed:
            self.terminal = True
            self.changed.notify_all()

    async def replay(self) -> AsyncGenerator[str]:
        index = 0
        while True:
            async with self.changed:
                while index >= len(self.events) and not self.terminal:
                    await self.changed.wait()
                if index == len(self.events) and self.terminal:
                    return
                event = self.events[index]
                index += 1
            yield event


class PersonalChatJobRegistry:
    """Own bounded live jobs without persisting them across process restart."""

    def __init__(self, capacity: int = 10) -> None:
        if capacity <= 0:
            raise PersonalChatJobConfigurationError
        self._capacity = capacity
        self._jobs: dict[PersonalJobKey, _PersonalChatJob] = {}
        self._lock = asyncio.Lock()

    async def start(
        self,
        scope_id: UUID,
        session_id: str,
        producer: PersonalJobProducer,
        *,
        buffer_max_bytes: int,
    ) -> AsyncGenerator[str]:
        """Admit one scoped producer and return its replay subscription."""
        if buffer_max_bytes < _TERMINAL_RESERVE_BYTES:
            raise PersonalChatJobConfigurationError
        key = (scope_id, session_id)
        async with self._lock:
            if key in self._jobs:
                raise PersonalChatJobConflictError
            if len(self._jobs) >= self._capacity:
                raise PersonalChatJobCapacityError
            job = _PersonalChatJob(key, buffer_max_bytes)
            self._jobs[key] = job
            job.task = asyncio.create_task(self._run(job, producer))
        return job.replay()

    async def subscribe(self, scope_id: UUID, session_id: str) -> AsyncGenerator[str]:
        """Attach only to a job in the same current scope."""
        async with self._lock:
            job = self._jobs.get((scope_id, session_id))
        if job is None:
            raise PersonalChatJobNotFoundError
        return job.replay()

    async def cancel_and_wait(self, scope_id: UUID, session_id: str) -> bool:
        """Idempotently cancel one same-scope job and await cleanup."""
        key = (scope_id, session_id)
        async with self._lock:
            job = self._jobs.get(key)
        if job is None or job.task is None:
            return False
        job.task.cancel()
        with suppress(asyncio.CancelledError):
            await job.task
        await self._remove(job)
        return True

    async def shutdown(self) -> None:
        """Cancel all current-process jobs before dependency shutdown."""
        async with self._lock:
            keys = tuple(self._jobs)
        for scope_id, session_id in keys:
            await self.cancel_and_wait(scope_id, session_id)

    async def _run(self, job: _PersonalChatJob, producer: PersonalJobProducer) -> None:
        try:
            await producer(job.publish)
        except asyncio.CancelledError:
            raise
        except PersonalChatJobBufferError:
            logger.warning("Personal Chat replay buffer exhausted")
            await job.publish_failure()
        except Exception as error:  # noqa: BLE001  # noqa: BROAD_EXCEPT_OK
            logger.error("Personal Chat producer failed: type=%s", type(error).__name__)
            await job.publish_failure()
        finally:
            await job.finish()
            await self._remove(job)

    async def _remove(self, job: _PersonalChatJob) -> None:
        async with self._lock:
            if self._jobs.get(job.key) is job:
                self._jobs.pop(job.key)
