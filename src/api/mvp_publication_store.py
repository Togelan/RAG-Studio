"""Transactional Postgres authority for one Personal Lab publication."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import assert_never
from uuid import UUID, uuid4

import anyio
import asyncpg

from src.api.mvp_publication import (
    Publication,
    PublicationAuditEvent,
    PublicationConflictError,
    PublicationEventType,
    PublicationState,
)
from src.api.mvp_publication_origin import canonicalize_origin


class PublicationStoreUnavailableError(Exception):
    """Sanitized durable publication failure."""


@asynccontextmanager
async def _transaction(database_url: str) -> AsyncIterator[asyncpg.Connection]:
    try:
        connection = await asyncpg.connect(
            database_url, timeout=5.0, command_timeout=5.0
        )
        try:
            async with connection.transaction():
                await connection.execute("SET LOCAL statement_timeout = '5s'")
                yield connection
        finally:
            with anyio.move_on_after(5.0, shield=True):
                await connection.close(timeout=5.0)
    except asyncpg.PostgresError, OSError, TimeoutError:
        raise PublicationStoreUnavailableError from None


@dataclass(frozen=True, slots=True)
class PostgresMvpPublicationStore:
    """Serialize lifecycle changes against Task 3 publication procedures."""

    database_url: str

    async def read(self, personal_lab_id: UUID) -> Publication | None:
        """Read fresh publication and retained audit state by trusted lab ID."""
        async with _transaction(self.database_url) as connection:
            return await _load(connection, personal_lab_id)

    async def publish(self, personal_lab_id: UUID, raw_origin: str) -> Publication:
        """Create or idempotently re-enable the sole canonical publication."""
        allowed_origin = canonicalize_origin(raw_origin)
        async with _transaction(self.database_url) as connection:
            await _lock(connection, personal_lab_id)
            current = await _load(connection, personal_lab_id)
            if current is None:
                await connection.fetchval(
                    "SELECT private.publish_personal_lab_widget($1,$2,$3)",
                    personal_lab_id,
                    str(allowed_origin),
                    uuid4(),
                )
            else:
                if current.allowed_origin != allowed_origin:
                    raise PublicationConflictError
                match current.state:
                    case PublicationState.ENABLED:
                        return current
                    case PublicationState.DISABLED:
                        await _set_state(connection, current.id, "enabled")
                    case PublicationState.REVOKED:
                        raise PublicationConflictError
                    case unreachable:
                        assert_never(unreachable)
            return await _require(connection, personal_lab_id)

    async def disable(self, personal_lab_id: UUID) -> Publication | None:
        """Disable an existing publication idempotently without deleting audit."""
        async with _transaction(self.database_url) as connection:
            await _lock(connection, personal_lab_id)
            current = await _load(connection, personal_lab_id)
            if current is None:
                return None
            match current.state:
                case PublicationState.ENABLED:
                    await _set_state(connection, current.id, "disabled")
                case PublicationState.DISABLED:
                    return current
                case PublicationState.REVOKED:
                    raise PublicationConflictError
                case unreachable:
                    assert_never(unreachable)
            return await _require(connection, personal_lab_id)

    async def rotate(self, personal_lab_id: UUID) -> Publication | None:
        """Atomically rotate an active or disabled publication identifier."""
        async with _transaction(self.database_url) as connection:
            await _lock(connection, personal_lab_id)
            current = await _load(connection, personal_lab_id)
            if current is None:
                return None
            if current.state is PublicationState.REVOKED:
                raise PublicationConflictError
            changed = await connection.fetchval(
                "SELECT private.rotate_personal_lab_widget_key($1,$2)",
                current.id,
                uuid4(),
            )
            if not changed:
                raise PublicationConflictError
            return await _require(connection, personal_lab_id)

    async def revoke(self, personal_lab_id: UUID) -> Publication | None:
        """Rotate then terminally revoke in one transaction with retained audit."""
        async with _transaction(self.database_url) as connection:
            await _lock(connection, personal_lab_id)
            current = await _load(connection, personal_lab_id)
            if current is None:
                return None
            if current.state is PublicationState.REVOKED:
                return current
            rotated = await connection.fetchval(
                "SELECT private.rotate_personal_lab_widget_key($1,$2)",
                current.id,
                uuid4(),
            )
            if not rotated:
                raise PublicationConflictError
            await _set_state(connection, current.id, "revoked")
            return await _require(connection, personal_lab_id)


async def _lock(connection: asyncpg.Connection, personal_lab_id: UUID) -> None:
    await connection.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended($1,0))",
        str(personal_lab_id),
    )


async def _set_state(
    connection: asyncpg.Connection, publication_id: UUID, state: str
) -> None:
    changed = await connection.fetchval(
        "SELECT private.set_personal_lab_widget_state($1,$2)", publication_id, state
    )
    if not changed:
        raise PublicationConflictError


async def _require(
    connection: asyncpg.Connection, personal_lab_id: UUID
) -> Publication:
    publication = await _load(connection, personal_lab_id)
    if publication is None:
        raise PublicationStoreUnavailableError
    return publication


async def _load(
    connection: asyncpg.Connection, personal_lab_id: UUID
) -> Publication | None:
    row = await connection.fetchrow(
        "SELECT id,personal_lab_id,public_key,allowed_origin,state,key_version "
        "FROM public.personal_lab_widget_publications "
        "WHERE personal_lab_id=$1 FOR UPDATE",
        personal_lab_id,
    )
    if row is None:
        return None
    publication_id = UUID(str(row["id"]))
    audit_rows = await connection.fetch(
        "SELECT event_type,key_version,previous_public_key,current_public_key,"
        "recorded_at FROM public.personal_lab_widget_publication_audit "
        "WHERE publication_id=$1 ORDER BY id",
        publication_id,
    )
    audit = tuple(
        PublicationAuditEvent(
            PublicationEventType(str(item["event_type"])),
            int(item["key_version"]),
            None
            if item["previous_public_key"] is None
            else UUID(str(item["previous_public_key"])),
            UUID(str(item["current_public_key"])),
            item["recorded_at"],
        )
        for item in audit_rows
    )
    return Publication(
        publication_id,
        UUID(str(row["personal_lab_id"])),
        UUID(str(row["public_key"])),
        canonicalize_origin(str(row["allowed_origin"])),
        PublicationState(str(row["state"])),
        int(row["key_version"]),
        audit,
    )
