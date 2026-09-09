from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from src.api.mvp_publication import (
    BoundaryOutcome,
    PublicationConflictError,
    PublicationEventType,
    PublicationState,
    disable_publication,
    evaluate_public_boundary,
    publish,
    revoke_publication,
    rotate_public_key,
)
from src.api.mvp_publication_origin import (
    OriginRejectedError,
    OriginRejection,
    RequestKind,
    canonicalize_origin,
)

LAB_ID = UUID("10000000-0000-4000-8000-000000000001")
OTHER_LAB_ID = UUID("20000000-0000-4000-8000-000000000002")
PUBLICATION_ID = UUID("30000000-0000-4000-8000-000000000003")
KEY_1 = UUID("40000000-0000-4000-8000-000000000004")
KEY_2 = UUID("50000000-0000-4000-8000-000000000005")
KEY_3 = UUID("60000000-0000-4000-8000-000000000006")
NOW = datetime(2026, 8, 25, 12, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("raw", "expected"),
    (
        ("HTTPS://Widget.Example.TEST", "https://widget.example.test"),
        ("https://widget.example.test:443", "https://widget.example.test"),
        ("http://widget.example.test:80", "http://widget.example.test"),
        ("https://widget.example.test:8443", "https://widget.example.test:8443"),
    ),
)
def test_origin_is_canonicalized_without_broadening_authority(
    raw: str, expected: str
) -> None:
    # Given: one syntactically exact HTTP origin.
    # When: it crosses the publication boundary.
    origin = canonicalize_origin(raw)
    # Then: only scheme/host case and the scheme's default port are normalized.
    assert str(origin) == expected


@pytest.mark.parametrize(
    ("raw", "reason"),
    (
        (None, OriginRejection.MISSING),
        ("", OriginRejection.MISSING),
        ("null", OriginRejection.NULL),
        ("*", OriginRejection.WILDCARD),
        ("https://*.example.test", OriginRejection.WILDCARD),
        ("https://widget.example.test/path", OriginRejection.NON_ORIGIN_COMPONENT),
        ("https://widget.example.test?x=1", OriginRejection.NON_ORIGIN_COMPONENT),
        ("https://widget.example.test#x", OriginRejection.NON_ORIGIN_COMPONENT),
        ("https://user@widget.example.test", OriginRejection.CREDENTIALS),
        ("ftp://widget.example.test", OriginRejection.SCHEME),
        ("https://localhost", OriginRejection.LOCALHOST),
        ("https://api.localhost", OriginRejection.LOCALHOST),
        ("http://127.0.0.1:4173", OriginRejection.LOCALHOST),
        ("http://127.1", OriginRejection.LOCALHOST),
        ("http://2130706433", OriginRejection.LOCALHOST),
        ("http://[::1]:4173", OriginRejection.IPV6),
        ("https://[2001:db8::1]", OriginRejection.IPV6),
        (" https://widget.example.test", OriginRejection.MALFORMED),
        ("https://widget.example.test:99999", OriginRejection.MALFORMED),
    ),
)
def test_unsafe_or_ambiguous_origin_is_rejected(
    raw: str | None, reason: OriginRejection
) -> None:
    # Given: an origin that is missing, broadened, local, or not an origin tuple.
    # When/Then: parsing rejects it with a bounded machine-readable reason.
    with pytest.raises(OriginRejectedError) as error:
        canonicalize_origin(raw)
    assert error.value.reason is reason


def test_publish_is_idempotent_and_cross_lab_or_origin_change_conflicts() -> None:
    # Given: one newly published Personal Lab origin.
    first = publish(
        None, LAB_ID, "https://widget.example.test:443", PUBLICATION_ID, KEY_1, NOW
    )

    # When: the same command is replayed and forged/changed commands are attempted.
    replay = publish(
        first, LAB_ID, "https://widget.example.test", PUBLICATION_ID, KEY_2, NOW
    )

    # Then: replay adds no state, while selectors and origin replacement cannot mutate it.
    assert replay is first
    assert len(replay.audit) == 1
    with pytest.raises(PublicationConflictError):
        publish(
            first,
            OTHER_LAB_ID,
            "https://widget.example.test",
            PUBLICATION_ID,
            KEY_2,
            NOW,
        )
    with pytest.raises(PublicationConflictError):
        publish(first, LAB_ID, "https://other.example.test", PUBLICATION_ID, KEY_2, NOW)


