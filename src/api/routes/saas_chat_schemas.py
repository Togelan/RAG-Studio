"""Validated request and response shapes for tenant chat sessions."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from src.api.saas_chat_models import SupportedLocale


class SessionCreateRequest(BaseModel):
    """Create one scoped session with an optional client-stable UUID."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    session_id: UUID = Field(default_factory=uuid4)
    title: str = Field(default="New Session", min_length=1, max_length=120)


class SessionRenameRequest(BaseModel):
    """Rename one scoped session."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    title: str = Field(min_length=1, max_length=120)


class SessionMessageRequest(BaseModel):
    """Submit one bounded user message to an existing scoped session."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    content: str = Field(min_length=1, max_length=10_000)
    locale: SupportedLocale = SupportedLocale.EN


class SessionResponse(BaseModel):
    """Non-secret session metadata returned to one authorized user."""

    model_config = ConfigDict(from_attributes=True, frozen=True)

    session_id: UUID
    title: str
    created_at: datetime
    updated_at: datetime


class SessionOperationResponse(BaseModel):
    """Sanitized outcome for delete and cancellation operations."""

    model_config = ConfigDict(frozen=True)

    status: Literal["deleted", "cancelled", "idle", "stored"]
    session_id: UUID
