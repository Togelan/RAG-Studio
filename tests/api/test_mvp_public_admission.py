from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import anyio
import pytest

from src.api.mvp_public_admission import (
    AdmissionDenial,
    BurstRateLimiter,
    PublicAdmissionAuthority,
    PublicAdmissionRejected,
    PublicAuthoritySnapshot,
    ReservationOutcome,
)
from src.api.mvp_public_proof import PublicProofSigner
from src.api.mvp_publication import PublicationState
from src.api.mvp_publication_origin import canonicalize_origin

NOW = datetime(2026, 8, 25, 12, 0, tzinfo=UTC)
PUBLICATION = UUID("10000000-0000-4000-8000-000000000001")
KEY = UUID("20000000-0000-4000-8000-000000000002")


class _Store:
    def __init__(
        self,
        snapshot: PublicAuthoritySnapshot | None,
        *,
        next_outcome: ReservationOutcome | None = None,
    ) -> None:
        self.snapshot = snapshot
        self.reservations: dict[UUID, str] = {}
        self.lock = anyio.Lock()
        self.next_outcome = next_outcome

    async def resolve(self, public_key: UUID) -> PublicAuthoritySnapshot | None:
        return self.snapshot if public_key == KEY else None

    async def reserve_once(
        self, publication_id: UUID, reservation_id: UUID
    ) -> ReservationOutcome:
        async with self.lock:
            if self.next_outcome is not None:
                return self.next_outcome
            if publication_id != PUBLICATION or reservation_id in self.reservations:
                return ReservationOutcome.REPLAYED
            self.reservations[reservation_id] = "reserved"
            return ReservationOutcome.ACCEPTED

    async def commit(self, reservation_id: UUID) -> bool:
        if self.reservations.get(reservation_id) != "reserved":
            return False
        self.reservations[reservation_id] = "committed"
        return True

    async def release(self, reservation_id: UUID) -> bool:
        if self.reservations.get(reservation_id) != "reserved":
            return False
        self.reservations[reservation_id] = "released"
        return True


def _snapshot(
    *, state: PublicationState = PublicationState.ENABLED, entitled: bool = True
) -> PublicAuthoritySnapshot:
    return PublicAuthoritySnapshot(
        PUBLICATION,
        3,
        canonicalize_origin("https://widget.example.test"),
        state,
        entitled,
    )


def _authority(store: _Store, *, enabled: bool = True) -> PublicAdmissionAuthority:
    return PublicAdmissionAuthority(
        enabled,
        store,
        PublicProofSigner(b"proof-key-material-that-is-at-least-32"),
        BurstRateLimiter(limit=2, window_seconds=60, capacity=4),
    )


@pytest.mark.anyio
async def test_one_time_proof_reserves_once_and_replay_is_denied() -> None:
    store = _Store(_snapshot())
    authority = _authority(store)
    bootstrap = await authority.issue(KEY, "https://widget.example.test", NOW)

    admission = await authority.admit(
        KEY, "https://widget.example.test", bootstrap.proof, "198.51.100.1", NOW
    )
    with pytest.raises(PublicAdmissionRejected) as replay:
        await authority.admit(
            KEY, "https://widget.example.test", bootstrap.proof, "198.51.100.1", NOW
        )

    assert admission.session_id == bootstrap.session_id
    assert replay.value.reason is AdmissionDenial.REPLAYED_PROOF
    assert store.reservations == {admission.reservation_id: "reserved"}


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("enabled", "snapshot", "origin", "reason"),
    (
        (
            False,
            _snapshot(),
            "https://widget.example.test",
            AdmissionDenial.FEATURE_DISABLED,
        ),
        (True, None, "https://widget.example.test", AdmissionDenial.NOT_FOUND),
        (
            True,
            _snapshot(state=PublicationState.DISABLED),
            "https://widget.example.test",
            AdmissionDenial.DISABLED,
        ),
        (
            True,
            _snapshot(state=PublicationState.REVOKED),
            "https://widget.example.test",
            AdmissionDenial.REVOKED,
        ),
        (True, _snapshot(), "https://attacker.example.test", AdmissionDenial.ORIGIN),
        (
            True,
            _snapshot(entitled=False),
            "https://widget.example.test",
            AdmissionDenial.NOT_ENTITLED,
        ),
    ),
)
async def test_bootstrap_rejects_before_issuing_proof(
    enabled: bool,
    snapshot: PublicAuthoritySnapshot | None,
    origin: str,
    reason: AdmissionDenial,
) -> None:
    store = _Store(snapshot)

    with pytest.raises(PublicAdmissionRejected) as rejected:
        await _authority(store, enabled=enabled).issue(KEY, origin, NOW)

    assert rejected.value.reason is reason
    assert store.reservations == {}


