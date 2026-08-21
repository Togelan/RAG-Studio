"""Immutable Account and trusted context contracts for FR-022."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from src.api.saas_sessions import WorkspaceRole


class AccountStatus(StrEnum):
    """Account states exposed by the Group 1 context boundary."""

    ACTIVE = "active"


class WorkspaceContextStatus(StrEnum):
    """Workspace states admitted to an authenticated context."""

    ACTIVE = "active"


class AccountContextErrorCode(StrEnum):
    """Sanitized Account-context failure classes."""

    DENIED = "denied"
    CONFLICT = "conflict"
    UNAVAILABLE = "unavailable"


class AccountContextError(Exception):
    """Sanitized failure kept mutable for Python traceback assignment."""

    def __init__(self, code: AccountContextErrorCode) -> None:
        super().__init__()
        self.code = code

    def __str__(self) -> str:
        return f"account context {self.code.value}"


@dataclass(frozen=True, slots=True)
class AccountOwnerProjection:
    """Owner-only authority hooks without unapproved commercial values."""

    can_manage_billing: bool = True
    can_view_plan: bool = True
    can_view_limits: bool = True


@dataclass(frozen=True, slots=True)
class WorkspaceContext:
    """One server-confirmed active Workspace membership."""

    id: UUID
    name: str
    role: WorkspaceRole
    status: WorkspaceContextStatus = WorkspaceContextStatus.ACTIVE


@dataclass(frozen=True, slots=True)
class AccountContext:
    """One owned or foreign Account grouped with accessible Workspaces."""

    id: UUID
    label: str
    status: AccountStatus
    owner_projection: AccountOwnerProjection | None
    workspaces: tuple[WorkspaceContext, ...]


@dataclass(frozen=True, slots=True)
class SelectedAccountContext:
    """Explicit Account selection with an optional trusted Workspace."""

    account: AccountContext
    workspace: WorkspaceContext | None
