"""Typed browser contracts for unified authentication and Account context."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from src.api.saas_account_models import (
    AccountContext,
    AccountOwnerProjection,
    SelectedAccountContext,
)
from src.api.saas_sessions import BffSession, Membership


class AccountContextResolver(Protocol):
    """Resolve only Account and Workspace contexts trusted by Postgres."""

    async def available(self, user_id: UUID) -> tuple[AccountContext, ...]: ...

    async def resolve(
        self,
        user_id: UUID,
        *,
        account_id: UUID,
        workspace_id: UUID | None,
    ) -> SelectedAccountContext: ...


class AccountBootstrapper(Protocol):
    """Create the deterministic owner Account for an authenticated identity."""

    async def bootstrap_default_account(self, user_id: UUID) -> AccountContext: ...


class CredentialsRequest(BaseModel):
    """Bounded password-credential request."""

    model_config = ConfigDict(frozen=True)

    email: str = Field(min_length=3, max_length=320, pattern=r"^[^@\s]+@[^@\s]+$")
    password: str = Field(min_length=8, max_length=256)


class WorkspaceSelectionRequest(BaseModel):
    """Legacy-compatible explicit Workspace selection."""

    model_config = ConfigDict(frozen=True)

    workspace_id: UUID


class ContextSelectionRequest(BaseModel):
    """Explicit Account and optional Workspace selection."""

    model_config = ConfigDict(frozen=True)

    account_id: UUID
    workspace_id: UUID | None = None


class WorkspaceResponse(BaseModel):
    """Server-confirmed active Workspace projection."""

    model_config = ConfigDict(frozen=True)

    id: UUID
    role: str
    name: str | None = None


class AccountOwnerResponse(BaseModel):
    """Owner capabilities without commercial plan values."""

    model_config = ConfigDict(frozen=True)

    can_manage_billing: bool
    can_view_plan: bool
    can_view_limits: bool


class AccountResponse(BaseModel):
    """One trusted Account and its accessible Workspaces."""

    model_config = ConfigDict(frozen=True)

    id: UUID
    label: str
    status: str
    owner: AccountOwnerResponse | None
    workspaces: tuple[WorkspaceResponse, ...]


class SessionResponse(BaseModel):
    """Browser-safe identity and trusted Account context."""

    model_config = ConfigDict(frozen=True)

    user_id: UUID
    email: str
    accounts: tuple[AccountResponse, ...] = ()
    active_account_id: UUID | None = None
    workspace: WorkspaceResponse | None


class SignupResponse(BaseModel):
    """Sanitized signup result."""

    model_config = ConfigDict(frozen=True)

    confirmation_required: bool


def account_response(context: AccountContext) -> AccountResponse:
    """Map trusted internal Account context to its browser projection."""
    return AccountResponse(
        id=context.id,
        label=context.label,
        status=context.status.value,
        owner=_owner_response(context.owner_projection),
        workspaces=tuple(
            WorkspaceResponse(
                id=workspace.id,
                name=workspace.name,
                role=workspace.role.value,
            )
            for workspace in context.workspaces
        ),
    )


def session_response(
    session: BffSession,
    accounts: tuple[AccountContext, ...],
    membership: Membership | None = None,
) -> SessionResponse:
    """Map a revalidated session without exposing provider credentials."""
    workspace = _workspace_response(accounts, session.active_workspace_id)
    if workspace is None and membership is not None:
        workspace = WorkspaceResponse(
            id=membership.workspace_id, role=membership.role.value
        )
    return SessionResponse(
        user_id=session.user_id,
        email=session.email,
        accounts=tuple(account_response(account) for account in accounts),
        active_account_id=session.active_account_id,
        workspace=workspace,
    )


def account_for_workspace(
    accounts: tuple[AccountContext, ...], workspace_id: UUID
) -> UUID | None:
    """Resolve a legacy Workspace selector only when its Account is unambiguous."""
    matches = tuple(
        account.id
        for account in accounts
        if any(workspace.id == workspace_id for workspace in account.workspaces)
    )
    return matches[0] if len(matches) == 1 else None


def _owner_response(
    projection: AccountOwnerProjection | None,
) -> AccountOwnerResponse | None:
    if projection is None:
        return None
    return AccountOwnerResponse(
        can_manage_billing=projection.can_manage_billing,
        can_view_plan=projection.can_view_plan,
        can_view_limits=projection.can_view_limits,
    )


def _workspace_response(
    accounts: tuple[AccountContext, ...], workspace_id: UUID | None
) -> WorkspaceResponse | None:
    for account in accounts:
        for workspace in account.workspaces:
            if workspace.id == workspace_id:
                return WorkspaceResponse(
                    id=workspace.id, name=workspace.name, role=workspace.role.value
                )
    return None
