from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from src.api.saas_chat_models import (
    ChatbotConfiguration,
    ChatbotExecutionConfiguration,
    ExecutionChannel,
    SupportedLocale,
)


@dataclass(frozen=True, slots=True)
class EnabledChatbots:
    configuration: ChatbotConfiguration

    async def resolve_execution(
        self,
        workspace_id: UUID,
        chatbot_id: UUID,
        channel: ExecutionChannel,
        locale: SupportedLocale,
    ) -> ChatbotExecutionConfiguration:
        del workspace_id, chatbot_id, locale
        return ChatbotExecutionConfiguration(self.configuration, channel)
