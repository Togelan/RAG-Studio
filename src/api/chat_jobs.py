"""Bounded process-local ownership for background chat generation jobs."""

from __future__ import annotations

import asyncio  # noqa: ANYIO_OK - existing job manager is asyncio-native
import logging
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass, field

from src.api.chat_stream import StreamCapacityError, StreamSessionConflictError

PublishEvent = Callable[[str], Awaitable[None]]
JobProducer = Callable[[PublishEvent], Awaitable[None]]

logger = logging.getLogger(__name__)
_BUFFER_ERROR_EVENT = (
    'event: error\ndata: {"code":"replay_buffer_exhausted",'
    '"message":"Response exceeded the replay limit.","retryable":true}\n\n'
)
_BUFFER_DONE_EVENT = 'event: done\ndata: {"done":true,"completed":false}\n\n'
_PRODUCER_ERROR_EVENT = (
    'event: error\ndata: {"code":"response_failed",'
    '"message":"Response could not be completed.","retryable":true}\n\n'
)
_TERMINAL_RESERVE_BYTES = 256


class ChatJobNotFoundError(LookupError):
    """Raised when a session has no live generation job to attach to."""


class ChatJobBufferFullError(RuntimeError):
    """Raised when replay data exceeds the job's configured memory bound."""


class ChatJobConfigurationError(ValueError):
    """Raised when bounded job limits cannot support safe execution."""


@dataclass(slots=True)  # noqa: MUTABLE_OK - owns live task and replay state
class _ChatJob:
    """Mutable state machine for one producer-owned replay stream."""

    session_id: str
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
                raise ChatJobBufferFullError(self.session_id)
            self.events.append(event)
            self.buffered_bytes += encoded_size
            self.changed.notify_all()

    async def publish_buffer_error(self) -> None:
        """Publish a bounded, sanitized terminal outcome after overflow."""
        await self._publish_terminal(_BUFFER_ERROR_EVENT)

    async def publish_producer_error(self) -> None:
        """Publish a stable terminal outcome without provider exception text."""
        await self._publish_terminal(_PRODUCER_ERROR_EVENT)

    async def _publish_terminal(self, error_event: str) -> None:
        async with self.changed:
            for event in (error_event, _BUFFER_DONE_EVENT):
                encoded_size = len(event.encode("utf-8"))
                if self.buffered_bytes + encoded_size > self.buffer_max_bytes:
                    break
                self.events.append(event)
                self.buffered_bytes += encoded_size
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


class ChatJobManager:
    """Own active generation tasks independently of SSE subscribers."""

    def __init__(self, capacity: int) -> None:
        if capacity <= 0:
            raise ChatJobConfigurationError("Chat job capacity must be positive")
        self._capacity = capacity
        self._jobs: dict[str, _ChatJob] = {}
        self._lock = asyncio.Lock()

    async def start(
        self,
        session_id: str,
        producer: JobProducer,
        *,
        buffer_max_bytes: int,
    ) -> AsyncGenerator[str]:
        """Admit one producer and return its initial replaying subscription."""
        if buffer_max_bytes < _TERMINAL_RESERVE_BYTES:
            raise ChatJobConfigurationError(
                "Chat job replay buffer must reserve terminal capacity"
            )
        async with self._lock:
            if session_id in self._jobs:
                raise StreamSessionConflictError(session_id)
            if len(self._jobs) >= self._capacity:
                raise StreamCapacityError(str(self._capacity))
            job = _ChatJob(session_id, buffer_max_bytes)
            self._jobs[session_id] = job
            job.task = asyncio.create_task(self._run(job, producer))
        return job.replay()

    async def subscribe(self, session_id: str) -> AsyncGenerator[str]:
        """Return a replaying subscription for a live job."""
        async with self._lock:
            job = self._jobs.get(session_id)
        if job is None:
            raise ChatJobNotFoundError(session_id)
        return job.replay()

    async def cancel_and_wait(self, session_id: str) -> bool:
        """Cancel one live producer and wait for its cleanup to finish."""
        async with self._lock:
            job = self._jobs.get(session_id)
        if job is None or job.task is None:
            return False
        job.task.cancel()
        with suppress(asyncio.CancelledError):
            await job.task
        await job.finish()
        async with self._lock:
            if self._jobs.get(session_id) is job:
                self._jobs.pop(session_id)
        return True

    async def shutdown(self) -> None:
        """Cancel and await every producer before application resources close."""
        async with self._lock:
            session_ids = list(self._jobs)
        if session_ids:
            await asyncio.gather(
                *(self.cancel_and_wait(session_id) for session_id in session_ids)
            )

    async def active_count(self) -> int:
        """Return the number of producer-owned admission slots."""
        async with self._lock:
            return len(self._jobs)

    async def _run(self, job: _ChatJob, producer: JobProducer) -> None:
        try:
            await producer(job.publish)
        except ChatJobBufferFullError:
            logger.warning(
                "Chat job replay buffer exhausted: session=%s", job.session_id
            )
            await job.publish_buffer_error()
        except Exception as error:  # noqa: BLE001  # noqa: BROAD_EXCEPT_OK
            logger.error(
                "Chat job producer failed: session=%s type=%s",
                job.session_id,
                type(error).__name__,
            )
            await job.publish_producer_error()
        finally:
            await job.finish()
            async with self._lock:
                if self._jobs.get(job.session_id) is job:
                    self._jobs.pop(job.session_id)
