from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.mvp_public_admission import (
    BurstRateLimiter,
    PublicAdmissionAuthority,
    PublicAdmissionStoreUnavailableError,
    PublicAuthoritySnapshot,
    ReservationOutcome,
)
from src.api.mvp_public_proof import PublicProofSigner
from src.api.mvp_publication import PublicationState
from src.api.mvp_publication_origin import canonicalize_origin
from src.api.public_cors import PartitionedCORSMiddleware
from src.api.routes.mvp_public import create_mvp_public_router

NOW = datetime(2026, 8, 25, 12, 0, tzinfo=UTC)
PUBLICATION = UUID("10000000-0000-4000-8000-000000000001")
KEY = UUID("20000000-0000-4000-8000-000000000002")
ORIGIN = "https://widget.example.test"


class _Store:
    def __init__(self) -> None:
        self.state = PublicationState.ENABLED
        self.entitled = True
        self.reservations: dict[UUID, str] = {}
        self.next_outcome: ReservationOutcome | None = None
        self.fail_reservation = False

    async def resolve(self, public_key: UUID) -> PublicAuthoritySnapshot | None:
        if public_key != KEY:
            return None
        return PublicAuthoritySnapshot(
            PUBLICATION, 1, canonicalize_origin(ORIGIN), self.state, self.entitled
        )

    async def reserve_once(
        self, publication_id: UUID, reservation_id: UUID
    ) -> ReservationOutcome:
        if self.fail_reservation:
            raise PublicAdmissionStoreUnavailableError
        if self.next_outcome is not None:
            return self.next_outcome
        if reservation_id in self.reservations:
            return ReservationOutcome.REPLAYED
        self.reservations[reservation_id] = "reserved"
        return ReservationOutcome.ACCEPTED

    async def commit(self, reservation_id: UUID) -> bool:
        return reservation_id in self.reservations

    async def release(self, reservation_id: UUID) -> bool:
        return reservation_id in self.reservations


def _fixture(*, limit: int = 2) -> tuple[TestClient, _Store]:
    store = _Store()
    authority = PublicAdmissionAuthority(
        True,
        store,
        PublicProofSigner(b"proof-key-material-that-is-at-least-32"),
        BurstRateLimiter(limit=limit, window_seconds=60, capacity=10),
    )
    app = FastAPI()
    app.add_middleware(
        PartitionedCORSMiddleware,
        allow_origins=("https://attacker.example.test",),
        allow_methods=("POST",),
        allow_headers=("Content-Type",),
    )
    app.include_router(create_mvp_public_router(authority, clock=lambda: NOW))
    return TestClient(app), store


def test_exact_preflight_and_proof_cors_only_echo_configured_origin() -> None:
    client, _ = _fixture()
    with client:
        allowed = client.options(
            f"/api/public/widgets/{KEY}/proof",
            headers={"Origin": ORIGIN, "Access-Control-Request-Method": "POST"},
        )
        hostile = client.options(
            f"/api/public/widgets/{KEY}/admissions",
            headers={
                "Origin": "https://attacker.example.test",
                "Access-Control-Request-Method": "POST",
            },
        )
        missing = client.post(f"/api/public/widgets/{KEY}/proof", json={})
        issued = client.post(
            f"/api/public/widgets/{KEY}/proof", json={}, headers={"Origin": ORIGIN}
        )

    assert allowed.status_code == 204
    assert allowed.headers["access-control-allow-origin"] == ORIGIN
    assert allowed.headers["access-control-allow-methods"] == "POST, OPTIONS"
    assert (
        hostile.status_code == 403
        and "access-control-allow-origin" not in hostile.headers
    )
    assert (
        missing.status_code == 403
        and "access-control-allow-origin" not in missing.headers
    )
    assert issued.status_code == 200
    assert issued.headers["access-control-allow-origin"] == ORIGIN


