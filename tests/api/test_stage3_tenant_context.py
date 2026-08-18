from __future__ import annotations

from dataclasses import replace
from uuid import uuid4

import pytest

from src.api.saas_auth_context import AuthContext
from src.api.saas_identity import JwtClaims
from src.api.saas_security import BffSessionHandle
from src.api.saas_sessions import BffSession, Membership, WorkspaceRole
from src.api.saas_tenant_context import (
    WorkspaceContextUnavailableError,
    trusted_workspace_context,
)


def _auth_context(*, with_membership: bool = True) -> AuthContext:
    user_id = uuid4()
    workspace_id = uuid4()
    session = BffSession(
        handle=BffSessionHandle("opaque-handle"),
        user_id=user_id,
        email="member@example.test",
        access_token="server-only-access",
        refresh_token="server-only-refresh",
        expires_at=99_999_999_999.0,
        active_workspace_id=workspace_id,
    )
    membership = (
        Membership(workspace_id, WorkspaceRole.MEMBER) if with_membership else None
    )
    return AuthContext(
        session=session,
        claims=JwtClaims(user_id=user_id, email=session.email),
        membership=membership,
    )


def test_trusted_workspace_context_is_derived_only_from_revalidated_membership() -> (
    None
):
    # Given: Task 4 produced a verified session and active membership.
    auth_context = _auth_context()

    # When: the internal tenant capability is derived.
    context = trusted_workspace_context(auth_context)

    # Then: it uses server-owned identity and membership values only.
    assert context.user_id == auth_context.session.user_id
    assert context.workspace_id == auth_context.membership.workspace_id
    assert context.role is WorkspaceRole.MEMBER


def test_trusted_workspace_context_rejects_missing_or_mismatched_authority() -> None:
    # Given: one stale selection and one mismatched verified identity.
    missing = _auth_context(with_membership=False)
    valid = _auth_context()
    mismatched = replace(
        valid,
        claims=JwtClaims(user_id=uuid4(), email=valid.claims.email),
    )

    # When/Then: neither state can mint an internal tenant capability.
    with pytest.raises(WorkspaceContextUnavailableError):
        trusted_workspace_context(missing)
    with pytest.raises(WorkspaceContextUnavailableError):
        trusted_workspace_context(mismatched)
