"""Security tests for FR-008: API Key Encryption at Rest (AC-008.3).

Validates:
- Fernet encryption/decryption roundtrip
- Key derivation from machine ID
- No plaintext API keys in logs/traces
- .env.example contains no real keys
- Sanitization of sensitive data in logs
"""

from __future__ import annotations

import base64
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest


# ============================================================
# AC-008.3: API Key Encryption at Rest
# ============================================================


class TestAC0083APIKeyEncryption:
    """AC-008.3: Verify AES-256 (Fernet) encryption of API keys at rest."""

    def test_encrypt_decrypt_roundtrip(self) -> None:
        """Encrypted API key can be successfully decrypted."""
        from src.api.dependencies import decrypt_api_key, encrypt_api_key

        plaintext = "sk-proj-this-is-a-test-api-key-12345"
        encrypted = encrypt_api_key(plaintext)
        decrypted = decrypt_api_key(encrypted)

        assert decrypted == plaintext
        assert encrypted != plaintext
        # Fernet tokens start with 'gAAAAA'
        assert encrypted.startswith("gAAAAA")

    def test_different_keys_produce_different_ciphertext(self) -> None:
        """Same plaintext encrypted twice produces different ciphertext (IV)."""
        from src.api.dependencies import encrypt_api_key

        plaintext = "sk-test-key"
        ct1 = encrypt_api_key(plaintext)
        ct2 = encrypt_api_key(plaintext)

        # Different IVs mean different ciphertext
        assert ct1 != ct2

        # But both decrypt to the same plaintext
        from src.api.dependencies import decrypt_api_key

        assert decrypt_api_key(ct1) == decrypt_api_key(ct2) == plaintext

    def test_encrypted_data_is_not_plaintext_json(self) -> None:
        """Encrypted output is not readable JSON."""
        from src.api.dependencies import encrypt_api_key

        data = json.dumps({"OPENAI_API_KEY": "sk-secret"})
        encrypted = encrypt_api_key(data)

        # Should not be valid JSON
        with pytest.raises((json.JSONDecodeError, UnicodeDecodeError)):
            json.loads(encrypted)

    def test_key_derivation_from_machine_id(self) -> None:
        """Fernet key is derived from machine-specific identifier."""
        from src.api.dependencies import _derive_fernet_key

        key1 = _derive_fernet_key(passphrase=None)
        key2 = _derive_fernet_key(passphrase=None)

        # Same machine produces the same key
        assert key1 == key2

        # Key is 32 bytes base64-encoded = 44 chars
        assert len(base64.urlsafe_b64decode(key1)) == 32

    def test_key_derivation_with_passphrase(self) -> None:
        """Different passphrases produce different Fernet keys."""
        from src.api.dependencies import _derive_fernet_key

        key1 = _derive_fernet_key(passphrase="hello")
        key2 = _derive_fernet_key(passphrase="world")

        assert key1 != key2

    def test_secrets_save_and_load_roundtrip(self) -> None:
        """Secrets saved encrypted can be loaded and decrypted."""
        from src.api.dependencies import load_secrets, save_secrets

        with tempfile.TemporaryDirectory() as tmpdir:
            secrets_path = Path(tmpdir) / "secrets.enc"
            with patch(
                "src.api.dependencies.get_secrets_path",
                return_value=secrets_path,
            ):
                test_secrets = {
                    "OPENAI_API_KEY": "sk-test-abc123",
                    "LANGCHAIN_API_KEY": "ls__test-key",
                    "LLM_PROVIDER": "openai",
                }
                save_secrets(test_secrets)
                assert secrets_path.exists()

                # Read raw file - should be encrypted (not plain JSON)
                raw_content = secrets_path.read_text()
                with pytest.raises((json.JSONDecodeError, UnicodeDecodeError)):
                    json.loads(raw_content)

                # Load and decrypt
                loaded = load_secrets()
                assert loaded == test_secrets

    def test_load_secrets_empty_when_no_file(self) -> None:
        """load_secrets returns empty dict when no secrets file exists."""
        from src.api.dependencies import load_secrets

        with patch(
            "src.api.dependencies.get_secrets_path",
            return_value=Path("/nonexistent/path/secrets.enc"),
        ):
            result = load_secrets()
            assert result == {}

    def test_load_secrets_handles_corrupted_file(self) -> None:
        """load_secrets returns empty dict when secrets file is corrupted."""
        from src.api.dependencies import load_secrets

        with tempfile.TemporaryDirectory() as tmpdir:
            secrets_path = Path(tmpdir) / "corrupted.enc"
            secrets_path.write_text("this is not valid fernet data")

            with patch(
                "src.api.dependencies.get_secrets_path",
                return_value=secrets_path,
            ):
                result = load_secrets()
                assert result == {}


# ============================================================
# Sanitization & Log Safety
# ============================================================


