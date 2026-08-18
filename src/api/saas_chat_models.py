"""Typed non-secret records for tenant-scoped SaaS chat."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from src.api.saas_chat_scope import ChatbotConfigurationFingerprint


class ChatSessionNotFoundError(LookupError):
    """The exact tenant chat scope has no session."""


class ChatPersistenceUnavailableError(RuntimeError):
    """Tenant chat persistence failed without exposing storage details."""


class ChatbotUnavailableError(PermissionError):
    """New execution is blocked by the authoritative chatbot lifecycle state."""


class ChatbotCatalogUnavailableError(RuntimeError):
    """Chatbot authority could not be resolved without exposing storage detail."""


class ChatbotAvailability(StrEnum):
    """Availability states consumed by tenant chat execution."""

    ENABLED = "enabled"
    DISABLED = "disabled"
    ARCHIVED = "archived"


class ExecutionChannel(StrEnum):
    """Server-selected chatbot traffic classes used by availability and metering."""

    TEST = "test"
    PUBLIC_WIDGET = "public_widget"


class SupportedLocale(StrEnum):
    """Locales supported by Stage 3 chatbot configuration."""

    EN = "en"
    RU = "ru"


class ChatbotConfiguration(BaseModel):
    """Per-chatbot settings that deliberately contain no credential field."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: str = Field(min_length=1, max_length=40)
    model_name: str = Field(min_length=1, max_length=120)
    instructions: str = Field(default="", max_length=8_000)
    workspace_all: bool = True

    @property
    def fingerprint(self) -> ChatbotConfigurationFingerprint:
        """Return a stable opaque cache namespace for this validated config."""
        digest = hashlib.sha256(self.model_dump_json().encode()).hexdigest()
        return ChatbotConfigurationFingerprint(f"cfg_{digest}")


@dataclass(frozen=True, slots=True)
class ChatbotExecutionConfiguration:
    """Resolved non-secret configuration paired with its server-selected channel."""

    configuration: ChatbotConfiguration
    channel: ExecutionChannel


class ChatFeedback(BaseModel):
    """Validated feedback associated with one scoped assistant message."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    message_id: UUID
    feedback: Literal["positive", "negative"]
    reason: str | None = Field(default=None, max_length=500)


@dataclass(frozen=True, slots=True)
class ChatSessionRecord:
    """Persisted metadata for one exact composite conversation scope."""

    session_id: UUID
    title: str
    created_at: datetime
    updated_at: datetime
