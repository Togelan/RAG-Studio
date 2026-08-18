"""Postgres-backed workspace collection lifecycle registry."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Final, assert_never
from uuid import UUID

import asyncpg
from pydantic import ConfigDict, TypeAdapter, ValidationError

from src.api.saas_workspace_database import workspace_transaction
from src.api.saas_workspace_models import (
    WorkspaceErrorCode,
    WorkspaceOperationError,
)
from src.vector_store.workspace_collections import (
    CollectionAccessDeniedError,
    CollectionRegistryUnavailableError,
    CollectionStateConflictError,
    ProvisioningFailed,
    ProvisioningResult,
    ProvisioningSucceeded,
    WorkspaceCollectionClaim,
    WorkspaceCollectionName,
    WorkspaceCollectionState,
)

_STRICT_STRING: Final = TypeAdapter(str, config=ConfigDict(strict=True))


@dataclass(frozen=True, slots=True)
class PostgresWorkspaceCollectionRegistry:
    """Use the Task 2 registry functions as the provisioning authority."""

    database_url: str

    async def claim(self, workspace_id: UUID) -> WorkspaceCollectionClaim:
        """Claim an active workspace mapping for an idempotent attempt."""
        async with _registry_transaction(self.database_url) as connection:
            await connection.execute("SET LOCAL ROLE service_role")
            raw_name = await connection.fetchval(
                "SELECT private.claim_workspace_collection($1)", workspace_id
            )
        try:
            name = _STRICT_STRING.validate_python(raw_name)
        except ValidationError:
            raise CollectionRegistryUnavailableError from None
        return WorkspaceCollectionClaim(workspace_id, WorkspaceCollectionName(name))

    async def complete(self, workspace_id: UUID, result: ProvisioningResult) -> None:
        """Persist a sanitized successful or failed provisioning result."""
        match result:
            case ProvisioningSucceeded():
                succeeded = True
                error_code = None
            case ProvisioningFailed(code=code):
                succeeded = False
                error_code = code.value
            case unreachable:
                assert_never(unreachable)
        async with _registry_transaction(self.database_url) as connection:
            await connection.execute("SET LOCAL ROLE service_role")
            await connection.execute(
                "SELECT private.complete_workspace_collection($1, $2, $3)",
                workspace_id,
                succeeded,
                error_code,
            )

    async def state(self, workspace_id: UUID) -> WorkspaceCollectionState:
        """Read only the public lifecycle state for trusted readiness checks."""
        async with _registry_transaction(self.database_url) as connection:
            raw_state = await connection.fetchval(
                """
                SELECT registry.state::text
                  FROM public.workspace_collection_registry AS registry
                  JOIN public.workspaces AS workspace
                    ON workspace.id = registry.workspace_id
                 WHERE registry.workspace_id = $1
                """,
                workspace_id,
            )
        if raw_state is None:
            raise CollectionAccessDeniedError
        try:
            state = _STRICT_STRING.validate_python(raw_state)
            return WorkspaceCollectionState(state)
        except ValidationError, ValueError:
            raise CollectionRegistryUnavailableError from None


@asynccontextmanager
async def _registry_transaction(
    database_url: str,
) -> AsyncIterator[asyncpg.Connection]:
    try:
        async with workspace_transaction(database_url) as connection:
            yield connection
    except WorkspaceOperationError as error:
        match error.code:
            case WorkspaceErrorCode.DENIED:
                raise CollectionAccessDeniedError from None
            case WorkspaceErrorCode.CONFLICT:
                raise CollectionStateConflictError from None
            case WorkspaceErrorCode.UNAVAILABLE:
                raise CollectionRegistryUnavailableError from None
            case unreachable:
                assert_never(unreachable)
