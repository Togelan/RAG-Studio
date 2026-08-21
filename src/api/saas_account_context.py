"""Trusted Account and Workspace context resolution facade."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from src.api.saas_account_models import AccountContext, SelectedAccountContext


class AccountContextStore(Protocol):
    """Persistence authority required by the BFF context boundary."""

    async def list_available_contexts(
        self, user_id: UUID
    ) -> tuple[AccountContext, ...]: ...

    async def resolve_selection(
        self,
        user_id: UUID,
        *,
        account_id: UUID,
        workspace_id: UUID | None,
    ) -> SelectedAccountContext: ...

    async def owned_account_for_new_workspace(
        self, user_id: UUID, selected_account_id: UUID | None
    ) -> UUID: ...


@dataclass(frozen=True, slots=True)
class PostgresAccountContextResolver:
    """Expose only selections independently confirmed by Postgres."""

    store: AccountContextStore

    async def available(self, user_id: UUID) -> tuple[AccountContext, ...]:
        """Return every active owned or Workspace-member context."""
        return await self.store.list_available_contexts(user_id)

    async def resolve(
        self,
        user_id: UUID,
        *,
        account_id: UUID,
        workspace_id: UUID | None,
    ) -> SelectedAccountContext:
        """Resolve an explicit Account and optional Workspace selection."""
        return await self.store.resolve_selection(
            user_id,
            account_id=account_id,
            workspace_id=workspace_id,
        )

    async def owned_account_for_new_workspace(
        self, user_id: UUID, selected_account_id: UUID | None
    ) -> UUID:
        """Resolve the server-owned Account for a new Workspace."""
        return await self.store.owned_account_for_new_workspace(
            user_id, selected_account_id
        )
