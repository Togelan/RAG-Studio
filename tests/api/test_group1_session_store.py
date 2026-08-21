from __future__ import annotations

import base64
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock
from uuid import UUID

import anyio
import asyncpg
import pytest
from anyio.lowlevel import checkpoint

from src.api.saas_security import BffSessionHandle
from src.api.saas_session_database import (
    SessionDatabase,
    SessionDatabaseLimits,
    SessionDatabaseUnavailableError,
)
from src.api.saas_session_store import (
    PostgresBffSessionStore,
    SessionKeyConfigurationError,
    SessionKeyRing,
    SessionStoreUnavailableError,
)
from src.api.saas_sessions import BffSession

USER_ID = UUID("20000000-0000-4000-8000-000000000001")
ACCOUNT_ID = UUID("cd2c3e18-b111-476f-824d-e24a2443c35a")
WORKSPACE_ID = UUID("10000000-0000-4000-8000-000000000001")
EMAIL = "owner@example.test"


def _encoded_key(fill: int) -> str:
    return base64.urlsafe_b64encode(bytes([fill]) * 32).decode().rstrip("=")


def _key_ring(*entries: tuple[str, int]) -> SessionKeyRing:
    value = ",".join(f"{key_id}:{_encoded_key(fill)}" for key_id, fill in entries)
    return SessionKeyRing.parse(value)


def _database_url() -> str:
    value = os.environ.get("GROUP1_SESSION_DATABASE_URL")
    if value is None:
        pytest.skip("GROUP1_SESSION_DATABASE_URL requires the task-owned Postgres")
    return value


async def _create_session(
    store: PostgresBffSessionStore,
    token_prefix: str,
    *,
    lifetime_seconds: int = 900,
    refresh_lifetime_seconds: int = 3600,
) -> BffSession:
    return await store.create(
        user_id=USER_ID,
        email=EMAIL,
        access_token=f"{token_prefix}-access",
        refresh_token=f"{token_prefix}-refresh",
        lifetime_seconds=lifetime_seconds,
        refresh_lifetime_seconds=refresh_lifetime_seconds,
    )


@asynccontextmanager
async def _connection() -> AsyncIterator[asyncpg.Connection]:
    connection = await asyncpg.connect(_database_url(), timeout=5)
    try:
        yield connection
    finally:
        await connection.close(timeout=5)


@pytest.fixture(autouse=True)
async def clean_sessions() -> AsyncIterator[None]:
    if os.environ.get("GROUP1_SESSION_DATABASE_URL") is None:
        yield
        return
    async with _connection() as connection:
        await connection.execute("DELETE FROM private.bff_sessions")
    yield
    async with _connection() as connection:
        await connection.execute("DELETE FROM private.bff_sessions")


def test_key_ring_rejects_missing_malformed_and_duplicate_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: the mandatory key-ring environment is absent or malformed.
    monkeypatch.delenv("RAG_STUDIO_SESSION_ENCRYPTION_KEYS", raising=False)

    # When/Then: configuration fails before session material can be accepted.
    with pytest.raises(SessionKeyConfigurationError):
        SessionKeyRing.from_environment()
    with pytest.raises(SessionKeyConfigurationError):
        SessionKeyRing.parse("current:not-base64")
    with pytest.raises(SessionKeyConfigurationError):
        SessionKeyRing.parse(f"bad key:{_encoded_key(1)}")
    with pytest.raises(SessionKeyConfigurationError):
        SessionKeyRing.parse(f"current:{_encoded_key(1)},current:{_encoded_key(2)}")