def test_disable_republish_rotate_and_revoke_retain_complete_audit() -> None:
    # Given: one enabled publication.
    published = publish(
        None, LAB_ID, "https://widget.example.test", PUBLICATION_ID, KEY_1, NOW
    )

    # When: it is disabled, republished, rotated, and finally revoked.
    disabled = disable_publication(published, NOW + timedelta(seconds=1))
    enabled = publish(
        disabled,
        LAB_ID,
        "https://widget.example.test:443",
        PUBLICATION_ID,
        KEY_2,
        NOW + timedelta(seconds=2),
    )
    rotated = rotate_public_key(enabled, KEY_2, NOW + timedelta(seconds=3))
    revoked = revoke_publication(rotated, KEY_3, NOW + timedelta(seconds=4))

    # Then: each semantic transition survives and old keys cannot authorize.
    assert revoked.state is PublicationState.REVOKED
    assert revoked.key_version == 3
    assert tuple(event.event_type for event in revoked.audit) == (
        PublicationEventType.PUBLISHED,
        PublicationEventType.DISABLED,
        PublicationEventType.ENABLED,
        PublicationEventType.KEY_ROTATED,
        PublicationEventType.REVOKED,
    )
    assert (
        evaluate_public_boundary(
            True, revoked, KEY_1, "https://widget.example.test", RequestKind.REQUEST
        ).outcome
        is BoundaryOutcome.UNKNOWN_KEY
    )
    assert (
        evaluate_public_boundary(
            True, revoked, KEY_3, "https://widget.example.test", RequestKind.REQUEST
        ).outcome
        is BoundaryOutcome.REVOKED
    )


def test_rejected_rotation_and_republish_leave_no_partial_state() -> None:
    # Given: one immutable enabled publication snapshot.
    publication = publish(
        None, LAB_ID, "https://widget.example.test", PUBLICATION_ID, KEY_1, NOW
    )

    # When: duplicate-key rotation and malformed republish fail.
    with pytest.raises(PublicationConflictError):
        rotate_public_key(publication, KEY_1, NOW + timedelta(seconds=1))
    with pytest.raises(OriginRejectedError):
        publish(
            publication,
            LAB_ID,
            "https://widget.example.test/path",
            PUBLICATION_ID,
            KEY_2,
            NOW + timedelta(seconds=2),
        )

    # Then: neither failure can append audit or replace current authority.
    assert publication.state is PublicationState.ENABLED
    assert publication.public_key == KEY_1
    assert publication.key_version == 1
    assert len(publication.audit) == 1


def test_public_boundary_is_fail_closed_before_origin_or_publication_lookup() -> None:
    # Given: a retained enabled publication while public service is rolled back.
    publication = publish(
        None, LAB_ID, "https://widget.example.test", PUBLICATION_ID, KEY_1, NOW
    )

    # When: both request and preflight reach the disabled feature boundary.
    request = evaluate_public_boundary(
        False, publication, KEY_1, None, RequestKind.REQUEST
    )
    preflight = evaluate_public_boundary(
        False, publication, KEY_1, "*", RequestKind.PREFLIGHT
    )

    # Then: rollback wins without deleting the retained ledger or parsing attacker input.
    assert request.outcome is BoundaryOutcome.FEATURE_DISABLED
    assert preflight.outcome is BoundaryOutcome.FEATURE_DISABLED
    assert publication.state is PublicationState.ENABLED
    assert len(publication.audit) == 1


@pytest.mark.parametrize("kind", tuple(RequestKind))
def test_request_and_preflight_require_the_same_exact_origin(kind: RequestKind) -> None:
    # Given: one enabled publication with its server-owned canonical origin.
    publication = publish(
        None, LAB_ID, "https://widget.example.test", PUBLICATION_ID, KEY_1, NOW
    )

    # When: canonical equivalent, wrong case-sensitive path, missing, and forged keys arrive.
    accepted = evaluate_public_boundary(
        True, publication, KEY_1, "HTTPS://WIDGET.EXAMPLE.TEST:443", kind
    )
    wrong_port = evaluate_public_boundary(
        True, publication, KEY_1, "https://widget.example.test:444", kind
    )
    missing = evaluate_public_boundary(True, publication, KEY_1, None, kind)
    forged = evaluate_public_boundary(
        True, publication, KEY_2, "https://widget.example.test", kind
    )

    # Then: both flows share exact matching and reveal no scope details.
    assert accepted.outcome is BoundaryOutcome.ALLOWED
    assert wrong_port.outcome is BoundaryOutcome.ORIGIN_MISMATCH
    assert missing.outcome is BoundaryOutcome.INVALID_ORIGIN
    assert forged.outcome is BoundaryOutcome.UNKNOWN_KEY
    assert not hasattr(accepted, "personal_lab_id")
    assert not hasattr(accepted, "collection_name")
