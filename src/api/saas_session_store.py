"""Encrypted durable storage for server-owned browser sessions."""

from __future__ import annotations

import secrets
from collections.abc import Awaitable
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import asyncpg
from cryptography.exceptions import InvalidTag

from src.api.saas_security import BffSessionHandle
from src.api.saas_session_crypto import (
    SessionKey,
    SessionKeyConfigurationError,
    SessionKeyRing,
    decrypt_session_value,
    encrypt_session_value,
    session_handle_digest,
)
from src.api.saas_session_database import (
    DEFAULT_SESSION_DATABASE_LIMITS,
    EncryptedSessionWrite,
    RefreshCas,
    SessionDatabase,
    SessionDatabaseLimits,
    SessionDatabaseUnavailableError,
)
from src.api.saas_sessions import BffSession, BffSessionStore, SessionRefreshLease

__all__ = (
    "PostgresBffSessionStore",
    "SessionKeyConfigurationError",
    "SessionKeyRing",
    "SessionStoreUnavailableError",
)


class SessionStoreUnavailableError(RuntimeError):
    """The durable session authority could not complete bounded I/O."""

    def __str__(self) -> str:
        return "Session storage is unavailable."


class PostgresBffSessionStore(BffSessionStore):
    """Postgres session repository with AEAD fields and CAS rotation."""

    def __init__(
        self,
        database_url: str,
        key_ring: SessionKeyRing,
        limits: SessionDatabaseLimits = DEFAULT_SESSION_DATABASE_LIMITS,
    ) -> None:
        self._database = SessionDatabase(database_url, limits)
        self._key_ring = key_ring

    async def create(
        self,
        *,
        user_id: UUID,
        email: str,
        access_token: str,
        refresh_token: str,
        lifetime_seconds: int,
        refresh_lifetime_seconds: int | None = None,
    ) -> BffSession:
        """Persist a new session while returning only its opaque handle."""
        now = datetime.now(UTC)
        refresh_lifetime = refresh_lifetime_seconds or lifetime_seconds
        session = BffSession(
            handle=BffSessionHandle(secrets.token_urlsafe(32)),
            user_id=user_id,
            email=email,
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at=(now + timedelta(seconds=lifetime_seconds)).timestamp(),
            refresh_expires_at=(now + timedelta(seconds=refresh_lifetime)).timestamp(),
        )
        await self._run(self._database.insert(self._encrypted_write(session)))
        return session

    async def get(self, handle: BffSessionHandle) -> BffSession | None:
        """Reconstruct one live session without extending either expiry."""
        row = await self._run(self._database.fetch_live(self._digests(handle)))
        session = self._decode(row, handle)
        if row is not None and session is None:
            await self._run(self._database.revoke_row(row["id"]))
        elif row is not None:
            await self._run(self._database.touch(row["id"]))
        return session

    async def begin_refresh(
        self, handle: BffSessionHandle
    ) -> SessionRefreshLease | None:
        """Atomically claim a short lease before the provider call."""
        lease_id = uuid4()
        row = await self._run(
            self._database.claim_refresh(self._digests(handle), lease_id)
        )
        session = self._decode(row, handle)
        if row is not None and session is None:
            await self._run(self._database.revoke_row(row["id"]))
            return None
        if session is None:
            return None
        return SessionRefreshLease(session, lease_id, session.rotation_version)

    async def rotate(
        self,
        old_handle: BffSessionHandle,
        *,
        user_id: UUID,
        email: str,
        access_token: str,
        refresh_token: str,
        lifetime_seconds: int,
        refresh_lifetime_seconds: int | None = None,
        lease: SessionRefreshLease | None = None,
    ) -> BffSession | None:
        """CAS-revoke one leased version and insert its replacement."""
        claimed = lease or await self.begin_refresh(old_handle)
        if claimed is None or claimed.session.user_id != user_id:
            return None
        now = datetime.now(UTC)
        refresh_lifetime = refresh_lifetime_seconds or lifetime_seconds
        replacement = BffSession(
            handle=BffSessionHandle(secrets.token_urlsafe(32)),
            user_id=user_id,
            email=email,
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at=(now + timedelta(seconds=lifetime_seconds)).timestamp(),
            refresh_expires_at=(now + timedelta(seconds=refresh_lifetime)).timestamp(),
            rotation_version=claimed.rotation_version + 1,
            active_account_id=claimed.session.active_account_id,
            active_workspace_id=claimed.session.active_workspace_id,
        )
        cas = RefreshCas(
            self._digests(old_handle), claimed.lease_id, claimed.rotation_version
        )
        rotated = await self._run(
            self._database.rotate(cas, self._encrypted_write(replacement))
        )
        return replacement if rotated else None

    async def select_account(
        self, handle: BffSessionHandle, account_id: UUID | None
    ) -> BffSession | None:
        """Persist Account selection and clear stale Workspace selection."""
        row = await self._run(
            self._database.update_selection(
                self._digests(handle), account_id, None, replace_account=True
            )
        )
        return self._decode(row, handle)

    async def select_workspace(
        self, handle: BffSessionHandle, workspace_id: UUID | None
    ) -> BffSession | None:
        """Persist a Workspace selection inside the selected Account."""
        row = await self._run(
            self._database.update_selection(
                self._digests(handle), None, workspace_id, replace_account=False
            )
        )
        return self._decode(row, handle)

    async def delete(self, handle: BffSessionHandle) -> BffSession | None:
        """Revoke the current durable session without deleting audit state."""
        row = await self._run(self._database.revoke(self._digests(handle)))
        return self._decode(row, handle)

    async def cleanup_expired(self, *, limit: int = 100) -> int:
        """Delete at most ``limit`` unusable rows ordered by expiry."""
        if limit < 1:
            return 0
        return await self._run(self._database.cleanup(limit))

    def _encrypted_write(self, session: BffSession) -> EncryptedSessionWrite:
        row_id = uuid4()
        key = self._key_ring.current
        return EncryptedSessionWrite(
            row_id=row_id,
            user_id=session.user_id,
            handle_hmac=session_handle_digest(session.handle, key),
            access_ciphertext=encrypt_session_value(
                row_id, "access", session.access_token, key
            ),
            refresh_ciphertext=encrypt_session_value(
                row_id, "refresh", session.refresh_token, key
            ),
            email_ciphertext=encrypt_session_value(row_id, "email", session.email, key),
            key_id=key.key_id,
            access_expires_at=datetime.fromtimestamp(session.expires_at, UTC),
            refresh_expires_at=datetime.fromtimestamp(session.refresh_expires_at, UTC),
            rotation_version=session.rotation_version,
            active_account_id=session.active_account_id,
            active_workspace_id=session.active_workspace_id,
        )

    def _decode(
        self, row: asyncpg.Record | None, handle: BffSessionHandle
    ) -> BffSession | None:
        if row is None:
            return None
        key = self._key_ring.by_id(row["encryption_key_id"])
        if key is None:
            return None
        try:
            return BffSession(
                handle=handle,
                user_id=row["user_id"],
                email=self._decrypt(row, "email", key),
                access_token=self._decrypt(row, "access", key),
                refresh_token=self._decrypt(row, "refresh", key),
                expires_at=row["access_token_expires_at"].timestamp(),
                refresh_expires_at=row["refresh_token_expires_at"].timestamp(),
                rotation_version=row["rotation_version"],
                active_account_id=row["active_account_id"],
                active_workspace_id=row["active_workspace_id"],
            )
        except InvalidTag, UnicodeDecodeError:
            return None

    def _decrypt(self, row: asyncpg.Record, field: str, key: SessionKey) -> str:
        column = "email_ciphertext" if field == "email" else f"{field}_token_ciphertext"
        return decrypt_session_value(row["id"], field, bytes(row[column]), key)

    def _digests(self, handle: BffSessionHandle) -> tuple[str, ...]:
        return tuple(session_handle_digest(handle, key) for key in self._key_ring.keys)

    @staticmethod
    async def _run[T](operation: Awaitable[T]) -> T:
        try:
            return await operation
        except SessionDatabaseUnavailableError:
            raise SessionStoreUnavailableError from None
