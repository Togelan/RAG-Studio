from __future__ import annotations

from typing import assert_never
from uuid import UUID, uuid4

import pytest
from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models as qmodels

from src.api.saas_sessions import WorkspaceRole
from src.api.saas_tenant_context import TrustedWorkspaceContext
from src.vector_store.workspace_collections import (
    CollectionAccessDeniedError,
    CollectionFailureCode,
    CollectionProvisioningError,
    CollectionStateConflictError,
    ProvisioningFailed,
    ProvisioningResult,
    ProvisioningSucceeded,
    WorkspaceCollectionClaim,
    WorkspaceCollectionName,
    WorkspaceCollectionProvisioner,
    WorkspaceCollectionState,
    derive_workspace_collection_name,
)


class FakeRegistry:
    def __init__(
        self,
        allowed: set[UUID],
        *,
        conflict_once: bool = False,
        archive_on_conflict: bool = False,
    ) -> None:
        self.allowed = allowed
        self.states: dict[UUID, WorkspaceCollectionState] = {}
        self.names: dict[UUID, WorkspaceCollectionName] = {}
        self.attempts: dict[UUID, int] = {}
        self.failures: dict[UUID, CollectionFailureCode] = {}
        self.conflict_once = conflict_once
        self.archive_on_conflict = archive_on_conflict

    async def claim(self, workspace_id: UUID) -> WorkspaceCollectionClaim:
        state = self.states.get(workspace_id, WorkspaceCollectionState.PENDING)
        if (
            workspace_id not in self.allowed
            or state is WorkspaceCollectionState.ARCHIVED
        ):
            raise CollectionAccessDeniedError
        name = self.names.setdefault(
            workspace_id, derive_workspace_collection_name(workspace_id)
        )
        if state is not WorkspaceCollectionState.READY:
            self.states[workspace_id] = WorkspaceCollectionState.PROVISIONING
            self.attempts[workspace_id] = self.attempts.get(workspace_id, 0) + 1
        return WorkspaceCollectionClaim(workspace_id, name)

    async def complete(self, workspace_id: UUID, result: ProvisioningResult) -> None:
        if self.conflict_once:
            self.conflict_once = False
            if self.archive_on_conflict:
                self.states[workspace_id] = WorkspaceCollectionState.ARCHIVED
            else:
                self.states[workspace_id] = WorkspaceCollectionState.READY
            raise CollectionStateConflictError
        if self.states.get(workspace_id) is not WorkspaceCollectionState.PROVISIONING:
            raise CollectionStateConflictError
        match result:
            case ProvisioningSucceeded():
                self.states[workspace_id] = WorkspaceCollectionState.READY
                self.failures.pop(workspace_id, None)
            case ProvisioningFailed(code=code):
                self.states[workspace_id] = WorkspaceCollectionState.FAILED
                self.failures[workspace_id] = code
            case unreachable:
                assert_never(unreachable)

    async def state(self, workspace_id: UUID) -> WorkspaceCollectionState:
        if workspace_id not in self.allowed:
            raise CollectionAccessDeniedError
        return self.states.get(workspace_id, WorkspaceCollectionState.PENDING)


def _context(workspace_id: UUID) -> TrustedWorkspaceContext:
    return TrustedWorkspaceContext(uuid4(), workspace_id, WorkspaceRole.OWNER)


def test_collection_name_is_deterministic_opaque_and_workspace_distinct() -> None:
    # Given: two workspace UUIDs, including a repeated first UUID.
    first = uuid4()
    second = uuid4()

    # When: the BFF derives internal collection identifiers.
    first_name = derive_workspace_collection_name(first)
    repeated_name = derive_workspace_collection_name(first)
    second_name = derive_workspace_collection_name(second)

    # Then: only the opaque registry format is stable and workspace-distinct.
    assert first_name == repeated_name
    assert first_name != second_name
    assert str(first) not in first_name
    assert len(first_name) == 35
    assert first_name.startswith("ws_")
    assert all(character in "0123456789abcdef" for character in first_name[3:])


