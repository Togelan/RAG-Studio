"""Typed Workspace creation command."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class WorkspaceCreation:
    """Create one Workspace inside a server-confirmed owned Account."""

    user_id: UUID
    account_id: UUID
    name: str
    idempotency_key: str
