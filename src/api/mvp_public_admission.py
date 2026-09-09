"""Fail-closed public widget admission without graph or retrieval authority."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol, assert_never
from uuid import UUID

from src.api.mvp_public_proof import (
    ProofInvalidError,
    PublicProofSigner,
    VerifiedPublicProof,
)
from src.api.mvp_public_rate_limit import BurstRateLimiter
from src.api.mvp_publication import PublicationState
from src.api.mvp_publication_origin import (
    CanonicalOrigin,
    OriginRejectedError,
    canonicalize_origin,
)

__all__ = ("BurstRateLimiter",)


class AdmissionDenial(StrEnum):
    """Sanitized public admission denials."""

    FEATURE_DISABLED = "feature_disabled"
    NOT_FOUND = "not_found"
    DISABLED = "disabled"
    REVOKED = "revoked"
    ORIGIN = "origin"
    NOT_ENTITLED = "not_entitled"
    INVALID_PROOF = "invalid_proof"
    REPLAYED_PROOF = "replayed_proof"
    RATE_LIMITED = "rate_limited"
    QUOTA_EXHAUSTED = "quota_exhausted"
    STALE_AUTHORITY = "stale_authority"


class ReservationOutcome(StrEnum):
    """Atomic durable quota reservation outcomes."""

    ACCEPTED = "accepted"
    REPLAYED = "replayed"
    SATURATED = "saturated"
    STALE_AUTHORITY = "stale_authority"


class PublicAdmissionRejected(Exception):
    """Bounded rejection safe to translate at the public HTTP boundary."""

    def __init__(
        self,
        reason: AdmissionDenial,
        retry_after: int | None = None,
        cors_origin: str | None = None,
    ) -> None:
        super().__init__(reason.value)
        self.reason = reason
        self.retry_after = retry_after
        self.cors_origin = cors_origin


class PublicAdmissionStoreUnavailableError(Exception):
    """Sanitized durable failure with optional already-authorized Origin."""

    def __init__(self, cors_origin: str | None = None) -> None:
        super().__init__()
        self.cors_origin = cors_origin


@dataclass(frozen=True, slots=True)
class PublicAuthoritySnapshot:
    """Fresh public state without Personal Lab, collection, or credentials."""

    publication_id: UUID
    key_version: int
    allowed_origin: CanonicalOrigin
    state: PublicationState
    entitled: bool


class PublicAdmissionStore(Protocol):
    """Durable publication, entitlement, and quota capabilities."""

    async def resolve(self, public_key: UUID) -> PublicAuthoritySnapshot | None: ...

    async def reserve_once(
        self, publication_id: UUID, reservation_id: UUID
    ) -> ReservationOutcome: ...

    async def commit(self, reservation_id: UUID) -> bool: ...

    async def release(self, reservation_id: UUID) -> bool: ...


@dataclass(frozen=True, slots=True)
class PublicBootstrap:
    """Anonymous non-persistent session proof response."""

    proof: str
    session_id: UUID
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class PublicAdmission:
    """Verified public-only reservation passed to the later execution adapter."""

    publication_id: UUID
    session_id: UUID
    reservation_id: UUID


@dataclass(frozen=True, slots=True)
class PublicAdmissionAuthority:
    """Order all public checks before exposing an execution reservation."""

    feature_enabled: bool
    store: PublicAdmissionStore
    proofs: PublicProofSigner
    burst: BurstRateLimiter

    async def issue(
        self, public_key: UUID, raw_origin: str | None, now: datetime
    ) -> PublicBootstrap:
        """Issue a short-lived proof only for current entitled authority."""
        snapshot, origin = await self._authorize(public_key, raw_origin)
        proof = self.proofs.issue(
            snapshot.publication_id, snapshot.key_version, str(origin), now
        )
        verified = self.proofs.verify(
            proof,
            snapshot.publication_id,
            snapshot.key_version,
            str(origin),
            now,
        )
        return PublicBootstrap(proof, verified.session_id, verified.expires_at)

    async def admit(
        self,
        public_key: UUID,
        raw_origin: str | None,
        proof: str,
        client_ip: str,
        now: datetime,
    ) -> PublicAdmission:
        """Verify one proof, burst slot, and durable monthly reservation."""
        snapshot, origin = await self._authorize(public_key, raw_origin)
        verified = self._verify_proof(snapshot, origin, proof, now)
        burst = await self.burst.admit(
            snapshot.publication_id, client_ip, now.timestamp()
        )
        if not burst.allowed:
            raise PublicAdmissionRejected(
                AdmissionDenial.RATE_LIMITED, burst.retry_after, str(origin)
            )
        try:
            outcome = await self.store.reserve_once(
                snapshot.publication_id, verified.reservation_id
            )
        except PublicAdmissionStoreUnavailableError:
            raise PublicAdmissionStoreUnavailableError(str(origin)) from None
        match outcome:
            case ReservationOutcome.ACCEPTED:
                return PublicAdmission(
                    snapshot.publication_id,
                    verified.session_id,
                    verified.reservation_id,
                )
            case ReservationOutcome.REPLAYED:
                denial = AdmissionDenial.REPLAYED_PROOF
            case ReservationOutcome.SATURATED:
                denial = AdmissionDenial.QUOTA_EXHAUSTED
            case ReservationOutcome.STALE_AUTHORITY:
                denial = AdmissionDenial.STALE_AUTHORITY
            case unreachable:
                assert_never(unreachable)
        raise PublicAdmissionRejected(denial, cors_origin=str(origin))

    async def verify(
        self,
        public_key: UUID,
        raw_origin: str | None,
        proof: str,
        now: datetime,
    ) -> PublicAdmission:
        """Recheck a proof for public-only cancellation without reserving quota."""
        snapshot, origin = await self._authorize(public_key, raw_origin)
        verified = self._verify_proof(snapshot, origin, proof, now)
        return PublicAdmission(
            snapshot.publication_id,
            verified.session_id,
            verified.reservation_id,
        )

    async def commit(self, reservation_id: UUID) -> bool:
        """Commit a successful terminal public response exactly once."""
        return await self.store.commit(reservation_id)

    async def release(self, reservation_id: UUID) -> bool:
        """Release a canceled or failed public response exactly once."""
        return await self.store.release(reservation_id)

    async def _authorize(
        self, public_key: UUID, raw_origin: str | None
    ) -> tuple[PublicAuthoritySnapshot, CanonicalOrigin]:
        if not self.feature_enabled:
            raise PublicAdmissionRejected(AdmissionDenial.FEATURE_DISABLED)
        snapshot = await self.store.resolve(public_key)
        if snapshot is None:
            raise PublicAdmissionRejected(AdmissionDenial.NOT_FOUND)
        match snapshot.state:
            case PublicationState.DISABLED:
                raise PublicAdmissionRejected(AdmissionDenial.DISABLED)
            case PublicationState.REVOKED:
                raise PublicAdmissionRejected(AdmissionDenial.REVOKED)
            case PublicationState.ENABLED:
                pass
            case unreachable:
                assert_never(unreachable)
        try:
            origin = canonicalize_origin(raw_origin)
        except OriginRejectedError:
            raise PublicAdmissionRejected(AdmissionDenial.ORIGIN) from None
        if origin != snapshot.allowed_origin:
            raise PublicAdmissionRejected(AdmissionDenial.ORIGIN)
        if not snapshot.entitled:
            raise PublicAdmissionRejected(
                AdmissionDenial.NOT_ENTITLED, cors_origin=str(origin)
            )
        return snapshot, origin

    def _verify_proof(
        self,
        snapshot: PublicAuthoritySnapshot,
        origin: CanonicalOrigin,
        proof: str,
        now: datetime,
    ) -> VerifiedPublicProof:
        try:
            return self.proofs.verify(
                proof,
                snapshot.publication_id,
                snapshot.key_version,
                str(origin),
                now,
            )
        except ProofInvalidError:
            raise PublicAdmissionRejected(
                AdmissionDenial.INVALID_PROOF, cors_origin=str(origin)
            ) from None
