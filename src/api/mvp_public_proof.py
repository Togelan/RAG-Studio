"""Signed, short-lived proof for anonymous public widget admission."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import struct
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final
from uuid import UUID, uuid4

_VERSION: Final = 1
_LIFETIME: Final = timedelta(minutes=15)
_FIXED_FORMAT: Final = "!B16sI16s16sQQH"
_FIXED_SIZE: Final = struct.calcsize(_FIXED_FORMAT)
_SIGNATURE_SIZE: Final = hashlib.sha256().digest_size
_MAX_ORIGIN_BYTES: Final = 512


class ProofInvalidError(Exception):
    """Sanitized invalid, expired, forged, or misbound proof result."""


@dataclass(frozen=True, slots=True)
class VerifiedPublicProof:
    """Verified public-only values with no Personal Lab or collection authority."""

    session_id: UUID
    reservation_id: UUID
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class PublicProofSigner:
    """Issue and verify domain-separated HMAC public widget proofs."""

    signing_key: bytes

    def __post_init__(self) -> None:
        if len(self.signing_key) < 32:
            raise ProofInvalidError

    def issue(
        self,
        publication_id: UUID,
        key_version: int,
        origin: str,
        now: datetime,
        *,
        session_id: UUID | None = None,
        nonce: UUID | None = None,
    ) -> str:
        """Issue one non-persistent proof with a fixed fifteen-minute lifetime."""
        issued_at = _utc(now)
        expires_at = issued_at + _LIFETIME
        origin_bytes = origin.encode("ascii")
        if len(origin_bytes) > _MAX_ORIGIN_BYTES or not 1 <= key_version <= 2**32 - 1:
            raise ProofInvalidError
        payload = (
            struct.pack(
                _FIXED_FORMAT,
                _VERSION,
                publication_id.bytes,
                key_version,
                (session_id or uuid4()).bytes,
                (nonce or uuid4()).bytes,
                int(issued_at.timestamp()),
                int(expires_at.timestamp()),
                len(origin_bytes),
            )
            + origin_bytes
        )
        signature = hmac.digest(self.signing_key, _domain(payload), "sha256")
        return base64.urlsafe_b64encode(payload + signature).rstrip(b"=").decode()

    def verify(
        self,
        token: str,
        publication_id: UUID,
        key_version: int,
        origin: str,
        now: datetime,
    ) -> VerifiedPublicProof:
        """Authenticate and bind a proof without returning private scope."""
        payload = _authenticate(token, self.signing_key)
        try:
            unpacked = struct.unpack(_FIXED_FORMAT, payload[:_FIXED_SIZE])
            version, raw_publication, proof_version = unpacked[:3]
            raw_session, raw_nonce, issued, expires, origin_length = unpacked[3:]
            encoded_origin = payload[_FIXED_SIZE:]
            proof_origin = encoded_origin.decode("ascii")
        except struct.error, UnicodeDecodeError, ValueError:
            raise ProofInvalidError from None
        valid_shape = (
            version == _VERSION
            and len(encoded_origin) == origin_length
            and origin_length <= _MAX_ORIGIN_BYTES
            and expires - issued == int(_LIFETIME.total_seconds())
        )
        valid_binding = (
            hmac.compare_digest(raw_publication, publication_id.bytes)
            and proof_version == key_version
            and hmac.compare_digest(proof_origin, origin)
        )
        current = int(_utc(now).timestamp())
        if (
            not valid_shape
            or not valid_binding
            or current < issued
            or current >= expires
        ):
            raise ProofInvalidError
        return VerifiedPublicProof(
            UUID(bytes=raw_session),
            UUID(bytes=raw_nonce),
            datetime.fromtimestamp(expires, tz=UTC),
        )


def _authenticate(token: str, signing_key: bytes) -> bytes:
    try:
        encoded = token.encode("ascii")
        raw = base64.b64decode(
            encoded + b"=" * (-len(encoded) % 4), altchars=b"-_", validate=True
        )
    except UnicodeEncodeError, binascii.Error, ValueError:
        raise ProofInvalidError from None
    if len(raw) < _FIXED_SIZE + _SIGNATURE_SIZE:
        raise ProofInvalidError
    payload, signature = raw[:-_SIGNATURE_SIZE], raw[-_SIGNATURE_SIZE:]
    expected = hmac.digest(signing_key, _domain(payload), "sha256")
    if not hmac.compare_digest(signature, expected):
        raise ProofInvalidError
    return payload


def _domain(payload: bytes) -> bytes:
    return b"rag-studio:public-widget-proof:v1\x00" + payload


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ProofInvalidError
    return value.astimezone(UTC)
