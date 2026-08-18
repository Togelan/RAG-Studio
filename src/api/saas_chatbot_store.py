"""Postgres-backed FR-015 chatbot lifecycle service."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Final
from uuid import UUID, uuid5

from src.api.saas_chat_models import (
    ChatbotCatalogUnavailableError,
    ChatbotExecutionConfiguration,
    ChatbotUnavailableError,
    ExecutionChannel,
    SupportedLocale,
)
from src.api.saas_chatbot_database import (
    audit_chatbot_event,
    chatbot_record,
    chatbot_transaction,
    definition_matches,
    definition_values,
    execution_configuration,
    fetch_chatbot_record,
    require_chatbot_role,
)
from src.api.saas_chatbot_models import (
    ChatbotActor,
    ChatbotCreation,
    ChatbotErrorCode,
    ChatbotOperationError,
    ChatbotRecord,
    ChatbotStatus,
    ChatbotUpdate,
    ChatbotVersionMutation,
)
from src.api.saas_sessions import WorkspaceRole

_CHATBOT_ID_NAMESPACE: Final = UUID("950f71cf-2ba9-4eef-b9c9-20306a7acb47")
_ALL_ROLES: Final = (
    WorkspaceRole.OWNER,
    WorkspaceRole.ADMIN,
    WorkspaceRole.MEMBER,
)
_MANAGERS: Final = (WorkspaceRole.OWNER, WorkspaceRole.ADMIN)


@dataclass(frozen=True, slots=True)
class PostgresChatbotService:
    """Persist lifecycle state and resolve execution availability server-side."""

    database_url: str

    async def list_chatbots(self, actor: ChatbotActor) -> tuple[ChatbotRecord, ...]:
        """List non-archived chatbots within one active membership."""
        async with chatbot_transaction(self.database_url) as connection:
            await require_chatbot_role(connection, actor, _ALL_ROLES)
            rows = await connection.fetch(
                """
                SELECT id, workspace_id, name_en, name_ru,
                       instructions_en, instructions_ru,
                       provider, model_name, status::text AS status, version
                  FROM public.workspace_chatbots
                 WHERE workspace_id = $1 AND status <> 'archived'
                 ORDER BY created_at, id
                """,
                actor.workspace_id,
            )
        return tuple(chatbot_record(row) for row in rows)

    async def get_chatbot(self, actor: ChatbotActor, chatbot_id: UUID) -> ChatbotRecord:
        """Return one non-archived chatbot without cross-workspace fallback."""
        async with chatbot_transaction(self.database_url) as connection:
            await require_chatbot_role(connection, actor, _ALL_ROLES)
            record = await fetch_chatbot_record(
                connection, actor.workspace_id, chatbot_id, include_archived=False
            )
        return record

    async def create_chatbot(self, command: ChatbotCreation) -> ChatbotRecord:
        """Create one deterministic idempotent chatbot and one audit event."""
        key_hash = hashlib.sha256(command.idempotency_key.encode()).hexdigest()
        chatbot_id = uuid5(
            _CHATBOT_ID_NAMESPACE, f"{command.actor.workspace_id}:{key_hash}"
        )
        async with chatbot_transaction(self.database_url) as connection:
            await require_chatbot_role(connection, command.actor, _MANAGERS)
            await connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended($1, 0))",
                str(chatbot_id),
            )
            existing = await connection.fetchrow(
                """
                SELECT id, workspace_id, name_en, name_ru,
                       instructions_en, instructions_ru,
                       provider, model_name, status::text AS status, version,
                       created_by
                  FROM public.workspace_chatbots
                 WHERE workspace_id = $1 AND id = $2
                """,
                command.actor.workspace_id,
                chatbot_id,
            )
            if existing is not None:
                record = chatbot_record(existing)
                if existing[
                    "created_by"
                ] == command.actor.user_id and definition_matches(
                    record, command.definition
                ):
                    return record
                raise ChatbotOperationError(ChatbotErrorCode.CONFLICT)
            await connection.execute(
                """
                INSERT INTO public.workspace_chatbots (
                    id, workspace_id, idempotency_key_hash,
                    name_en, name_ru, instructions_en, instructions_ru,
                    provider, model_name, created_by, updated_by
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $10)
                """,
                chatbot_id,
                command.actor.workspace_id,
                key_hash,
                *definition_values(command.definition),
                command.actor.user_id,
            )
            await audit_chatbot_event(
                connection, command.actor, "chatbot.created", chatbot_id
            )
            return await fetch_chatbot_record(
                connection, command.actor.workspace_id, chatbot_id
            )

    async def update_chatbot(self, command: ChatbotUpdate) -> ChatbotRecord:
        """Apply one full optimistic update or return its exact retry result."""
        async with chatbot_transaction(self.database_url) as connection:
            await require_chatbot_role(connection, command.actor, _MANAGERS)
            current = await fetch_chatbot_record(
                connection,
                command.actor.workspace_id,
                command.chatbot_id,
                for_update=True,
            )
            if current.status is ChatbotStatus.ARCHIVED:
                raise ChatbotOperationError(ChatbotErrorCode.NOT_FOUND)
            if current.version == command.expected_version:
                if definition_matches(current, command.definition):
                    return current
                await connection.execute(
                    """
                    UPDATE public.workspace_chatbots
                       SET name_en=$3, name_ru=$4, instructions_en=$5,
                           instructions_ru=$6, provider=$7, model_name=$8,
                           version=version+1, updated_by=$9
                     WHERE workspace_id=$1 AND id=$2
                    """,
                    command.actor.workspace_id,
                    command.chatbot_id,
                    *definition_values(command.definition),
                    command.actor.user_id,
                )
                await audit_chatbot_event(
                    connection, command.actor, "chatbot.updated", command.chatbot_id
                )
                return await fetch_chatbot_record(
                    connection, command.actor.workspace_id, command.chatbot_id
                )
            if current.version == command.expected_version + 1 and definition_matches(
                current, command.definition
            ):
                return current
            raise ChatbotOperationError(ChatbotErrorCode.CONFLICT)

    async def disable_chatbot(self, command: ChatbotVersionMutation) -> ChatbotRecord:
        """Disable new executions without deleting sessions or knowledge."""
        return await self._change_status(command, ChatbotStatus.DISABLED)

    async def archive_chatbot(self, command: ChatbotVersionMutation) -> None:
        """Archive configuration without deleting documents or its collection."""
        await self._change_status(command, ChatbotStatus.ARCHIVED)

    async def resolve_execution(
        self,
        workspace_id: UUID,
        chatbot_id: UUID,
        channel: ExecutionChannel,
        locale: SupportedLocale,
    ) -> ChatbotExecutionConfiguration:
        """Resolve enabled configuration for a trusted test or widget context."""
        try:
            async with chatbot_transaction(self.database_url) as connection:
                record = await fetch_chatbot_record(
                    connection, workspace_id, chatbot_id
                )
        except ChatbotOperationError as error:
            if error.code is ChatbotErrorCode.UNAVAILABLE:
                raise ChatbotCatalogUnavailableError from None
            raise ChatbotUnavailableError from None
        if record.status is not ChatbotStatus.ENABLED:
            raise ChatbotUnavailableError
        return execution_configuration(record, channel, locale)

    async def _change_status(
        self, command: ChatbotVersionMutation, target: ChatbotStatus
    ) -> ChatbotRecord:
        async with chatbot_transaction(self.database_url) as connection:
            await require_chatbot_role(connection, command.actor, _MANAGERS)
            current = await fetch_chatbot_record(
                connection,
                command.actor.workspace_id,
                command.chatbot_id,
                for_update=True,
            )
            if current.status is target and command.expected_version in {
                current.version,
                current.version - 1,
            }:
                return current
            if (
                current.status is ChatbotStatus.ARCHIVED
                or current.version != command.expected_version
            ):
                raise ChatbotOperationError(ChatbotErrorCode.CONFLICT)
            await connection.execute(
                """
                UPDATE public.workspace_chatbots
                   SET status=$3::public.chatbot_status,
                       version=version+1, updated_by=$4::uuid,
                       archived_at=CASE
                           WHEN $3::public.chatbot_status='archived'::public.chatbot_status
                           THEN now() ELSE NULL
                       END,
                       archived_by=CASE
                           WHEN $3::public.chatbot_status='archived'::public.chatbot_status
                           THEN $4::uuid ELSE NULL
                       END
                 WHERE workspace_id=$1 AND id=$2
                """,
                command.actor.workspace_id,
                command.chatbot_id,
                target.value,
                command.actor.user_id,
            )
            await audit_chatbot_event(
                connection,
                command.actor,
                f"chatbot.{target.value}",
                command.chatbot_id,
            )
            return await fetch_chatbot_record(
                connection, command.actor.workspace_id, command.chatbot_id
            )
