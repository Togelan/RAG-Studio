"""Server-owned Personal Lab scope resolution and namespace topology."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Final, Protocol
from uuid import UUID

import anyio
import asyncpg

_DATABASE_TIMEOUT_SECONDS: Final = 5.0
_NAMESPACE_PREFIX: Final = "pl_"


class PersonalLabScopeUnavailableError(RuntimeError):
    """Raised when the durable Personal Lab registry cannot resolve a scope."""

    def __str__(self) -> str:
        return "Personal Lab scope is unavailable."


class PersonalLabScopeRegistry(Protocol):
    """Resolve the durable opaque scope identifier for one trusted identity."""

    async def resolve(self, user_id: UUID) -> UUID: ...


@dataclass(frozen=True, slots=True)
class PersonalLabScope:
    """Opaque Personal Lab identity and its server-derived namespace topology."""

    id: UUID
    namespace: str
    data_root: Path
    collection_name: str


@dataclass(frozen=True, slots=True)
class PersonalLabScopeResolver:
    """Build trusted namespace topology from a durable registry result."""

    registry: PersonalLabScopeRegistry
    root: Path

    async def resolve(self, user_id: UUID) -> PersonalLabScope:
        """Resolve one identity without accepting a browser scope selector."""
        scope_id = await self.registry.resolve(user_id)
        namespace = personal_lab_namespace(scope_id)
        return PersonalLabScope(
            id=scope_id,
            namespace=namespace,
            data_root=self.root / namespace,
            collection_name=namespace,
        )


@dataclass(frozen=True, slots=True)
class PostgresPersonalLabScopeRegistry:
    """Provision and resolve Personal Lab identifiers transactionally."""

    database_url: str

    async def resolve(self, user_id: UUID) -> UUID:
        """Return the existing random scope or atomically create it once."""
        try:
            connection = await asyncpg.connect(
                self.database_url,
                timeout=_DATABASE_TIMEOUT_SECONDS,
                command_timeout=_DATABASE_TIMEOUT_SECONDS,
            )
            try:
                async with connection.transaction():
                    await connection.execute("SET LOCAL ROLE service_role")
                    scope_id: UUID | None = await connection.fetchval(
                        """
                        INSERT INTO public.personal_labs (user_id)
                        VALUES ($1)
                        ON CONFLICT (user_id) DO UPDATE
                        SET user_id = EXCLUDED.user_id
                        RETURNING id
                        """,
                        user_id,
                    )
            finally:
                with anyio.move_on_after(_DATABASE_TIMEOUT_SECONDS, shield=True):
                    await connection.close(timeout=_DATABASE_TIMEOUT_SECONDS)
        except asyncpg.PostgresError, OSError, TimeoutError:
            raise PersonalLabScopeUnavailableError from None
        if scope_id is None:
            raise PersonalLabScopeUnavailableError
        return scope_id


def personal_lab_namespace(scope_id: UUID) -> str:
    """Return the only valid Personal Lab root and collection namespace."""
    return f"{_NAMESPACE_PREFIX}{scope_id.hex}"
