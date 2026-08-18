"""Trusted internal tenant context derived from the authenticated BFF session."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from src.api.saas_auth_context import AuthContext
from src.api.saas_sessions import WorkspaceRole


class WorkspaceContextUnavailableError(PermissionError):
    """The authenticated request has no active workspace authority."""


@dataclass(frozen=True, slots=True)
class TrustedWorkspaceContext:
    """Identity and active membership already revalidated by the BFF."""

    user_id: UUID
    workspace_id: UUID
    role: WorkspaceRole


def trusted_workspace_context(auth_context: AuthContext) -> TrustedWorkspaceContext:
    """Derive one tenant context without accepting browser workspace data."""
    membership = auth_context.membership
    session = auth_context.session
    claims = auth_context.claims
    if (
        membership is None
        or claims.user_id != session.user_id
        or claims.email != session.email
        or session.active_workspace_id != membership.workspace_id
    ):
        raise WorkspaceContextUnavailableError
    return TrustedWorkspaceContext(
        user_id=session.user_id,
        workspace_id=membership.workspace_id,
        role=membership.role,
    )
