"""Resolve tenant RAG storage only from trusted BFF workspace context."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from qdrant_client import AsyncQdrantClient

from src.api.saas_tenant_context import TrustedWorkspaceContext
from src.vector_store.tenant_store import TenantRagStore
from src.vector_store.workspace_collections import (
    WorkspaceCollectionProvisioner,
    WorkspaceCollectionRegistry,
)

QdrantClientProvider = Callable[[], Awaitable[AsyncQdrantClient]]


@dataclass(frozen=True, slots=True)
class TrustedTenantRagResolver:
    """Bind RAG operations after membership and collection resolution."""

    registry: WorkspaceCollectionRegistry
    client_provider: QdrantClientProvider

    async def resolve(self, context: TrustedWorkspaceContext) -> TenantRagStore:
        """Return a workspace-bound store with no caller collection authority."""
        client = await self.client_provider()
        resolved = await WorkspaceCollectionProvisioner(
            self.registry, client
        ).resolve(context)
        return TenantRagStore(resolved)
