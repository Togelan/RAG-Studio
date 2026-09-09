"""Immutable Personal Lab publication lifecycle and public boundary policy."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import assert_never
from uuid import UUID

from src.api.mvp_publication_origin import (
    CanonicalOrigin,
    OriginRejectedError,
    RequestKind,
    canonicalize_origin,
)


class PublicationState(StrEnum):
    """Persistent lifecycle states for the sole Personal Lab publication."""

    ENABLED = "enabled"
    DISABLED = "disabled"
    REVOKED = "revoked"


class PublicationEventType(StrEnum):
    """Append-only audit events retained across rollback and revocation."""

    PUBLISHED = "published"
    ENABLED = "enabled"
    DISABLED = "disabled"
    KEY_ROTATED = "key_rotated"
    REVOKED = "revoked"


class BoundaryOutcome(StrEnum):
    """Sanitized outcomes decided before public RAG or scope resolution."""

    ALLOWED = "allowed"
    FEATURE_DISABLED = "feature_disabled"
    UNKNOWN_KEY = "unknown_key"
    DISABLED = "disabled"
    REVOKED = "revoked"
    INVALID_ORIGIN = "invalid_origin"
    ORIGIN_MISMATCH = "origin_mismatch"


class PublicationConflictError(ValueError):
    """Raised when a command attempts to replace publication authority."""

    def __str__(self) -> str:
        return "Publication conflicts with retained server state."


@dataclass(frozen=True, slots=True)
class PublicationAuditEvent:
    """One immutable, redacted publication lifecycle record."""

    event_type: PublicationEventType
    key_version: int
    previous_public_key: UUID | None
    current_public_key: UUID
    recorded_at: datetime


@dataclass(frozen=True, slots=True)
class Publication:
    """One server-owned publication bound to one opaque Personal Lab."""

    id: UUID
    personal_lab_id: UUID
    public_key: UUID
    allowed_origin: CanonicalOrigin
    state: PublicationState
    key_version: int
    audit: tuple[PublicationAuditEvent, ...]


@dataclass(frozen=True, slots=True)
class PublicBoundaryDecision:
    """Scope-free result safe for a later public transport boundary."""

    outcome: BoundaryOutcome


def publish(
    current: Publication | None,
    personal_lab_id: UUID,
    raw_origin: str,
    publication_id: UUID,
    public_key: UUID,
    recorded_at: datetime,
) -> Publication:
    """Create, replay, or re-enable the sole exact-origin publication."""
    allowed_origin = canonicalize_origin(raw_origin)
    if current is None:
        event = PublicationAuditEvent(
            PublicationEventType.PUBLISHED, 1, None, public_key, recorded_at
        )
        return Publication(
            publication_id,
            personal_lab_id,
            public_key,
            allowed_origin,
            PublicationState.ENABLED,
            1,
            (event,),
        )
    if (
        current.personal_lab_id != personal_lab_id
        or current.id != publication_id
        or current.allowed_origin != allowed_origin
    ):
        raise PublicationConflictError
    match current.state:
        case PublicationState.ENABLED:
            return current
        case PublicationState.DISABLED:
            return _with_state(
                current,
                PublicationState.ENABLED,
                PublicationEventType.ENABLED,
                recorded_at,
            )
        case PublicationState.REVOKED:
            raise PublicationConflictError
        case unreachable_kind:
            assert_never(unreachable_kind)


def disable_publication(current: Publication, recorded_at: datetime) -> Publication:
    """Disable new public resolution while retaining the publication ledger."""
    match current.state:
        case PublicationState.ENABLED:
            return _with_state(
                current,
                PublicationState.DISABLED,
                PublicationEventType.DISABLED,
                recorded_at,
            )
        case PublicationState.DISABLED:
            return current
        case PublicationState.REVOKED:
            raise PublicationConflictError
        case unreachable_request_kind:
            assert_never(unreachable_request_kind)


def rotate_public_key(
    current: Publication, new_public_key: UUID, recorded_at: datetime
) -> Publication:
    """Invalidate the current identifier without changing enabled state."""
    if (
        current.state is PublicationState.REVOKED
        or new_public_key == current.public_key
    ):
        raise PublicationConflictError
    return _with_key(
        current, new_public_key, PublicationEventType.KEY_ROTATED, recorded_at
    )


def revoke_publication(
    current: Publication, replacement_key: UUID, recorded_at: datetime
) -> Publication:
    """Terminally revoke and rotate the identifier while retaining all audit."""
    if current.state is PublicationState.REVOKED:
        return current
    if replacement_key == current.public_key:
        raise PublicationConflictError
    rotated = _with_key(
        current, replacement_key, PublicationEventType.REVOKED, recorded_at
    )
    return Publication(
        rotated.id,
        rotated.personal_lab_id,
        rotated.public_key,
        rotated.allowed_origin,
        PublicationState.REVOKED,
        rotated.key_version,
        rotated.audit,
    )


def evaluate_public_boundary(
    feature_enabled: bool,
    publication: Publication | None,
    presented_key: UUID,
    raw_origin: str | None,
    request_kind: RequestKind,
) -> PublicBoundaryDecision:
    """Fail closed before returning any authority that can resolve Personal RAG."""
    if not feature_enabled:
        return PublicBoundaryDecision(BoundaryOutcome.FEATURE_DISABLED)
    if publication is None or publication.public_key != presented_key:
        return PublicBoundaryDecision(BoundaryOutcome.UNKNOWN_KEY)
    match publication.state:
        case PublicationState.DISABLED:
            return PublicBoundaryDecision(BoundaryOutcome.DISABLED)
        case PublicationState.REVOKED:
            return PublicBoundaryDecision(BoundaryOutcome.REVOKED)
        case PublicationState.ENABLED:
            pass
        case unreachable:
            assert_never(unreachable)
    match request_kind:
        case RequestKind.REQUEST | RequestKind.PREFLIGHT:
            try:
                presented_origin = canonicalize_origin(raw_origin)
            except OriginRejectedError:
                return PublicBoundaryDecision(BoundaryOutcome.INVALID_ORIGIN)
        case unreachable_request_kind:
            assert_never(unreachable_request_kind)
    if presented_origin != publication.allowed_origin:
        return PublicBoundaryDecision(BoundaryOutcome.ORIGIN_MISMATCH)
    return PublicBoundaryDecision(BoundaryOutcome.ALLOWED)


def _with_state(
    current: Publication,
    state: PublicationState,
    event_type: PublicationEventType,
    recorded_at: datetime,
) -> Publication:
    event = PublicationAuditEvent(
        event_type,
        current.key_version,
        None,
        current.public_key,
        recorded_at,
    )
    return Publication(
        current.id,
        current.personal_lab_id,
        current.public_key,
        current.allowed_origin,
        state,
        current.key_version,
        (*current.audit, event),
    )


def _with_key(
    current: Publication,
    new_public_key: UUID,
    event_type: PublicationEventType,
    recorded_at: datetime,
) -> Publication:
    key_version = current.key_version + 1
    event = PublicationAuditEvent(
        event_type,
        key_version,
        current.public_key,
        new_public_key,
        recorded_at,
    )
    return Publication(
        current.id,
        current.personal_lab_id,
        new_public_key,
        current.allowed_origin,
        current.state,
        key_version,
        (*current.audit, event),
    )
