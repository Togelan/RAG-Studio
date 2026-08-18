"""Typed FR-015 chatbot lifecycle contracts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from src.api.saas_chat_models import (
    ChatbotExecutionConfiguration,
    ExecutionChannel,
    SupportedLocale,
)
from src.api.saas_workspace_models import WorkspaceActor

ChatbotActor = WorkspaceActor


class ChatbotStatus(StrEnum):
    """Persisted chatbot lifecycle states."""

    ENABLED = "enabled"
    DISABLED = "disabled"
    ARCHIVED = "archived"


class ChatbotErrorCode(StrEnum):
    """Sanitized chatbot operation failures."""

    DENIED = "denied"
    NOT_FOUND = "not_found"
    CONFLICT = "conflict"
    UNAVAILABLE = "unavailable"


class ChatbotOperationError(Exception):
    """Chatbot failure without tenant, database, or provider detail."""

    __slots__ = ("code",)

    def __init__(self, code: ChatbotErrorCode) -> None:
        super().__init__(f"chatbot operation {code.value}")
        self.code = code

    def __str__(self) -> str:
        return f"chatbot operation {self.code.value}"


@dataclass(frozen=True, slots=True)
class ChatbotDefinition:
    """Validated localized chatbot configuration over all workspace sources."""

    name_en: str
    name_ru: str
    instructions_en: str
    instructions_ru: str
    provider: str
    model_name: str


@dataclass(frozen=True, slots=True)
class ChatbotRecord:
    """One workspace-owned chatbot without credentials or collection identity."""

    id: UUID
    workspace_id: UUID
    definition: ChatbotDefinition
    status: ChatbotStatus
    version: int


@dataclass(frozen=True, slots=True)
class ChatbotCreation:
    """Idempotent manager-authorized chatbot creation command."""

    actor: ChatbotActor
    definition: ChatbotDefinition
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class ChatbotUpdate:
    """Optimistically versioned chatbot replacement command."""

    actor: ChatbotActor
    chatbot_id: UUID
    expected_version: int
    definition: ChatbotDefinition


@dataclass(frozen=True, slots=True)
class ChatbotVersionMutation:
    """Optimistically versioned disable or archive command."""

    actor: ChatbotActor
    chatbot_id: UUID
    expected_version: int


class ChatbotService(Protocol):
    """Workspace lifecycle and execution-availability boundary."""

    async def list_chatbots(self, actor: ChatbotActor) -> tuple[ChatbotRecord, ...]: ...

    async def get_chatbot(
        self, actor: ChatbotActor, chatbot_id: UUID
    ) -> ChatbotRecord: ...

    async def create_chatbot(self, command: ChatbotCreation) -> ChatbotRecord: ...

    async def update_chatbot(self, command: ChatbotUpdate) -> ChatbotRecord: ...

    async def disable_chatbot(
        self, command: ChatbotVersionMutation
    ) -> ChatbotRecord: ...

    async def archive_chatbot(self, command: ChatbotVersionMutation) -> None: ...

    async def resolve_execution(
        self,
        workspace_id: UUID,
        chatbot_id: UUID,
        channel: ExecutionChannel,
        locale: SupportedLocale,
    ) -> ChatbotExecutionConfiguration: ...
