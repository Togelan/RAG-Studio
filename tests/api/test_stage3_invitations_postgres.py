from __future__ import annotations

import os
from datetime import timedelta
from uuid import UUID, uuid4

import anyio
import asyncpg
import pytest
from pydantic import SecretStr

from src.api.saas_invitation_delivery import InvitationMessage, InvitationTokenIssuer
from src.api.saas_invitation_store import PostgresInvitationStore
from src.api.saas_workspace_models import (
    InvitationAcceptance,
    InvitationCreation,
    InvitationRole,
    InvitationStatus,
    Workspace,
    WorkspaceActor,
    WorkspaceCreation,
    WorkspaceErrorCode,
    WorkspaceOperationError,
)
from src.api.saas_workspace_store import PostgresWorkspaceStore
from src.api.saas_workspaces import PostgresWorkspaceService


class _CapturingMailer:
    def __init__(self) -> None:
        self.messages: list[InvitationMessage] = []

    async def send(self, message: InvitationMessage) -> None:
        self.messages.append(message)


def _database_url() -> str:
    value = os.getenv("TASK5_DATABASE_URL")
    if value is None:
        pytest.skip("TASK5_DATABASE_URL is required for live Postgres coverage")
    return value


def _service(database_url: str) -> tuple[PostgresWorkspaceService, _CapturingMailer]:
    mailer = _CapturingMailer()
    return (
        PostgresWorkspaceService(
            PostgresWorkspaceStore(database_url),
            PostgresInvitationStore(
                database_url,
                InvitationTokenIssuer(SecretStr("task5-test-secret-" * 4)),
                mailer,
            ),
        ),
        mailer,
    )


async def _cleanup(database_url: str, workspace_ids: tuple[UUID, ...]) -> None:
    connection = await asyncpg.connect(database_url, timeout=5.0)
    try:
        await connection.execute(
            "DELETE FROM public.workspaces WHERE id = ANY($1::uuid[])", workspace_ids
        )
    finally:
        await connection.close(timeout=5.0)


@pytest.mark.asyncio
async def test_invitation_acceptance_is_concurrent_idempotent_and_hash_only() -> None:
    # Given: one owner workspace and a retry-stable admin invitation.
    database_url = _database_url()
    service, mailer = _service(database_url)
    owner_id = uuid4()
    admin_id = uuid4()
    workspace = await service.create_workspace(
        WorkspaceCreation(owner_id, "Concurrent Invite", "workspace-concurrent")
    )
    actor = WorkspaceActor(workspace.id, owner_id)
    command = InvitationCreation(
        actor,
        "admin@example.test",
        InvitationRole.ADMIN,
        "invite-concurrent-admin",
    )
    try:
        first = await service.create_invitation(command)
        retry = await service.create_invitation(command)
        results: list[Workspace] = []

        async def accept() -> None:
            results.append(
                await service.accept_invitation(
                    InvitationAcceptance(
                        admin_id, "admin@example.test", mailer.messages[0].token
                    )
                )
            )

        # When: the same verified user accepts the same token concurrently.
        async with anyio.create_task_group() as tasks:
            tasks.start_soon(accept)
            tasks.start_soon(accept)

        # Then: one membership exists and only a hash persisted.
        connection = await asyncpg.connect(database_url, timeout=5.0)
        try:
            invitation = await connection.fetchrow(
                """
                SELECT token_hash, status::text AS status, accepted_by
                  FROM public.workspace_invitations WHERE id = $1
                """,
                first.id,
            )
            membership_count = await connection.fetchval(
                """
                SELECT count(*) FROM public.workspace_memberships
                 WHERE workspace_id = $1 AND user_id = $2 AND status = 'active'
                """,
                workspace.id,
                admin_id,
            )
        finally:
            await connection.close(timeout=5.0)
        assert first.id == retry.id
        assert len(results) == 2
        assert membership_count == 1
        assert invitation is not None
        assert invitation["status"] == InvitationStatus.ACCEPTED.value
        assert invitation["accepted_by"] == admin_id
        assert invitation["token_hash"] != mailer.messages[0].token
        assert len(invitation["token_hash"]) == 64
        assert mailer.messages[0].token == mailer.messages[1].token
    finally:
        await _cleanup(database_url, (workspace.id,))


@pytest.mark.asyncio
async def test_revoked_and_expired_invitations_deny_without_membership() -> None:
    # Given: one revoked invite and one database-expired invite.
    database_url = _database_url()
    service, mailer = _service(database_url)
    owner_id = uuid4()
    workspace = await service.create_workspace(
        WorkspaceCreation(owner_id, "Invite Failures", "workspace-failures")
    )
    actor = WorkspaceActor(workspace.id, owner_id)
    revoked = await service.create_invitation(
        InvitationCreation(
            actor,
            "revoked@example.test",
            InvitationRole.MEMBER,
            "invite-revoked-member",
        )
    )
    revoked_token = mailer.messages[-1].token
    await service.revoke_invitation(actor, revoked.id)
    expired = await service.create_invitation(
        InvitationCreation(
            actor,
            "expired@example.test",
            InvitationRole.MEMBER,
            "invite-expired-member",
        )
    )
    expired_token = mailer.messages[-1].token
    connection = await asyncpg.connect(database_url, timeout=5.0)
    try:
        await connection.execute(
            """
            UPDATE public.workspace_invitations
               SET created_at = now() - $2::interval,
                   expires_at = now() - $1::interval
             WHERE id = $3
            """,
            timedelta(days=1),
            timedelta(days=2),
            expired.id,
        )
    finally:
        await connection.close(timeout=5.0)
    try:
        # When: verified users present revoked and expired bearer tokens.
        with pytest.raises(WorkspaceOperationError) as revoked_error:
            await service.accept_invitation(
                InvitationAcceptance(uuid4(), "revoked@example.test", revoked_token)
            )
        with pytest.raises(WorkspaceOperationError) as expired_error:
            await service.accept_invitation(
                InvitationAcceptance(uuid4(), "expired@example.test", expired_token)
            )

        # Then: both fail closed and expiry is persisted without membership creation.
        connection = await asyncpg.connect(database_url, timeout=5.0)
        try:
            status_value = await connection.fetchval(
                "SELECT status::text FROM public.workspace_invitations WHERE id = $1",
                expired.id,
            )
            membership_count = await connection.fetchval(
                """
                SELECT count(*) FROM public.workspace_memberships
                 WHERE workspace_id = $1 AND user_id <> $2
                """,
                workspace.id,
                owner_id,
            )
        finally:
            await connection.close(timeout=5.0)
        assert revoked_error.value.code is WorkspaceErrorCode.DENIED
        assert expired_error.value.code is WorkspaceErrorCode.DENIED
        assert status_value == InvitationStatus.EXPIRED.value
        assert membership_count == 0
    finally:
        await _cleanup(database_url, (workspace.id,))
