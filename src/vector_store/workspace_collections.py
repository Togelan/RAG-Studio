"""Trusted per-workspace Qdrant collection resolution and provisioning."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import StrEnum
from typing import NewType, Protocol, assert_never
from uuid import UUID

from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models as qmodels
from qdrant_client.http.exceptions import ApiException

from src.api.saas_tenant_context import TrustedWorkspaceContext
from src.ingestion.embedding import DENSE_EMBEDDING_SIZE

WorkspaceCollectionName = NewType("WorkspaceCollectionName", str)


class WorkspaceCollectionState(StrEnum):
    """Durable workspace collection lifecycle states."""

    PENDING = "pending"
    PROVISIONING = "provisioning"
    READY = "ready"
    FAILED = "failed"
    ARCHIVED = "archived"


class CollectionFailureCode(StrEnum):
    """Sanitized provisioning failures safe for durable registry state."""

    BACKEND_UNAVAILABLE = "backend_unavailable"
    INCOMPATIBLE_SCHEMA = "incompatible_schema"
    REGISTRY_CONFLICT = "registry_conflict"


@dataclass(frozen=True, slots=True)
class CollectionAccessDeniedError(PermissionError):
    """The trusted tenant no longer has an active collection mapping."""

    def __str__(self) -> str:
        return "workspace storage is unavailable"


@dataclass(frozen=True, slots=True)
class CollectionProvisioningError(RuntimeError):
    """Provisioning failed without exposing provider or collection detail."""

    code: CollectionFailureCode

    def __str__(self) -> str:
        return "workspace storage provisioning failed"


class CollectionStateConflictError(RuntimeError):
    """The durable lifecycle moved before completion."""


class CollectionRegistryUnavailableError(RuntimeError):
    """The durable collection registry could not be reached."""


@dataclass(frozen=True, slots=True)
class WorkspaceCollectionClaim:
    """Internal registry claim; never serialize this value."""

    workspace_id: UUID
    name: WorkspaceCollectionName


@dataclass(frozen=True, slots=True)
class ProvisioningSucceeded:
    """Durable successful provisioning outcome."""


@dataclass(frozen=True, slots=True)
class ProvisioningFailed:
    """Durable failed provisioning outcome with a sanitized code."""

    code: CollectionFailureCode


type ProvisioningResult = ProvisioningSucceeded | ProvisioningFailed


class WorkspaceCollectionRegistry(Protocol):
    """Durable lifecycle authority for workspace collection mappings."""

    async def claim(self, workspace_id: UUID) -> WorkspaceCollectionClaim: ...

    async def complete(
        self, workspace_id: UUID, result: ProvisioningResult
    ) -> None: ...

    async def state(self, workspace_id: UUID) -> WorkspaceCollectionState: ...


@dataclass(frozen=True, slots=True)
class ResolvedWorkspaceCollection:
    """Internal authorized Qdrant capability for one workspace."""

    context: TrustedWorkspaceContext
    client: AsyncQdrantClient
    name: WorkspaceCollectionName


def derive_workspace_collection_name(workspace_id: UUID) -> WorkspaceCollectionName:
    """Derive the opaque registry-compatible name for a workspace UUID."""
    digest = hashlib.md5(
        f"rag-studio:workspace:v1:{workspace_id}".encode(),
        usedforsecurity=False,
    ).hexdigest()
    return WorkspaceCollectionName(f"ws_{digest}")


@dataclass(frozen=True, slots=True)
class WorkspaceCollectionProvisioner:
    """Retry-safe workspace collection provisioning service."""

    registry: WorkspaceCollectionRegistry
    client: AsyncQdrantClient

    async def resolve(
        self, context: TrustedWorkspaceContext
    ) -> ResolvedWorkspaceCollection:
        """Return an authorized collection only after compatibility is ready."""
        claim = await self.registry.claim(context.workspace_id)
        expected_name = derive_workspace_collection_name(context.workspace_id)
        if claim.workspace_id != context.workspace_id or claim.name != expected_name:
            await self._complete_failure(
                context.workspace_id, CollectionFailureCode.REGISTRY_CONFLICT
            )
            raise CollectionProvisioningError(CollectionFailureCode.REGISTRY_CONFLICT)

        try:
            await _ensure_compatible_collection(self.client, expected_name)
        except CollectionProvisioningError as error:
            await self._complete_failure(context.workspace_id, error.code)
            raise

        try:
            await self.registry.complete(context.workspace_id, ProvisioningSucceeded())
        except CollectionStateConflictError:
            reconciled = await self.registry.claim(context.workspace_id)
            if (
                reconciled.workspace_id != context.workspace_id
                or reconciled.name != expected_name
            ):
                raise CollectionProvisioningError(
                    CollectionFailureCode.REGISTRY_CONFLICT
                ) from None

        await self._require_ready(context.workspace_id)
        return ResolvedWorkspaceCollection(context, self.client, expected_name)

    async def _complete_failure(
        self, workspace_id: UUID, code: CollectionFailureCode
    ) -> None:
        try:
            await self.registry.complete(workspace_id, ProvisioningFailed(code))
        except CollectionStateConflictError:
            state = await self.registry.state(workspace_id)
            if state is WorkspaceCollectionState.ARCHIVED:
                raise CollectionAccessDeniedError from None

    async def _require_ready(self, workspace_id: UUID) -> None:
        state = await self.registry.state(workspace_id)
        match state:
            case WorkspaceCollectionState.READY:
                return
            case WorkspaceCollectionState.ARCHIVED:
                raise CollectionAccessDeniedError
            case (
                WorkspaceCollectionState.PENDING
                | WorkspaceCollectionState.PROVISIONING
                | WorkspaceCollectionState.FAILED
            ):
                raise CollectionProvisioningError(
                    CollectionFailureCode.REGISTRY_CONFLICT
                )
            case unreachable:
                assert_never(unreachable)


async def _ensure_compatible_collection(
    client: AsyncQdrantClient, name: WorkspaceCollectionName
) -> None:
    try:
        if not await client.collection_exists(name):
            await client.create_collection(
                collection_name=name,
                vectors_config={
                    "dense": qmodels.VectorParams(
                        size=DENSE_EMBEDDING_SIZE,
                        distance=qmodels.Distance.COSINE,
                    )
                },
                sparse_vectors_config={
                    "sparse": qmodels.SparseVectorParams(
                        index=qmodels.SparseIndexParams(on_disk=False)
                    )
                },
            )
        information = await client.get_collection(name)
    except ApiException, OSError, RuntimeError, ValueError:
        raise CollectionProvisioningError(
            CollectionFailureCode.BACKEND_UNAVAILABLE
        ) from None
    if not _compatible_schema(information):
        raise CollectionProvisioningError(CollectionFailureCode.INCOMPATIBLE_SCHEMA)


def _compatible_schema(information: qmodels.CollectionInfo) -> bool:
    parameters = information.config.params
    match parameters.vectors:
        case dict() as vectors:
            dense = vectors.get("dense")
        case qmodels.VectorParams() | None:
            return False
        case unreachable:
            assert_never(unreachable)
    sparse_vectors = parameters.sparse_vectors
    if dense is None or sparse_vectors is None:
        return False
    return (
        set(vectors) == {"dense"}
        and dense.size == DENSE_EMBEDDING_SIZE
        and dense.distance is qmodels.Distance.COSINE
        and set(sparse_vectors) == {"sparse"}
    )