def test_admission_rejects_bad_payload_proof_replay_and_burst_with_no_private_state() -> (
    None
):
    client, store = _fixture(limit=2)
    with client:
        issued = client.post(
            f"/api/public/widgets/{KEY}/proof", json={}, headers={"Origin": ORIGIN}
        ).json()
        forged_scope = client.post(
            f"/api/public/widgets/{KEY}/admissions",
            json={
                "proof": issued["proof"],
                "message": "hello",
                "personal_lab_id": str(UUID(int=99)),
            },
            headers={"Origin": ORIGIN},
        )
        first = client.post(
            f"/api/public/widgets/{KEY}/admissions",
            json={"proof": issued["proof"], "message": "hello"},
            headers={"Origin": ORIGIN},
        )
        replay = client.post(
            f"/api/public/widgets/{KEY}/admissions",
            json={"proof": issued["proof"], "message": "hello"},
            headers={"Origin": ORIGIN},
        )

    assert forged_scope.status_code == 422 and store.reservations == {
        UUID(first.json()["reservation_id"]): "reserved"
    }
    assert first.status_code == 201
    assert set(first.json()) == {"session_id", "reservation_id"}
    assert replay.status_code == 401
    assert "proof" not in replay.text.lower()


def test_disabled_and_no_entitlement_fail_before_reservation() -> None:
    client, store = _fixture()
    store.state = PublicationState.DISABLED
    with client:
        disabled = client.post(
            f"/api/public/widgets/{KEY}/proof", json={}, headers={"Origin": ORIGIN}
        )
        store.state = PublicationState.ENABLED
        store.entitled = False
        no_entitlement = client.post(
            f"/api/public/widgets/{KEY}/proof", json={}, headers={"Origin": ORIGIN}
        )

    assert disabled.status_code == no_entitlement.status_code == 403
    assert store.reservations == {}


def test_burst_excess_returns_deterministic_429_and_retry_after() -> None:
    client, store = _fixture(limit=1)
    with client:
        first_proof = client.post(
            f"/api/public/widgets/{KEY}/proof", json={}, headers={"Origin": ORIGIN}
        ).json()["proof"]
        second_proof = client.post(
            f"/api/public/widgets/{KEY}/proof", json={}, headers={"Origin": ORIGIN}
        ).json()["proof"]
        first = client.post(
            f"/api/public/widgets/{KEY}/admissions",
            json={"proof": first_proof, "message": "one"},
            headers={"Origin": ORIGIN},
        )
        limited = client.post(
            f"/api/public/widgets/{KEY}/admissions",
            json={"proof": second_proof, "message": "two"},
            headers={"Origin": ORIGIN},
        )

    assert first.status_code == 201
    assert limited.status_code == 429
    assert limited.headers["retry-after"] == "60"
    assert limited.headers["access-control-allow-origin"] == ORIGIN
    assert len(store.reservations) == 1


def test_monthly_quota_exhaustion_returns_429_until_next_utc_month() -> None:
    client, store = _fixture()
    store.next_outcome = ReservationOutcome.SATURATED
    with client:
        proof = client.post(
            f"/api/public/widgets/{KEY}/proof", json={}, headers={"Origin": ORIGIN}
        ).json()["proof"]
        saturated = client.post(
            f"/api/public/widgets/{KEY}/admissions",
            json={"proof": proof, "message": "quota"},
            headers={"Origin": ORIGIN},
        )

    assert saturated.status_code == 429
    assert saturated.headers["retry-after"] == "561600"
    assert store.reservations == {}


def test_authorized_store_failure_is_cors_readable_but_wrong_origin_is_not() -> None:
    client, store = _fixture()
    with client:
        proof = client.post(
            f"/api/public/widgets/{KEY}/proof", json={}, headers={"Origin": ORIGIN}
        ).json()["proof"]
        store.fail_reservation = True
        allowed = client.post(
            f"/api/public/widgets/{KEY}/admissions",
            json={"proof": proof, "message": "failure"},
            headers={"Origin": ORIGIN},
        )
        hostile = client.post(
            f"/api/public/widgets/{KEY}/admissions",
            json={"proof": proof, "message": "failure"},
            headers={"Origin": "https://attacker.example.test"},
        )

    assert allowed.status_code == 503
    assert allowed.json() == {"detail": "Public widget request rejected."}
    assert allowed.headers["access-control-allow-origin"] == ORIGIN
    assert allowed.headers["vary"] == "Origin"
    assert hostile.status_code == 403
    assert "access-control-allow-origin" not in hostile.headers