@pytest.mark.asyncio
async def test_database_timeout_cancels_yielded_operation_and_closes_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a connected database whose operation stalls after connection setup.
    connection = AsyncMock()
    monkeypatch.setattr(asyncpg, "connect", AsyncMock(return_value=connection))
    limits = SessionDatabaseLimits(operation_seconds=0.01)
    database = SessionDatabase("postgresql://unused", limits)

    # When/Then: the complete yielded operation is bounded and cleanup still runs.
    with anyio.fail_after(0.2), pytest.raises(SessionDatabaseUnavailableError):
        async with database._connection():
            await anyio.sleep_forever()
    connection.close.assert_awaited_once()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_store_persists_only_digest_and_ciphertext_across_restart() -> None:
    # Given: a current key and one durable Postgres session store.
    database_url = _database_url()
    original_keys = _key_ring(("old", 1))
    store = PostgresBffSessionStore(database_url, original_keys)

    # When: a session and its Account/Workspace selection are persisted.
    created = await _create_session(store, "secret")
    selected_account = await store.select_account(created.handle, ACCOUNT_ID)
    selected = await store.select_workspace(created.handle, WORKSPACE_ID)
    restarted = PostgresBffSessionStore(database_url, original_keys)
    reconstructed = await restarted.get(created.handle)

    # Then: restart reconstruction works and the row contains no browser/token plaintext.
    assert selected_account is not None
    assert selected is not None
    assert reconstructed is not None
    assert reconstructed.email == EMAIL
    assert reconstructed.access_token == "secret-access"
    assert reconstructed.refresh_token == "secret-refresh"
    assert reconstructed.active_account_id == ACCOUNT_ID
    assert reconstructed.active_workspace_id == WORKSPACE_ID
    async with _connection() as connection:
        row = await connection.fetchrow(
            "SELECT session_handle_hmac, access_token_ciphertext, "
            "refresh_token_ciphertext, email_ciphertext, encryption_key_id "
            "FROM private.bff_sessions"
        )
    assert row is not None
    ciphertext_fields = (
        "access_token_ciphertext",
        "refresh_token_ciphertext",
        "email_ciphertext",
    )
    persisted = b"|".join(bytes(row[field]) for field in ciphertext_fields)
    assert str(created.handle) not in str(row["session_handle_hmac"])
    assert b"secret-access" not in persisted
    assert b"secret-refresh" not in persisted
    assert EMAIL.encode() not in persisted
    assert row["encryption_key_id"] == "old"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_rotation_reads_old_key_writes_current_and_denies_replay() -> None:
    # Given: an old-key session and a restarted store with a rotated key ring.
    database_url = _database_url()
    original = PostgresBffSessionStore(database_url, _key_ring(("old", 1)))
    current = await _create_session(original, "old")
    rotated_keys = _key_ring(("current", 2), ("old", 1))
    restarted = PostgresBffSessionStore(database_url, rotated_keys)

    # When: the old row is leased and CAS-rotated after the provider exchange.
    lease = await restarted.begin_refresh(current.handle)
    assert lease is not None
    rotated = await restarted.rotate(
        current.handle,
        lease=lease,
        user_id=USER_ID,
        email=EMAIL,
        access_token="access-new",
        refresh_token="refresh-new",
        lifetime_seconds=900,
        refresh_lifetime_seconds=3600,
    )

    # Then: only the new opaque handle is usable and uses the current write key.
    assert rotated is not None
    assert rotated.handle != current.handle
    assert await restarted.get(current.handle) is None
    assert await restarted.begin_refresh(current.handle) is None
    assert (await restarted.get(rotated.handle)) == rotated
    async with _connection() as connection:
        key_id = await connection.fetchval(
            "SELECT encryption_key_id FROM private.bff_sessions "
            "WHERE revoked_at IS NULL"
        )
    assert key_id == "current"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_two_instances_allow_exactly_one_concurrent_refresh() -> None:
    # Given: two BFF instances sharing the same live session row.
    database_url = _database_url()
    keys = _key_ring(("current", 3))
    first = PostgresBffSessionStore(database_url, keys)
    second = PostgresBffSessionStore(database_url, keys)
    session = await _create_session(first, "concurrent")
    leases = []

    async def claim(store: PostgresBffSessionStore) -> None:
        leases.append(await store.begin_refresh(session.handle))

    # When: both instances race to lease the same refresh token.
    async with anyio.create_task_group() as task_group:
        task_group.start_soon(claim, first)
        task_group.start_soon(claim, second)

    # Then: one caller owns a bounded lease and cancellation recovers after expiry.
    winners = [lease for lease in leases if lease is not None]
    assert len(winners) == 1
    abandoned = winners[0]
    with anyio.CancelScope() as provider_scope:
        provider_scope.cancel()
        await checkpoint()
    async with _connection() as connection:
        await connection.execute(
            "UPDATE private.bff_sessions SET refresh_lease_expires_at="
            "created_at+interval '1 millisecond'"
        )
    recovered = await second.begin_refresh(session.handle)
    assert recovered is not None
    rotated = await first.rotate(
        session.handle,
        lease=recovered,
        user_id=USER_ID,
        email=EMAIL,
        access_token="winner-access",
        refresh_token="winner-refresh",
        lifetime_seconds=900,
        refresh_lifetime_seconds=3600,
    )
    assert rotated is not None
    assert await second.get(session.handle) is None
    assert (
        await second.rotate(
            session.handle,
            lease=abandoned,
            user_id=USER_ID,
            email=EMAIL,
            access_token="loser-access",
            refresh_token="loser-refresh",
            lifetime_seconds=900,
            refresh_lifetime_seconds=3600,
        )
        is None
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_expiry_revoke_wrong_key_cleanup_and_outage_fail_closed() -> None:
    # Given: live, expired, and unreadable sessions.
    database_url = _database_url()
    store = PostgresBffSessionStore(database_url, _key_ring(("current", 4)))
    live = await _create_session(store, "live")
    expired = await _create_session(
        store,
        "expired",
        lifetime_seconds=-2,
        refresh_lifetime_seconds=-1,
    )

    # When: each bounded failure path is exercised.
    wrong_key = PostgresBffSessionStore(database_url, _key_ring(("wrong", 9)))
    revoked = await store.delete(live.handle)
    cleaned = await store.cleanup_expired(limit=1)
    unavailable = PostgresBffSessionStore(
        "postgresql://127.0.0.1:1/unavailable", _key_ring(("current", 4))
    )

    # Then: every failure is closed, sanitized, and cleanup is bounded.
    assert await wrong_key.get(expired.handle) is None
    assert revoked is not None
    assert await store.get(live.handle) is None
    assert await store.get(expired.handle) is None
    assert cleaned == 1
    with pytest.raises(SessionStoreUnavailableError) as failure:
        await unavailable.get(BffSessionHandle("opaque-browser-value"))
    assert str(failure.value) == "Session storage is unavailable."
    assert "127.0.0.1" not in repr(failure.value)
