"""Key rotation and authenticated encryption for durable BFF sessions."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import os
import re
import secrets
from dataclasses import dataclass
from typing import Final
from uuid import UUID

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from src.api.saas_security import BffSessionHandle

_KEY_RING_ENV: Final = "RAG_STUDIO_SESSION_ENCRYPTION_KEYS"
_HANDLE_INFO: Final = b"rag-studio:bff-session-handle:v1"
_NONCE_BYTES: Final = 12
_KEY_ID_PATTERN: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class SessionKeyConfigurationError(RuntimeError):
    """The mandatory session key ring is absent or invalid."""


@dataclass(frozen=True, slots=True)
class SessionKey:
    """One named 256-bit AEAD key."""

    key_id: str
    material: bytes


@dataclass(frozen=True, slots=True)
class SessionKeyRing:
    """Ordered session keys with the current write key first."""

    keys: tuple[SessionKey, ...]

    @classmethod
    def from_environment(cls) -> SessionKeyRing:
        """Parse the mandatory process key ring."""
        return cls.parse(os.environ.get(_KEY_RING_ENV, ""))

    @classmethod
    def parse(cls, value: str) -> SessionKeyRing:
        """Parse ``key-id:base64url-key`` entries in write/read order."""
        entries: list[SessionKey] = []
        seen: set[str] = set()
        for raw_entry in value.split(","):
            key_id, separator, encoded = raw_entry.partition(":")
            if (
                not separator
                or _KEY_ID_PATTERN.fullmatch(key_id) is None
                or key_id in seen
            ):
                raise SessionKeyConfigurationError
            try:
                padding = "=" * (-len(encoded) % 4)
                material = base64.b64decode(
                    encoded + padding, altchars=b"-_", validate=True
                )
            except binascii.Error, ValueError:
                raise SessionKeyConfigurationError from None
            if len(material) != 32:
                raise SessionKeyConfigurationError
            seen.add(key_id)
            entries.append(SessionKey(key_id, material))
        if not entries:
            raise SessionKeyConfigurationError
        return cls(tuple(entries))

    @property
    def current(self) -> SessionKey:
        """Return the only key permitted for new ciphertext."""
        return self.keys[0]

    def by_id(self, key_id: str) -> SessionKey | None:
        """Resolve a read key without exposing its material."""
        return next((key for key in self.keys if key.key_id == key_id), None)


def encrypt_session_value(
    row_id: UUID, field: str, value: str, key: SessionKey
) -> bytes:
    """Encrypt and bind one value to its row and field."""
    nonce = secrets.token_bytes(_NONCE_BYTES)
    ciphertext = AESGCM(key.material).encrypt(
        nonce, value.encode(), _associated_data(row_id, field)
    )
    return nonce + ciphertext


def decrypt_session_value(
    row_id: UUID, field: str, payload: bytes, key: SessionKey
) -> str:
    """Authenticate and decode one row-bound encrypted value."""
    return (
        AESGCM(key.material)
        .decrypt(
            payload[:_NONCE_BYTES],
            payload[_NONCE_BYTES:],
            _associated_data(row_id, field),
        )
        .decode()
    )


def session_handle_digest(handle: BffSessionHandle, key: SessionKey) -> str:
    """Derive a domain-separated HMAC index for one opaque handle."""
    hmac_key = HKDF(
        algorithm=hashes.SHA256(), length=32, salt=None, info=_HANDLE_INFO
    ).derive(key.material)
    return hmac.new(hmac_key, str(handle).encode(), hashlib.sha256).hexdigest()


def _associated_data(row_id: UUID, field: str) -> bytes:
    return f"rag-studio:bff-session:v1:{row_id}:{field}".encode()
