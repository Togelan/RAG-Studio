from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from src.api.mvp_public_proof import (
    ProofInvalidError,
    PublicProofSigner,
)

NOW = datetime(2026, 8, 25, 12, 0, tzinfo=UTC)
PUBLICATION = UUID("10000000-0000-4000-8000-000000000001")
SESSION = UUID("20000000-0000-4000-8000-000000000002")
NONCE = UUID("30000000-0000-4000-8000-000000000003")


def test_proof_is_bound_to_publication_origin_and_fifteen_minutes() -> None:
    signer = PublicProofSigner(b"proof-key-material-that-is-at-least-32")
    proof = signer.issue(
        PUBLICATION,
        4,
        "https://widget.example.test",
        NOW,
        session_id=SESSION,
        nonce=NONCE,
    )

    verified = signer.verify(
        proof,
        PUBLICATION,
        4,
        "https://widget.example.test",
        NOW + timedelta(minutes=14, seconds=59),
    )

    assert verified.session_id == SESSION
    assert verified.reservation_id == NONCE
    assert verified.expires_at == NOW + timedelta(minutes=15)


@pytest.mark.parametrize(
    ("publication_id", "key_version", "origin", "now"),
    (
        (UUID(int=99), 4, "https://widget.example.test", NOW),
        (PUBLICATION, 5, "https://widget.example.test", NOW),
        (PUBLICATION, 4, "https://attacker.example.test", NOW),
        (PUBLICATION, 4, "https://widget.example.test", NOW + timedelta(minutes=15)),
    ),
)
def test_proof_rejects_cross_publication_rotation_origin_and_expiry(
    publication_id: UUID, key_version: int, origin: str, now: datetime
) -> None:
    signer = PublicProofSigner(b"proof-key-material-that-is-at-least-32")
    proof = signer.issue(
        PUBLICATION,
        4,
        "https://widget.example.test",
        NOW,
        session_id=SESSION,
        nonce=NONCE,
    )

    with pytest.raises(ProofInvalidError):
        signer.verify(proof, publication_id, key_version, origin, now)


def test_forged_proof_is_rejected_without_echoing_token() -> None:
    signer = PublicProofSigner(b"proof-key-material-that-is-at-least-32")
    proof = signer.issue(
        PUBLICATION,
        4,
        "https://widget.example.test",
        NOW,
        session_id=SESSION,
        nonce=NONCE,
    )

    with pytest.raises(ProofInvalidError) as raised:
        signer.verify(
            proof[:-1] + ("A" if proof[-1] != "A" else "B"),
            PUBLICATION,
            4,
            "https://widget.example.test",
            NOW,
        )

    assert proof not in str(raised.value)
