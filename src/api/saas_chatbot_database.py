"""Postgres helpers shared by the FR-015 chatbot store."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Final, assert_never
from uuid import UUID

import asyncpg

from src.api.saas_chat_models import (
    ChatbotConfiguration,
    ChatbotExecutionConfiguration,
    ExecutionChannel,
    SupportedLocale,
)
from src.api.saas_chatbot_models import (
    ChatbotActor,
    ChatbotDefinition,
    ChatbotErrorCode,
    ChatbotOperationError,
    ChatbotRecord,
    ChatbotStatus,
)
from src.api.saas_sessions import WorkspaceRole
from src.api.saas_workspace_database import actor_has_role, workspace_transaction
from src.api.saas_workspace_models import WorkspaceErrorCode, WorkspaceOperationError

_SELECT_CHATBOT: Final = """
    SELECT id, workspace_id, name_en, name_ru, instructions_en, instructions_ru,
           provider, model_name, status::text AS status, version
      FROM public.workspace_chatbots
     WHERE workspace_id=$1 AND id=$2
"""
_SELECT_ACTIVE_CHATBOT: Final = """
    SELECT id, workspace_id, name_en, name_ru, instructions_en, instructions_ru,
           provider, model_name, status::text AS status, version
      FROM public.workspace_chatbots
     WHERE workspace_id=$1 AND id=$2 AND status <> 'archived'
"""
_SELECT_CHATBOT_FOR_UPDATE: Final = """
    SELECT id, workspace_id, name_en, name_ru, instructions_en, instructions_ru,
           provider, model_name, status::text AS status, version
      FROM public.workspace_chatbots
     WHERE workspace_id=$1 AND id=$2
    FOR UPDATE
"""


@asynccontextmanager
async def chatbot_transaction(database_url: str) -> AsyncIterator[asyncpg.Connection]:
    """Open one bounded transaction and translate infrastructure failures."""
    try:
        async with workspace_transaction(database_url) as connection:
            yield connection
    except WorkspaceOperationError as error:
        raise ChatbotOperationError(_chatbot_error_code(error.code)) from None


def chatbot_record(row: asyncpg.Record) -> ChatbotRecord:
    """Parse one trusted database row into the lifecycle value object."""
    return ChatbotRecord(
        id=UUID(str(row["id"])),
        workspace_id=UUID(str(row["workspace_id"])),
        definition=ChatbotDefinition(
            name_en=str(row["name_en"]),
            name_ru=str(row["name_ru"]),
            instructions_en=str(row["instructions_en"]),
            instructions_ru=str(row["instructions_ru"]),
            provider=str(row["provider"]),
            model_name=str(row["model_name"]),
        ),
        status=ChatbotStatus(str(row["status"])),
        version=int(str(row["version"])),
    )


def definition_values(definition: ChatbotDefinition) -> tuple[str, ...]:
    """Return the stable SQL parameter order for a validated definition."""
    return (
        definition.name_en,
        definition.name_ru,
        definition.instructions_en,
        definition.instructions_ru,
        definition.provider,
        definition.model_name,
    )


def definition_matches(record: ChatbotRecord, definition: ChatbotDefinition) -> bool:
    """Return whether a retry describes the already-persisted definition."""
    return record.definition == definition


def execution_configuration(
    record: ChatbotRecord,
    channel: ExecutionChannel,
    locale: SupportedLocale,
) -> ChatbotExecutionConfiguration:
    """Resolve localized non-secret execution settings."""
    match locale:
        case SupportedLocale.EN:
            instructions = record.definition.instructions_en
        case SupportedLocale.RU:
            instructions = record.definition.instructions_ru
        case unreachable:
            assert_never(unreachable)
    return ChatbotExecutionConfiguration(
        configuration=ChatbotConfiguration(
            provider=record.definition.provider,
            model_name=record.definition.model_name,
            instructions=instructions,
            workspace_all=True,
        ),
        channel=channel,
    )


async def require_chatbot_role(
    connection: asyncpg.Connection,
    actor: ChatbotActor,
    roles: tuple[WorkspaceRole, ...],
) -> None:
    """Revalidate chatbot authority in the same mutation transaction."""
    if not await actor_has_role(connection, actor, roles):
        raise ChatbotOperationError(ChatbotErrorCode.DENIED)


async def fetch_chatbot_record(
    connection: asyncpg.Connection,
    workspace_id: UUID,
    chatbot_id: UUID,
    *,
    include_archived: bool = True,
    for_update: bool = False,
) -> ChatbotRecord:
    """Fetch one exact tenant record with optional mutation locking."""
    if for_update:
        statement = _SELECT_CHATBOT_FOR_UPDATE
    elif include_archived:
        statement = _SELECT_CHATBOT
    else:
        statement = _SELECT_ACTIVE_CHATBOT
    row = await connection.fetchrow(
        statement,
        workspace_id,
        chatbot_id,
    )
    if row is None:
        raise ChatbotOperationError(ChatbotErrorCode.NOT_FOUND)
    return chatbot_record(row)


async def audit_chatbot_event(
    connection: asyncpg.Connection,
    actor: ChatbotActor,
    event_type: str,
    chatbot_id: UUID,
) -> None:
    """Append one redacted lifecycle audit record in the mutation transaction."""
    await connection.execute(
        """
        INSERT INTO public.workspace_audit_events
            (workspace_id, actor_user_id, event_type, subject_id)
        VALUES ($1, $2, $3, $4)
        """,
        actor.workspace_id,
        actor.user_id,
        event_type,
        chatbot_id,
    )


def _chatbot_error_code(code: WorkspaceErrorCode) -> ChatbotErrorCode:
    match code:
        case WorkspaceErrorCode.DENIED:
            return ChatbotErrorCode.DENIED
        case WorkspaceErrorCode.CONFLICT:
            return ChatbotErrorCode.CONFLICT
        case WorkspaceErrorCode.UNAVAILABLE:
            return ChatbotErrorCode.UNAVAILABLE
        case unreachable:
            assert_never(unreachable)
