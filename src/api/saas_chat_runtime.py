"""Composite-key runtime ownership for tenant chat jobs and checkpoints."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import assert_never
from uuid import UUID

from src.api.chat_jobs import ChatJobManager, JobProducer, PublishEvent
from src.api.saas_chat_models import ChatbotAvailability, ChatbotUnavailableError
from src.api.saas_chat_persistence import TenantChatStore
from src.api.saas_chat_scope import (
    CheckpointConfiguration,
    ExecutionKey,
    SaasChatScope,
    checkpoint_configuration,
    derive_execution_key,
)


class TenantChatRuntime:
    """Own tenant chat persistence and bounded jobs under composite keys."""

    def __init__(
        self,
        store: TenantChatStore,
        execution_signing_key: bytes,
        capacity: int,
    ) -> None:
        self.store = store
        self._execution_signing_key = execution_signing_key
        self._jobs = ChatJobManager(capacity)
        self._active_scopes: dict[ExecutionKey, SaasChatScope] = {}

    async def initialize(self) -> None:
        """Initialize durable tenant chat persistence."""
        await self.store.initialize()

    def checkpoint_config(self, scope: SaasChatScope) -> CheckpointConfiguration:
        """Return the opaque composite selector for LangGraph persistence."""
        return checkpoint_configuration(scope, self._execution_signing_key)

    async def start(
        self,
        scope: SaasChatScope,
        producer: JobProducer,
        *,
        availability: ChatbotAvailability,
        buffer_max_bytes: int,
    ) -> AsyncGenerator[str]:
        """Start one bounded producer owned by the exact composite scope."""
        match availability:
            case ChatbotAvailability.ENABLED:
                pass
            case ChatbotAvailability.DISABLED | ChatbotAvailability.ARCHIVED:
                raise ChatbotUnavailableError
            case unreachable:
                assert_never(unreachable)
        key = self._key(scope)

        async def scoped_producer(publish: PublishEvent) -> None:
            try:
                await producer(publish)
            finally:
                self._active_scopes.pop(key, None)

        self._active_scopes[key] = scope
        try:
            return await self._jobs.start(
                key,
                scoped_producer,
                buffer_max_bytes=buffer_max_bytes,
            )
        except RuntimeError, ValueError:
            self._active_scopes.pop(key, None)
            raise

    async def reattach(self, scope: SaasChatScope) -> AsyncGenerator[str]:
        """Replay only the live job matching the exact composite scope."""
        return await self._jobs.subscribe(self._key(scope))

    async def cancel(self, scope: SaasChatScope) -> bool:
        """Cancel one exact composite job and release its admission slot."""
        key = self._key(scope)
        cancelled = await self._jobs.cancel_and_wait(key)
        self._active_scopes.pop(key, None)
        return cancelled

    async def cancel_workspace(self, workspace_id: UUID) -> int:
        """Cancel all in-flight work after workspace archive or revocation."""
        keys = tuple(
            key
            for key, scope in self._active_scopes.items()
            if scope.workspace_id == workspace_id
        )
        cancelled = 0
        for key in keys:
            if await self._jobs.cancel_and_wait(key):
                cancelled += 1
            self._active_scopes.pop(key, None)
        return cancelled

    async def active_count(self) -> int:
        """Return the bounded active producer count."""
        return await self._jobs.active_count()

    async def shutdown(self) -> None:
        """Cancel all producers before application resources close."""
        await self._jobs.shutdown()
        self._active_scopes.clear()

    def _key(self, scope: SaasChatScope) -> ExecutionKey:
        return derive_execution_key(scope, self._execution_signing_key)