class TestSanitization:
    """Verify API keys are stripped from logs and traces."""

    def test_sanitize_api_key(self) -> None:
        """API keys are replaced with [REDACTED] in log data."""
        from src.api.dependencies import sanitize_for_log

        data = {"OPENAI_API_KEY": "sk-abc123", "model": "gpt-4o"}
        sanitized = sanitize_for_log(data)
        assert sanitized["OPENAI_API_KEY"] == "[REDACTED]"
        assert sanitized["model"] == "gpt-4o"

    def test_sanitize_deepseek_key(self) -> None:
        """DeepSeek API key is redacted."""
        from src.api.dependencies import sanitize_for_log

        data = {"DEEPSEEK_API_KEY": "sk-deepseek-key", "provider": "deepseek"}
        sanitized = sanitize_for_log(data)
        assert sanitized["DEEPSEEK_API_KEY"] == "[REDACTED]"

    def test_sanitize_anthropic_key(self) -> None:
        """Anthropic API key is redacted."""
        from src.api.dependencies import sanitize_for_log

        data = {"ANTHROPIC_API_KEY": "sk-ant-secret"}
        sanitized = sanitize_for_log(data)
        assert sanitized["ANTHROPIC_API_KEY"] == "[REDACTED]"

    def test_sanitize_langchain_key(self) -> None:
        """LangChain/LangSmith API key is redacted."""
        from src.api.dependencies import sanitize_for_log

        data = {"LANGCHAIN_API_KEY": "ls__secret-key"}
        sanitized = sanitize_for_log(data)
        assert sanitized["LANGCHAIN_API_KEY"] == "[REDACTED]"

    def test_sanitize_generic_api_key_field(self) -> None:
        """Any field with 'api_key' in the name is redacted."""
        from src.api.dependencies import sanitize_for_log

        data = {
            "my_api_key": "secret123",
            "api_key_v2": "secret456",
            "username": "john",
        }
        sanitized = sanitize_for_log(data)
        assert sanitized["my_api_key"] == "[REDACTED]"
        assert sanitized["api_key_v2"] == "[REDACTED]"
        assert sanitized["username"] == "john"

    def test_sanitize_password_field(self) -> None:
        """Fields containing 'password' are redacted."""
        from src.api.dependencies import sanitize_for_log

        data = {"db_password": "s3cr3t!", "user": "admin"}
        sanitized = sanitize_for_log(data)
        assert sanitized["db_password"] == "[REDACTED]"

    def test_sanitize_token_field(self) -> None:
        """Fields containing 'token' are redacted."""
        from src.api.dependencies import sanitize_for_log

        data = {"access_token": "jwt-token-here", "name": "test"}
        sanitized = sanitize_for_log(data)
        assert sanitized["access_token"] == "[REDACTED]"

    def test_sanitize_nested_api_keys(self) -> None:
        """Nested dictionaries with API keys are recursively sanitized."""
        from src.api.dependencies import sanitize_for_log

        data = {
            "request": {
                "headers": {"authorization": "Bearer sk-secret"},
                "body": {"api_key": "nested-secret"},
            },
            "safe_field": "visible",
        }
        sanitized = sanitize_for_log(data)
        assert sanitized["request"]["body"]["api_key"] == "[REDACTED]"
        assert sanitized["safe_field"] == "visible"

    def test_sanitize_lists_of_dicts(self) -> None:
        """Lists of dicts are sanitized element by element."""
        from src.api.dependencies import sanitize_for_log

        data = {
            "items": [
                {"name": "item1", "api_key": "key1"},
                {"name": "item2", "api_key": "key2"},
            ]
        }
        sanitized = sanitize_for_log(data)
        assert sanitized["items"][0]["api_key"] == "[REDACTED]"
        assert sanitized["items"][1]["api_key"] == "[REDACTED]"
        assert sanitized["items"][0]["name"] == "item1"

    def test_env_example_has_no_real_keys(self) -> None:
        """.env.example contains only placeholder values."""
        env_file = Path(__file__).parent.parent / ".env.example"
        content = env_file.read_text()

        # Check for placeholder patterns
        assert "sk-your-key-here" in content
        assert "your-key-here" in content

        # Verify no real-looking API keys
        import re

        # Match patterns like sk-... with 20+ alphanumeric chars
        real_key_pattern = re.compile(r"(?:sk|ls__)[a-zA-Z0-9_-]{20,}")
        matches = real_key_pattern.findall(content)
        # Allow the placeholder "sk-your-key-here" but nothing else
        real_keys = [
            m for m in matches if m not in ("sk-your-key-here", "sk-ant-your-key-here")
        ]
        assert len(real_keys) == 0, (
            f"Found potential real API keys in .env.example: {real_keys}"
        )


# ============================================================
# Machine ID derivation tests
# ============================================================


class TestMachineIDDerivation:
    """Verify machine-specific identifier generation."""

    def test_machine_id_is_stable(self) -> None:
        """Machine ID is stable across calls."""
        from src.api.dependencies import _get_machine_id

        id1 = _get_machine_id()
        id2 = _get_machine_id()
        assert id1 == id2

    def test_machine_id_is_non_empty(self) -> None:
        """Machine ID is a non-empty string."""
        from src.api.dependencies import _get_machine_id

        machine_id = _get_machine_id()
        assert len(machine_id) > 0
        assert ":" in machine_id  # Format: node:hostname
