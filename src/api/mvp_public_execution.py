"""Server-derived Personal Lab scope for an admitted public execution."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from uuid import UUID

import anyio
import asyncpg

from src.api.mvp_public_admission import PublicAdmission
from src.api.personal_lab_scope import PersonalLabScope, personal_lab_namespace


class PublicExecutionScopeUnavailableError(RuntimeError):
    """Hide stale publication and persistence failures at the public boundary."""


class PublicExecutionScopeSource(Protocol):
    """Resolve a scope ID only from a previously verified publication ID."""

    async def resolve_scope_id(self, publication_id: UUID) -> UUID | None: ...


@dataclass(frozen=True, slots=True)
class PublicExecutionScopeResolver:
    """Build namespace topology without accepting any browser scope selector."""

    source: PublicExecutionScopeSource
    root: Path

    async def resolve(self, admission: PublicAdmission) -> PersonalLabScope:
        """Resolve fresh enabled, entitled publication authority to one scope."""
        scope_id = await self.source.resolve_scope_id(admission.publication_id)
        if scope_id is None:
            raise PublicExecutionScopeUnavailableError
        namespace = personal_lab_namespace(scope_id)
        return PersonalLabScope(
            scope_id,
            namespace,
            self.root / namespace,
            namespace,
        )


@dataclass(frozen=True, slots=True)
class PostgresPublicExecutionScopeSource:
    """Recheck publication and entitlement before returning the private scope ID."""

    database_url: str

    async def resolve_scope_id(self, publication_id: UUID) -> UUID | None:
        """Return only a currently enabled and entitled publication's lab ID."""
        try:
            connection = await asyncpg.connect(
                self.database_url, timeout=5.0, command_timeout=5.0
            )
            try:
                value = await connection.fetchval(
                    "SELECT publication.personal_lab_id "
                    "FROM public.personal_lab_widget_publications AS publication "
                    "JOIN public.personal_lab_billing_projections AS billing "
                    "ON billing.personal_lab_id=publication.personal_lab_id "
                    "WHERE publication.id=$1 AND publication.state='enabled' "
                    "AND billing.entitled=true",
                    publication_id,
                )
            finally:
                with anyio.move_on_after(5.0, shield=True):
                    await connection.close(timeout=5.0)
        except asyncpg.PostgresError, OSError, TimeoutError:
            raise PublicExecutionScopeUnavailableError from None
        return None if value is None else UUID(str(value))