@pytest.mark.asyncio
async def test_provisioning_two_workspaces_is_distinct_and_idempotent() -> None:
    # Given: two authorized workspaces and an empty real Qdrant instance.
    first = uuid4()
    second = uuid4()
    registry = FakeRegistry({first, second})
    client = AsyncQdrantClient(location=":memory:")
    provisioner = WorkspaceCollectionProvisioner(registry, client)

    try:
        # When: each workspace resolves and the first is retried.
        first_resolved = await provisioner.resolve(_context(first))
        second_resolved = await provisioner.resolve(_context(second))
        first_retried = await provisioner.resolve(_context(first))

        # Then: both real collections exist and retry reuses only the first mapping.
        assert first_resolved.name != second_resolved.name
        assert first_retried.name == first_resolved.name
        assert await client.collection_exists(first_resolved.name)
        assert await client.collection_exists(second_resolved.name)
        assert registry.states[first] is WorkspaceCollectionState.READY
        assert registry.states[second] is WorkspaceCollectionState.READY
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_schema_collision_fails_sanitized_then_retry_recovers() -> None:
    # Given: the deterministic name is occupied by an incompatible collection.
    workspace_id = uuid4()
    registry = FakeRegistry({workspace_id})
    client = AsyncQdrantClient(location=":memory:")
    name = derive_workspace_collection_name(workspace_id)
    await client.create_collection(
        collection_name=name,
        vectors_config=qmodels.VectorParams(size=3, distance=qmodels.Distance.DOT),
    )
    provisioner = WorkspaceCollectionProvisioner(registry, client)

    try:
        # When: provisioning collides, then the foreign collection is removed and retried.
        with pytest.raises(CollectionProvisioningError) as captured:
            await provisioner.resolve(_context(workspace_id))
        await client.delete_collection(name)
        recovered = await provisioner.resolve(_context(workspace_id))

        # Then: failure is durable/redacted and retry reaches a compatible ready state.
        assert captured.value.code is CollectionFailureCode.INCOMPATIBLE_SCHEMA
        assert name not in str(captured.value)
        assert str(workspace_id) not in str(captured.value)
        assert recovered.name == name
        assert registry.attempts[workspace_id] == 2
        assert registry.states[workspace_id] is WorkspaceCollectionState.READY
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_tampered_or_archived_context_never_returns_collection_capability() -> (
    None
):
    # Given: one active workspace, one foreign selector, and one archived workspace.
    active = uuid4()
    foreign = uuid4()
    archived = uuid4()
    registry = FakeRegistry({active, archived})
    registry.states[archived] = WorkspaceCollectionState.ARCHIVED
    client = AsyncQdrantClient(location=":memory:")
    provisioner = WorkspaceCollectionProvisioner(registry, client)

    try:
        # When/Then: neither unauthorized context can reach collection resolution.
        with pytest.raises(CollectionAccessDeniedError):
            await provisioner.resolve(_context(foreign))
        with pytest.raises(CollectionAccessDeniedError):
            await provisioner.resolve(_context(archived))
        assert not (await client.get_collections()).collections
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_completion_conflict_reconciles_ready_but_denies_archive() -> None:
    # Given: one concurrent completion and one archive racing completion.
    ready_workspace = uuid4()
    archived_workspace = uuid4()
    client = AsyncQdrantClient(location=":memory:")
    ready_registry = FakeRegistry({ready_workspace}, conflict_once=True)
    archived_registry = FakeRegistry(
        {archived_workspace}, conflict_once=True, archive_on_conflict=True
    )

    try:
        # When: the durable state moves during completion.
        ready = await WorkspaceCollectionProvisioner(ready_registry, client).resolve(
            _context(ready_workspace)
        )
        with pytest.raises(CollectionAccessDeniedError):
            await WorkspaceCollectionProvisioner(archived_registry, client).resolve(
                _context(archived_workspace)
            )

        # Then: ready reconciles idempotently, while archived returns no capability.
        assert ready.name == derive_workspace_collection_name(ready_workspace)
        assert (
            archived_registry.states[archived_workspace]
            is WorkspaceCollectionState.ARCHIVED
        )
    finally:
        await client.close()
