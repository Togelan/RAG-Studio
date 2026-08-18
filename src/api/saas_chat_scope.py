"""Composite tenant identity for SaaS chat persistence and execution."""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from typing import NewType, TypedDict
from uuid import UUID

ExecutionKey = NewType("ExecutionKey", str)
ChatbotConfigurationFingerprint = NewType("ChatbotConfigurationFingerprint", str)


class CheckpointConfigurable(TypedDict):
    """LangGraph configurable values with an opaque tenant thread key."""

    thread_id: ExecutionKey


class CheckpointConfiguration(TypedDict):
    """LangGraph checkpoint configuration for one tenant execution."""

    configurable: CheckpointConfigurable


@dataclass(frozen=True, slots=True)
class SaasChatContext:
    """Trusted workspace, user, and chatbot identity."""

    workspace_id: UUID
    user_id: UUID
    chatbot_id: UUID


@dataclass(frozen=True, slots=True)
class SaasChatScope:
    """Complete trusted identity for one conversation execution."""

    workspace_id: UUID
    user_id: UUID
    chatbot_id: UUID
    session_id: UUID

    @property
    def context(self) -> SaasChatContext:
        """Return the session-independent tenant chat context."""
        return SaasChatContext(self.workspace_id, self.user_id, self.chatbot_id)


def derive_execution_key(scope: SaasChatScope, signing_key: bytes) -> ExecutionKey:
    """Derive a stable opaque key that changes with every scope dimension."""
    material = b"\x01".join(
        (
            scope.workspace_id.bytes,
            scope.user_id.bytes,
            scope.chatbot_id.bytes,
            scope.session_id.bytes,
        )
    )
    digest = hmac.new(signing_key, material, hashlib.sha256).hexdigest()
    return ExecutionKey(f"chat_{digest}")


def checkpoint_configuration(
    scope: SaasChatScope, signing_key: bytes
) -> CheckpointConfiguration:
    """Build the only checkpoint selector accepted by tenant chat execution."""
    return {"configurable": {"thread_id": derive_execution_key(scope, signing_key)}}
