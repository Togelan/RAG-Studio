"""Validated FR-015 chatbot request and response schemas."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic_core import PydanticCustomError

from src.api.saas_chatbot_models import ChatbotDefinition, ChatbotRecord, ChatbotStatus


class LocalizedName(BaseModel):
    """Required English and Russian chatbot names."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    en: str = Field(min_length=1, max_length=120)
    ru: str = Field(min_length=1, max_length=120)

    @field_validator("en", "ru")
    @classmethod
    def strip_name(cls, value: str) -> str:
        """Reject whitespace-only names and persist their canonical form."""
        stripped = value.strip()
        if not stripped:
            raise PydanticCustomError(
                "chatbot_name",
                "name must contain visible characters",
            )
        return stripped


class LocalizedInstructions(BaseModel):
    """Bounded English and Russian system instructions."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    en: str = Field(default="", max_length=8_000)
    ru: str = Field(default="", max_length=8_000)

    @field_validator("en", "ru")
    @classmethod
    def strip_instructions(cls, value: str) -> str:
        """Persist canonical instructions without changing internal whitespace."""
        return value.strip()


class ChatbotDefinitionRequest(BaseModel):
    """Complete validated chatbot configuration accepted by create and update."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: LocalizedName
    instructions: LocalizedInstructions
    provider: str = Field(
        min_length=1,
        max_length=40,
        pattern=r"^[a-z][a-z0-9_-]*$",
    )
    model_name: str = Field(
        min_length=1,
        max_length=120,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$",
    )
    source_scope: Literal["workspace_all"]

    def to_definition(self) -> ChatbotDefinition:
        """Convert one parsed boundary model into the internal value object."""
        return ChatbotDefinition(
            name_en=self.name.en,
            name_ru=self.name.ru,
            instructions_en=self.instructions.en,
            instructions_ru=self.instructions.ru,
            provider=self.provider,
            model_name=self.model_name,
        )


class ChatbotUpdateRequest(ChatbotDefinitionRequest):
    """Full replacement guarded by the caller-observed version."""

    version: int = Field(ge=1)


class ChatbotVersionRequest(BaseModel):
    """Version guard for disable and archive operations."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: int = Field(ge=1)


class ChatbotResponse(BaseModel):
    """Non-secret workspace chatbot representation."""

    model_config = ConfigDict(frozen=True)

    id: UUID
    workspace_id: UUID
    name: LocalizedName
    instructions: LocalizedInstructions
    provider: str
    model_name: str
    source_scope: Literal["workspace_all"] = "workspace_all"
    status: ChatbotStatus
    version: int


def chatbot_response(record: ChatbotRecord) -> ChatbotResponse:
    """Map the internal record without exposing actor or persistence metadata."""
    definition = record.definition
    return ChatbotResponse(
        id=record.id,
        workspace_id=record.workspace_id,
        name=LocalizedName(en=definition.name_en, ru=definition.name_ru),
        instructions=LocalizedInstructions(
            en=definition.instructions_en,
            ru=definition.instructions_ru,
        ),
        provider=definition.provider,
        model_name=definition.model_name,
        status=record.status,
        version=record.version,
    )
