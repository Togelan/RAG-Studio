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
import platform
import uuid
from datetime import datetime, timezone
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet
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

# Machine-specific identifier for key derivation
_MACHINE_ID = str(uuid.getnode())  # MAC-based machine identifier


def _get_machine_id() -> str:
    """Return a machine-specific identifier for Fernet key derivation.

    Uses a combination of:
    - Platform node (MAC address hash)
    - Machine hostname

    Returns:
        A stable string unique to this machine.
    """
    return f"{_MACHINE_ID}:{platform.node()}"


def _derive_fernet_key(passphrase: str | None = None) -> bytes:
    """Derive a Fernet-compatible 32-byte key from machine_id + optional passphrase.

    Args:
        passphrase: Optional user-provided passphrase for extra security.

    Returns:
        32-byte base64-encoded Fernet key.
    """
    machine_id = _get_machine_id()
    seed = machine_id
    if passphrase:
        seed = f"{machine_id}:{passphrase}"
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


def _get_fernet() -> Fernet:
    """Return a Fernet instance using the derived key."""
    passphrase = os.getenv("RAG_STUDIO_PASSPHRASE")
    key = _derive_fernet_key(passphrase if passphrase else None)
    return Fernet(key)


def encrypt_api_key(plaintext: str) -> str:
    """Encrypt an API key using AES-256 (Fernet).

    Args:
        plaintext: The API key to encrypt.

    Returns:
        Base64-encoded encrypted key string.
    """
    f = _get_fernet()
    encrypted = f.encrypt(plaintext.encode("utf-8"))
    return encrypted.decode("utf-8")


def decrypt_api_key(ciphertext: str) -> str:
    """Decrypt an API key previously encrypted with Fernet.

    Args:
        ciphertext: The encrypted API key string.

    Returns:
        The original plaintext API key.
    """
    f = _get_fernet()
    decrypted = f.decrypt(ciphertext.encode("utf-8"))
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
        Dictionary of decrypted key-value pairs, or empty dict if no secrets exist.
    """
    path = get_secrets_path()
    if not path.exists():
        return {}
    try:
        ciphertext = path.read_text()
        plaintext = decrypt_api_key(ciphertext)
        secrets: dict[str, str] = json.loads(plaintext)
        return secrets
    except Exception:
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