@pytest.mark.anyio
async def test_burst_limit_isolated_by_publication_and_ip_and_resets() -> None:
    limiter = BurstRateLimiter(limit=2, window_seconds=60, capacity=4)
    other = UUID("30000000-0000-4000-8000-000000000003")

    assert (await limiter.admit(PUBLICATION, "198.51.100.1", 100)).allowed
    assert (await limiter.admit(PUBLICATION, "198.51.100.1", 101)).allowed
    denied = await limiter.admit(PUBLICATION, "198.51.100.1", 102)
    isolated_ip = await limiter.admit(PUBLICATION, "198.51.100.2", 102)
    isolated_publication = await limiter.admit(other, "198.51.100.1", 102)
    reset = await limiter.admit(PUBLICATION, "198.51.100.1", 160)

    assert not denied.allowed and denied.retry_after == 58
    assert isolated_ip.allowed and isolated_publication.allowed and reset.allowed


@pytest.mark.anyio
async def test_release_and_commit_are_public_reservation_only() -> None:
    store = _Store(_snapshot())
    authority = _authority(store)
    first = await authority.issue(KEY, "https://widget.example.test", NOW)
    admitted = await authority.admit(
        KEY, "https://widget.example.test", first.proof, "198.51.100.1", NOW
    )

    assert await authority.release(admitted.reservation_id)
    assert not await authority.commit(admitted.reservation_id)
    assert store.reservations[admitted.reservation_id] == "released"
    assert str(admitted.session_id) not in str(store.reservations)


@pytest.mark.anyio
async def test_concurrent_proof_replay_has_exactly_one_durable_winner() -> None:
    store = _Store(_snapshot())
    authority = _authority(store)
    bootstrap = await authority.issue(KEY, "https://widget.example.test", NOW)
    outcomes: list[str] = []

    async def attempt(ip: str) -> None:
        try:
            await authority.admit(
                KEY, "https://widget.example.test", bootstrap.proof, ip, NOW
            )
            outcomes.append("accepted")
        except PublicAdmissionRejected as rejected:
            outcomes.append(rejected.reason.value)

    async with anyio.create_task_group() as tasks:
        tasks.start_soon(attempt, "198.51.100.1")
        tasks.start_soon(attempt, "198.51.100.2")

    assert sorted(outcomes) == ["accepted", "replayed_proof"]
    assert len(store.reservations) == 1


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("outcome", "reason"),
    (
        (ReservationOutcome.SATURATED, AdmissionDenial.QUOTA_EXHAUSTED),
        (ReservationOutcome.STALE_AUTHORITY, AdmissionDenial.STALE_AUTHORITY),
    ),
)
async def test_durable_quota_and_stale_recheck_fail_without_admission(
    outcome: ReservationOutcome, reason: AdmissionDenial
) -> None:
    store = _Store(_snapshot(), next_outcome=outcome)
    authority = _authority(store)
    bootstrap = await authority.issue(KEY, "https://widget.example.test", NOW)

    with pytest.raises(PublicAdmissionRejected) as rejected:
        await authority.admit(
            KEY, "https://widget.example.test", bootstrap.proof, "198.51.100.1", NOW
        )

    assert rejected.value.reason is reason
    assert store.reservations == {}
