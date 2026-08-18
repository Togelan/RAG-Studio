from __future__ import annotations

import json
import os
from uuid import uuid4

import asyncpg
import pytest

from src.api.saas_chat_models import (
    ChatbotUnavailableError,
    ExecutionChannel,
    SupportedLocale,
)
from src.api.saas_chatbot_models import (
    ChatbotActor,
    ChatbotCreation,
    ChatbotErrorCode,
    ChatbotOperationError,
    ChatbotStatus,
    ChatbotUpdate,
    ChatbotVersionMutation,
)
from src.api.saas_chatbot_store import PostgresChatbotService
from tests.api.test_stage3_chatbots import _definition

_DATABASE_URL = os.getenv("TASK9_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    _DATABASE_URL is None,
    reason="requires a task-owned migrated Postgres database",
)


@pytest.mark.anyio
async def test_postgres_lifecycle_is_tenant_scoped_retry_safe_and_audited() -> None:
    # Given: owner, admin, and member roles in one active workspace.
    assert _DATABASE_URL is not None
    workspace_id, other_workspace_id = uuid4(), uuid4()
    owner_id, admin_id, member_id, other_owner_id = (
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
    )
    connection = await asyncpg.connect(_DATABASE_URL)
    try:
        async with connection.transaction():
            await connection.executemany(
                "INSERT INTO public.workspaces (id, name, created_by) VALUES ($1,$2,$3)",
                (
                    (workspace_id, "Workspace", owner_id),
                    (other_workspace_id, "Other", other_owner_id),
                ),
            )
            await connection.executemany(
                """
                INSERT INTO public.workspace_memberships
                    (workspace_id, user_id, role)
                VALUES ($1,$2,$3)
                """,
                (
                    (workspace_id, owner_id, "owner"),
                    (workspace_id, admin_id, "admin"),
                    (workspace_id, member_id, "member"),
                    (other_workspace_id, other_owner_id, "owner"),
                ),
            )
        registry_before = await connection.fetchrow(
            """
            SELECT collection_name, state::text AS state, attempt_count
              FROM public.workspace_collection_registry WHERE workspace_id=$1
            """,
            workspace_id,
        )
    finally:
        await connection.close()

    service = PostgresChatbotService(_DATABASE_URL)
    owner = ChatbotActor(workspace_id, owner_id)
    admin = ChatbotActor(workspace_id, admin_id)
    member = ChatbotActor(workspace_id, member_id)
    outsider = ChatbotActor(other_workspace_id, other_owner_id)
    definition = _definition()

    # When: managers create/update with retries and a member attempts mutation.
    created = await service.create_chatbot(
        ChatbotCreation(owner, definition, "task9-create-retry")
    )
    retried_create = await service.create_chatbot(
        ChatbotCreation(owner, definition, "task9-create-retry")
    )
    updated_definition = type(definition)(
        name_en="Support Updated",
        name_ru="Поддержка обновлена",
        instructions_en=definition.instructions_en,
        instructions_ru=definition.instructions_ru,
        provider=definition.provider,
        model_name=definition.model_name,
    )
    updated = await service.update_chatbot(
        ChatbotUpdate(admin, created.id, created.version, updated_definition)
    )
    retried_update = await service.update_chatbot(
        ChatbotUpdate(admin, created.id, created.version, updated_definition)
    )
    with pytest.raises(ChatbotOperationError) as stale:
        await service.update_chatbot(
            ChatbotUpdate(owner, created.id, created.version, definition)
        )
    with pytest.raises(ChatbotOperationError) as denied:
        await service.create_chatbot(
            ChatbotCreation(member, definition, "member-mutation-denied")
        )

    # Then: retries are stable, stale/member writes fail, and tenants stay isolated.
    assert retried_create == created
    assert retried_update == updated
    assert updated.version == 2
    assert stale.value.code is ChatbotErrorCode.CONFLICT
    assert denied.value.code is ChatbotErrorCode.DENIED
    assert [record.id for record in await service.list_chatbots(member)] == [created.id]
    assert await service.list_chatbots(outsider) == ()
    with pytest.raises(ChatbotOperationError) as foreign:
        await service.get_chatbot(outsider, created.id)
    assert foreign.value.code is ChatbotErrorCode.NOT_FOUND

    # When: both traffic channels resolve while enabled, then disable/archive retry.
    english = await service.resolve_execution(
        workspace_id, created.id, ExecutionChannel.TEST, SupportedLocale.EN
    )
    russian = await service.resolve_execution(
        workspace_id,
        created.id,
        ExecutionChannel.PUBLIC_WIDGET,
        SupportedLocale.RU,
    )
    disabled = await service.disable_chatbot(
        ChatbotVersionMutation(admin, created.id, updated.version)
    )
    disabled_retry = await service.disable_chatbot(
        ChatbotVersionMutation(admin, created.id, updated.version)
    )
    for channel in (ExecutionChannel.TEST, ExecutionChannel.PUBLIC_WIDGET):
        with pytest.raises(ChatbotUnavailableError):
            await service.resolve_execution(
                workspace_id, created.id, channel, SupportedLocale.EN
            )
    await service.archive_chatbot(
        ChatbotVersionMutation(owner, created.id, disabled.version)
    )
    for channel in (ExecutionChannel.TEST, ExecutionChannel.PUBLIC_WIDGET):
        with pytest.raises(ChatbotUnavailableError):
            await service.resolve_execution(
                workspace_id, created.id, channel, SupportedLocale.RU
            )
    await service.archive_chatbot(
        ChatbotVersionMutation(owner, created.id, disabled.version)
    )

    # Then: channel/locale remain explicit and lifecycle never touches knowledge.
    assert english.channel is ExecutionChannel.TEST
    assert english.configuration.instructions == updated_definition.instructions_en
    assert russian.channel is ExecutionChannel.PUBLIC_WIDGET
    assert russian.configuration.instructions == updated_definition.instructions_ru
    assert disabled.status is ChatbotStatus.DISABLED
    assert disabled_retry == disabled
    assert await service.list_chatbots(owner) == ()

    connection = await asyncpg.connect(_DATABASE_URL)
    try:
        events = await connection.fetch(
            """
            SELECT event_type, details
              FROM public.workspace_audit_events
             WHERE workspace_id=$1 AND event_type LIKE 'chatbot.%'
             ORDER BY id
            """,
            workspace_id,
        )
        registry_after = await connection.fetchrow(
            """
            SELECT collection_name, state::text AS state, attempt_count
              FROM public.workspace_collection_registry WHERE workspace_id=$1
            """,
            workspace_id,
        )
    finally:
        await connection.close()
    assert [row["event_type"] for row in events] == [
        "chatbot.created",
        "chatbot.updated",
        "chatbot.disabled",
        "chatbot.archived",
    ]
    assert all(json.loads(str(row["details"])) == {} for row in events)
    assert registry_after == registry_before
