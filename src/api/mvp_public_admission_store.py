"""PostgreSQL authority for public publication, entitlement, and quota admission."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Literal, assert_never
from uuid import UUID

import anyio
import asyncpg

from src.api.mvp_public_admission import (
    PublicAdmissionStoreUnavailableError,
    PublicAuthoritySnapshot,
    ReservationOutcome,
)
from src.api.mvp_publication import PublicationState
from src.api.mvp_publication_origin import canonicalize_origin


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
        raise PublicAdmissionStoreUnavailableError from None


@dataclass(frozen=True, slots=True)
class PostgresMvpPublicAdmissionStore:
    """Keep public resolution fresh and proof replay/quota admission atomic."""

    database_url: str
    _capacity: anyio.CapacityLimiter = field(
        default_factory=lambda: anyio.CapacityLimiter(10),
        repr=False,
        compare=False,
    )

    async def resolve(self, public_key: UUID) -> PublicAuthoritySnapshot | None:
        """Resolve only public state and server-owned verified entitlement."""
        async with self._capacity, _transaction(self.database_url) as connection:
            row = await connection.fetchrow(
                "SELECT publication.id,publication.key_version,"
                "publication.allowed_origin,publication.state,"
                "COALESCE(billing.entitled,false) AS entitled "
                "FROM public.personal_lab_widget_publications AS publication "
                "LEFT JOIN public.personal_lab_billing_projections AS billing "
                "ON billing.personal_lab_id=publication.personal_lab_id "
                "WHERE publication.public_key=$1",
                public_key,
            )
        if row is None:
            return None
        return PublicAuthoritySnapshot(
            UUID(str(row["id"])),
            int(row["key_version"]),
            canonicalize_origin(str(row["allowed_origin"])),
            PublicationState(str(row["state"])),
            bool(row["entitled"]),
        )

    async def reserve_once(
        self, publication_id: UUID, reservation_id: UUID
    ) -> ReservationOutcome:
        """Atomically reject replay and recheck authority before monthly reserve."""
        async with self._capacity, _transaction(self.database_url) as connection:
            await connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended($1,0))",
                str(reservation_id),
            )
            replay = await connection.fetchval(
                "SELECT EXISTS(SELECT 1 "
                "FROM public.personal_lab_widget_quota_reservations "
                "WHERE reservation_id=$1)",
                reservation_id,
            )
            if replay:
                return ReservationOutcome.REPLAYED
            current = await connection.fetchval(
                "SELECT EXISTS(SELECT 1 "
                "FROM public.personal_lab_widget_publications AS publication "
                "JOIN public.personal_lab_billing_projections AS billing "
                "ON billing.personal_lab_id=publication.personal_lab_id "
                "WHERE publication.id=$1 AND publication.state='enabled' "
                "AND billing.entitled=true)",
                publication_id,
            )
            if not current:
                return ReservationOutcome.STALE_AUTHORITY
            accepted = await connection.fetchval(
                "SELECT private.reserve_personal_lab_widget_message($1,$2)",
                publication_id,
                reservation_id,
            )
        return (
            ReservationOutcome.ACCEPTED
            if bool(accepted)
            else ReservationOutcome.SATURATED
        )

    async def commit(self, reservation_id: UUID) -> bool:
        """Commit one reserved public message exactly once."""
        return await self._finalize("commit", reservation_id)

    async def release(self, reservation_id: UUID) -> bool:
        """Release one canceled or failed public message exactly once."""
        return await self._finalize("release", reservation_id)

    async def _finalize(
        self, operation: Literal["commit", "release"], reservation_id: UUID
    ) -> bool:
        match operation:
            case "commit":
                query = "SELECT private.commit_personal_lab_widget_message($1)"
            case "release":
                query = "SELECT private.release_personal_lab_widget_message($1)"
            case unreachable:
                assert_never(unreachable)
        async with self._capacity, _transaction(self.database_url) as connection:
            changed = await connection.fetchval(query, reservation_id)
        return bool(changed)
