"""Bounded Postgres primitives for durable BFF session rows."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

import anyio
import asyncpg


class SessionDatabaseUnavailableError(RuntimeError):
    """The session database could not complete bounded I/O."""


@dataclass(frozen=True, slots=True)
class SessionDatabaseLimits:
    """Bounded connection, cleanup, and lease durations."""

    operation_seconds: float = 5.0
    close_seconds: float = 5.0
    refresh_lease_seconds: float = 15.0


DEFAULT_SESSION_DATABASE_LIMITS = SessionDatabaseLimits()


@dataclass(frozen=True, slots=True)
class EncryptedSessionWrite:
    """One complete encrypted session row ready for persistence."""

    row_id: UUID
    user_id: UUID
    handle_hmac: str
    access_ciphertext: bytes
    refresh_ciphertext: bytes
    email_ciphertext: bytes
    key_id: str
    access_expires_at: datetime
    refresh_expires_at: datetime
    rotation_version: int
    active_account_id: UUID | None
    active_workspace_id: UUID | None


@dataclass(frozen=True, slots=True)
class RefreshCas:
    """Database predicates required for one refresh rotation."""

    handle_digests: Sequence[str]
    lease_id: UUID
    rotation_version: int


class SessionDatabase:
    """Short-transaction adapter for the private session table."""

    def __init__(
        self,
        database_url: str,
        limits: SessionDatabaseLimits = DEFAULT_SESSION_DATABASE_LIMITS,
    ) -> None:
        self._database_url = database_url
        self.limits = limits

    async def insert(self, write: EncryptedSessionWrite) -> None:
        """Insert one encrypted session row."""
        async with self._connection() as connection:
            await self._insert(connection, write)

    async def fetch_live(self, digests: Sequence[str]) -> asyncpg.Record | None:
        """Fetch one live row by any key-ring-derived digest."""
        async with self._connection() as connection:
            return await connection.fetchrow(
                "SELECT * FROM private.bff_sessions WHERE revoked_at IS NULL "
                "AND refresh_token_expires_at>now() "
                "AND session_handle_hmac=ANY($1::text[])",
                digests,
            )

    async def touch(self, row_id: UUID) -> None:
        """Persist last use without extending token expiry."""
        async with self._connection() as connection:
            await connection.execute(
                "UPDATE private.bff_sessions SET last_used_at=now() WHERE id=$1",
                row_id,
            )

    async def claim_refresh(
        self, digests: Sequence[str], lease_id: UUID
    ) -> asyncpg.Record | None:
        """Atomically claim one expired-or-absent refresh lease."""
        async with self._connection() as connection:
            return await connection.fetchrow(
                "UPDATE private.bff_sessions SET refresh_lease_id=$2,"
                "refresh_lease_expires_at=now()+($3::double precision*interval '1 second') "
                "WHERE session_handle_hmac=ANY($1::text[]) AND revoked_at IS NULL "
                "AND refresh_token_expires_at>now() AND (refresh_lease_id IS NULL "
                "OR refresh_lease_expires_at<=now()) RETURNING *",
                digests,
                lease_id,
                self.limits.refresh_lease_seconds,
            )

    async def rotate(self, cas: RefreshCas, write: EncryptedSessionWrite) -> bool:
        """CAS-revoke the leased row and insert its replacement atomically."""
        async with self._connection() as connection, connection.transaction():
            revoked_id = await connection.fetchval(
                "UPDATE private.bff_sessions SET revoked_at=now(),rotated_at=now(),"
                "refresh_lease_id=NULL,refresh_lease_expires_at=NULL "
                "WHERE session_handle_hmac=ANY($1::text[]) AND revoked_at IS NULL "
                "AND refresh_token_expires_at>now() AND refresh_lease_id=$2 "
                "AND refresh_lease_expires_at>now() AND rotation_version=$3 "
                "RETURNING id",
                cas.handle_digests,
                cas.lease_id,
                cas.rotation_version,
            )
            if revoked_id is None:
                return False
            await self._insert(connection, write)
            return True

    async def update_selection(
        self,
        digests: Sequence[str],
        account_id: UUID | None,
        workspace_id: UUID | None,
        *,
        replace_account: bool,
    ) -> asyncpg.Record | None:
        """Persist one validated Account or Workspace selection."""
        async with self._connection() as connection:
            if replace_account:
                return await connection.fetchrow(
                    "UPDATE private.bff_sessions SET active_account_id=$2,"
                    "active_workspace_id=NULL,last_used_at=now() "
                    "WHERE session_handle_hmac=ANY($1::text[]) AND revoked_at IS NULL "
                    "AND refresh_token_expires_at>now() RETURNING *",
                    digests,
                    account_id,
                )
            return await connection.fetchrow(
                "UPDATE private.bff_sessions SET active_workspace_id=$2,last_used_at=now() "
                "WHERE session_handle_hmac=ANY($1::text[]) AND revoked_at IS NULL "
                "AND refresh_token_expires_at>now() RETURNING *",
                digests,
                workspace_id,
            )

    async def revoke(self, digests: Sequence[str]) -> asyncpg.Record | None:
        """Revoke one current row and return its encrypted prior state."""
        async with self._connection() as connection:
            return await connection.fetchrow(
                "UPDATE private.bff_sessions SET revoked_at=now(),refresh_lease_id=NULL,"
                "refresh_lease_expires_at=NULL WHERE session_handle_hmac=ANY($1::text[]) "
                "AND revoked_at IS NULL RETURNING *",
                digests,
            )

    async def revoke_row(self, row_id: UUID) -> None:
        """Fail closed when ciphertext cannot be authenticated."""
        async with self._connection() as connection:
            await connection.execute(
                "UPDATE private.bff_sessions SET revoked_at=now(),refresh_lease_id=NULL,"
                "refresh_lease_expires_at=NULL WHERE id=$1 AND revoked_at IS NULL",
                row_id,
            )

    async def cleanup(self, limit: int) -> int:
        """Delete at most ``limit`` expired or revoked rows."""
        async with self._connection() as connection:
            rows = await connection.fetch(
                "DELETE FROM private.bff_sessions WHERE id IN "
                "(SELECT id FROM private.bff_sessions WHERE refresh_token_expires_at<=now() "
                "OR revoked_at IS NOT NULL ORDER BY refresh_token_expires_at,id LIMIT $1) "
                "RETURNING id",
                limit,
            )
            return len(rows)

    @staticmethod
    async def _insert(
        connection: asyncpg.Connection, write: EncryptedSessionWrite
    ) -> None:
        await connection.execute(
            "INSERT INTO private.bff_sessions "
            "(id,user_id,session_handle_hmac,access_token_ciphertext,"
            "refresh_token_ciphertext,email_ciphertext,encryption_key_id,"
            "access_token_expires_at,refresh_token_expires_at,rotation_version,"
            "active_account_id,active_workspace_id) "
            "VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)",
            write.row_id,
            write.user_id,
            write.handle_hmac,
            write.access_ciphertext,
            write.refresh_ciphertext,
            write.email_ciphertext,
            write.key_id,
            write.access_expires_at,
            write.refresh_expires_at,
            write.rotation_version,
            write.active_account_id,
            write.active_workspace_id,
        )

    @asynccontextmanager
    async def _connection(self) -> AsyncIterator[asyncpg.Connection]:
        connection: asyncpg.Connection | None = None
        try:
            with anyio.fail_after(self.limits.operation_seconds):
                connection = await asyncpg.connect(
                    self._database_url, timeout=self.limits.operation_seconds
                )
                yield connection
        except asyncpg.PostgresError, OSError, TimeoutError:
            raise SessionDatabaseUnavailableError from None
        finally:
            if connection is not None:
                with anyio.move_on_after(self.limits.close_seconds, shield=True):
                    await connection.close(timeout=self.limits.close_seconds)
