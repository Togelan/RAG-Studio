"""Shared FastAPI dependencies — encryption, audit logging, Qdrant client.

Provides:
- Fernet-based encryption/decryption for API keys (AC-008.3)
- Structured JSON audit logging with daily rotation (AC-008.8)
- Qdrant client singleton dependency
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from qdrant_client import AsyncQdrantClient

from src.vector_store.client import get_qdrant_client as _get_qdrant_client

# ============================================================
# Fernet Encryption for API Keys (AC-008.3)
# ============================================================

# Sensitive keys that must never appear in logs/traces
_SENSITIVE_KEYS = frozenset(
    {
        "OPENAI_API_KEY",
        "DEEPSEEK_API_KEY",
        "ANTHROPIC_API_KEY",
        "LANGCHAIN_API_KEY",
        "QDRANT_API_KEY",
        "api_key",
        "password",
        "secret",
        "token",
    }
)

_PBKDF2_ITERATIONS = 600_000
_PBKDF2_DKLEN = 32
_SALT_SEPARATOR = ":"


def _get_passphrase() -> str:
    """Get the encryption passphrase from environment.

    Returns:
        The passphrase string.

    Raises:
        RuntimeError: If RAG_STUDIO_PASSPHRASE is not set.
    """
    passphrase = os.getenv("RAG_STUDIO_PASSPHRASE")
    if not passphrase:
        raise RuntimeError(
            "RAG_STUDIO_PASSPHRASE environment variable is not set. "
            "Please set a strong passphrase to encrypt your API keys "
            "(e.g., `export RAG_STUDIO_PASSPHRASE='your-strong-passphrase'`)."
        )
    return passphrase


def _derive_key(salt: bytes, passphrase: str) -> bytes:
    """Derive a Fernet-compatible 32-byte key via PBKDF2-HMAC-SHA256.

    Args:
        salt: Random 16-byte salt.
        passphrase: The user-provided passphrase.

    Returns:
        32-byte base64-urlsafe-encoded Fernet key.
    """
    raw = hashlib.pbkdf2_hmac(
        "sha256",
        passphrase.encode("utf-8"),
        salt,
        _PBKDF2_ITERATIONS,
        dklen=_PBKDF2_DKLEN,
    )
    return base64.urlsafe_b64encode(raw)


def encrypt_api_key(plaintext: str) -> str:
    """Encrypt a plaintext value using Fernet with PBKDF2 key derivation.

    Generates a random 16-byte salt, derives the encryption key via
    PBKDF2-HMAC-SHA256 (600k iterations), and encrypts with Fernet.
    The salt is prepended to the ciphertext: ``<salt_b64>:<token>``.

    Args:
        plaintext: The value to encrypt.

    Returns:
        Encrypted string in ``salt:token`` format.

    Raises:
        RuntimeError: If RAG_STUDIO_PASSPHRASE is not set.
    """
    salt = os.urandom(16)
    passphrase = _get_passphrase()
    key = _derive_key(salt, passphrase)
    f = Fernet(key)
    encrypted = f.encrypt(plaintext.encode("utf-8"))
    salt_b64 = base64.b64encode(salt).decode("ascii")
    return f"{salt_b64}{_SALT_SEPARATOR}{encrypted.decode('ascii')}"


def decrypt_api_key(ciphertext: str) -> str:
    """Decrypt a value previously encrypted with encrypt_api_key.

    Parses the ``salt:token`` format, re-derives the key via
    PBKDF2, and decrypts with Fernet.

    Args:
        ciphertext: The encrypted string in ``salt:token`` format.

    Returns:
        The decrypted plaintext string.

    Raises:
        ValueError: If the ciphertext uses the old (pre-PBKDF2) format.
        RuntimeError: If RAG_STUDIO_PASSPHRASE is not set.
        InvalidToken: If the token cannot be decrypted (wrong passphrase).
    """
    if _SALT_SEPARATOR not in ciphertext:
        raise ValueError(
            "Old-format encrypted secret detected (no salt prefix). "
            "Please re-save your secrets with the new passphrase-based encryption. "
            "Set RAG_STUDIO_PASSPHRASE and re-enter your API keys in Settings."
        )
    salt_b64, token = ciphertext.split(_SALT_SEPARATOR, 1)
    salt = base64.b64decode(salt_b64)
    passphrase = _get_passphrase()
    key = _derive_key(salt, passphrase)
    f = Fernet(key)
    decrypted = f.decrypt(token.encode("ascii"))
    return decrypted.decode("utf-8")


def get_secrets_path() -> Path:
    """Return the path to the encrypted secrets file.

    Default: ~/.rag-studio/secrets.enc
    """
    custom = os.getenv("RAG_STUDIO_SECRETS_PATH")
    if custom:
        return Path(custom)
    return Path.home() / ".rag-studio" / "secrets.enc"


def load_secrets() -> dict[str, str]:
    """Load and decrypt stored secrets from disk.

    Returns:
        Dictionary of decrypted key-value pairs, or empty dict if no
        secrets file exists or if the file is corrupted/unreadable.

    Raises:
        RuntimeError: If RAG_STUDIO_PASSPHRASE is not set.
        OSError: On unexpected filesystem errors (not FileNotFoundError).
    """
    path = get_secrets_path()
    if not path.exists():
        return {}
    try:
        ciphertext = path.read_text()
        plaintext = decrypt_api_key(ciphertext)
        secrets: dict[str, str] = json.loads(plaintext)
        return secrets
    except FileNotFoundError:
        return {}
    except (InvalidToken, json.JSONDecodeError) as e:
        logging.getLogger(__name__).warning(
            "Failed to decrypt secrets file %s: %s. Starting with empty secrets.",
            path,
            e,
        )
        return {}
    except ValueError as e:
        logging.getLogger(__name__).warning(
            "Failed to decrypt secrets file %s: %s. Starting with empty secrets.",
            path,
            e,
        )
        return {}


def save_secrets(secrets: dict[str, str]) -> None:
    """Encrypt and persist secrets to disk.

    Args:
        secrets: Dictionary of key-value pairs to encrypt and store.
    """
    path = get_secrets_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    plaintext = json.dumps(secrets)
    ciphertext = encrypt_api_key(plaintext)
    path.write_text(ciphertext)


def sanitize_for_log(data: dict[str, Any]) -> dict[str, Any]:
    """Remove sensitive values from a dictionary before logging.

    Args:
        data: The data dictionary to sanitize.

    Returns:
        Sanitized dictionary with sensitive values replaced by '[REDACTED]'.
    """
    sanitized: dict[str, Any] = {}
    for key, value in data.items():
        if key.upper() in _SENSITIVE_KEYS or any(
            sensitive in key.lower()
            for sensitive in ("api_key", "password", "secret", "token")
        ):
            sanitized[key] = "[REDACTED]"
        elif isinstance(value, dict):
            sanitized[key] = sanitize_for_log(value)
        elif isinstance(value, list):
            sanitized[key] = [
                sanitize_for_log(v) if isinstance(v, dict) else v for v in value
            ]
        else:
            sanitized[key] = value
    return sanitized


# ============================================================
# Audit Logging (AC-008.8)
# ============================================================

_AUDIT_LOGGER_NAME = "rag_studio_audit"
_audit_logger: logging.Logger | None = None


def _get_audit_logger() -> logging.Logger:
    """Get or create the audit logger with daily rotation."""
    global _audit_logger
    if _audit_logger is not None:
        return _audit_logger

    logs_path = os.getenv("RAG_STUDIO_LOGS_PATH")
    if logs_path:
        log_dir = Path(logs_path)
    else:
        log_dir = Path.home() / ".rag-studio" / "logs"

    log_dir.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger(_AUDIT_LOGGER_NAME)
    logger.setLevel(logging.INFO)
    logger.propagate = False  # Don't send audit logs to root logger

    # Remove any existing handlers (prevents duplicates on test resets)
    logger.handlers.clear()

    # Daily rotating file handler
    handler = TimedRotatingFileHandler(
        filename=str(log_dir / "audit.json"),
        when="midnight",
        interval=1,
        backupCount=30,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)

    _audit_logger = logger
    return logger


def log_audit(
    action_type: str,
    *,
    session_id: str | None = None,
    filename: str | None = None,
    success: bool = True,
    extra: dict[str, Any] | None = None,
) -> None:
    """Log a user action as a structured JSON entry (AC-008.8).

    The log MUST NOT contain API keys, passwords, or document content.

    Args:
        action_type: One of 'upload', 'chat', 'settings_change', 'delete_document', 'clear_all'.
        session_id: Session ID for chat messages (optional).
        filename: Filename associated with the action (optional).
        success: Whether the action succeeded.
        extra: Additional data to include (will be sanitized).
    """
    valid_actions = {
        "upload",
        "chat",
        "settings_change",
        "delete_document",
        "clear_all",
    }
    if action_type not in valid_actions:
        action_type = "unknown"

    entry: dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "action": action_type,
        "success": success,
    }

    if session_id:
        entry["session_id"] = session_id
    if filename:
        entry["filename"] = filename
    if extra:
        sanitized = sanitize_for_log(extra)
        entry["extra"] = sanitized

    logger = _get_audit_logger()
    logger.info(json.dumps(entry, ensure_ascii=False))


# ============================================================
# FastAPI Dependencies
# ============================================================


async def get_qdrant_client() -> AsyncQdrantClient:
    """FastAPI dependency for Qdrant client (re-export)."""
    return await _get_qdrant_client()
