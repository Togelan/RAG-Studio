from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
from uuid import uuid4

import anyio
import pytest

from src.api.chat_jobs import ChatJobNotFoundError
from src.api.saas_chat_models import ChatbotAvailability, ChatbotUnavailableError
from src.api.saas_chat_persistence import TenantChatStore
from src.api.saas_chat_runtime import TenantChatRuntime
from src.api.saas_chat_scope import SaasChatScope, derive_execution_key


@pytest.mark.anyio
async def test_execution_key_is_composite_opaque_and_restart_stable() -> None:
    # Given: the same session UUID appears under different tenant dimensions.
    session_id = uuid4()
    first = SaasChatScope(uuid4(), uuid4(), uuid4(), session_id)
    variants = (
        SaasChatScope(uuid4(), first.user_id, first.chatbot_id, session_id),
        SaasChatScope(first.workspace_id, uuid4(), first.chatbot_id, session_id),
        SaasChatScope(first.workspace_id, first.user_id, uuid4(), session_id),
    )

    # When: checkpoint/job execution keys are derived with a server key.
    first_key = derive_execution_key(first, b"server-side-test-key")
    keys = {derive_execution_key(scope, b"server-side-test-key") for scope in variants}

    # Then: every dimension changes the opaque key and the same input is stable.
    assert first_key == derive_execution_key(first, b"server-side-test-key")
    assert first_key not in keys
    assert len(keys) == len(variants)
    assert all(
        str(value) not in first_key
        for value in (
            first.workspace_id,
            first.user_id,
            first.chatbot_id,
            first.session_id,
        )
    )


@pytest.mark.anyio
async def test_job_reattach_cancel_and_capacity_are_scope_safe(tmp_path: Path) -> None:
    # Given: one active job and another scope reusing its session UUID.
    runtime = TenantChatRuntime(
        store=TenantChatStore(tmp_path / "tenant-chat.sqlite3"),
        execution_signing_key=b"server-side-test-key",
        capacity=1,
    )
    await runtime.initialize()
    started = anyio.Event()
    release = anyio.Event()
    first = SaasChatScope(uuid4(), uuid4(), uuid4(), uuid4())
    tampered = SaasChatScope(uuid4(), first.user_id, first.chatbot_id, first.session_id)

    async def producer(publish: Callable[[str], Awaitable[None]]) -> None:
        await publish('event: token\ndata: {"token":"redacted"}\n\n')
        started.set()
        await release.wait()

    async with anyio.create_task_group() as task_group:

        async def consume() -> None:
            stream = await runtime.start(
                first,
                producer,
                availability=ChatbotAvailability.ENABLED,
                buffer_max_bytes=4096,
            )
            async for _event in stream:
                pass

        task_group.start_soon(consume)
        await started.wait()

        # When/Then: a tampered scope cannot attach or cancel the owner job.
        with pytest.raises(ChatJobNotFoundError):
            await runtime.reattach(tampered)
        assert await runtime.cancel(tampered) is False
        assert await runtime.active_count() == 1

        # When: the exact owner scope cancels.
        assert await runtime.cancel(first) is True

        # Then: capacity is released deterministically.
        assert await runtime.active_count() == 0
        release.set()
        task_group.cancel_scope.cancel()


@pytest.mark.anyio
async def test_deactivated_chatbot_blocks_new_work_and_archive_cancels_active(
    tmp_path: Path,
) -> None:
    # Given: a runtime with one capacity slot and a scoped producer.
    runtime = TenantChatRuntime(
        store=TenantChatStore(tmp_path / "tenant-chat.sqlite3"),
        execution_signing_key=b"server-side-test-key",
        capacity=1,
    )
    await runtime.initialize()
    scope = SaasChatScope(uuid4(), uuid4(), uuid4(), uuid4())
    started = anyio.Event()

    async def producer(publish: Callable[[str], Awaitable[None]]) -> None:
        del publish
        started.set()
        await anyio.sleep_forever()

    # When/Then: deactivated state rejects before consuming capacity.
    with pytest.raises(ChatbotUnavailableError):
        await runtime.start(
            scope,
            producer,
            availability=ChatbotAvailability.DISABLED,
            buffer_max_bytes=4096,
        )
    assert await runtime.active_count() == 0

    async with anyio.create_task_group() as task_group:

        async def consume() -> None:
            stream = await runtime.start(
                scope,
                producer,
                availability=ChatbotAvailability.ENABLED,
                buffer_max_bytes=4096,
            )
            async for _event in stream:
                pass

        task_group.start_soon(consume)
        await started.wait()

        # When: workspace archive/revocation signals runtime cancellation.
        cancelled = await runtime.cancel_workspace(scope.workspace_id)

        # Then: its producer stops and the admission slot is released.
        assert cancelled == 1
        assert await runtime.active_count() == 0
        task_group.cancel_scope.cancel()


@pytest.mark.anyio
async def test_hostile_provider_error_replays_only_sanitized_terminal_events(
    tmp_path: Path,
) -> None:
    # Given: a provider boundary that raises text containing a credential marker.
    runtime = TenantChatRuntime(
        store=TenantChatStore(tmp_path / "tenant-chat.sqlite3"),
        execution_signing_key=b"server-side-test-key",
        capacity=1,
    )
    await runtime.initialize()
    scope = SaasChatScope(uuid4(), uuid4(), uuid4(), uuid4())

    async def failing_provider(publish: Callable[[str], Awaitable[None]]) -> None:
        del publish
        raise OSError("provider-secret-must-not-escape")

    # When: the scoped producer fails after admission.
    stream = await runtime.start(
        scope,
        failing_provider,
        availability=ChatbotAvailability.ENABLED,
        buffer_max_bytes=4096,
    )
    events = [event async for event in stream]

    # Then: replay exposes only stable terminal events and releases capacity.
    assert [event.splitlines()[0] for event in events] == [
        "event: error",
        "event: done",
    ]
    assert '"code":"response_failed"' in events[0]
    assert "provider-secret-must-not-escape" not in "".join(events)
    assert await runtime.active_count() == 0
