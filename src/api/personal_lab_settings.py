"""Encrypted settings persistence for one trusted Personal Lab scope."""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

from cryptography.fernet import InvalidToken
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from src.api.chunking_settings import ChunkingSettings
from src.api.dependencies import decrypt_api_key, encrypt_api_key
from src.api.personal_lab_scope import PersonalLabScope

_SETTINGS_FILENAME: Final = "settings.enc"
_MASKED_SECRET: Final = "********"
ProviderName = Literal["openai", "deepseek", "anthropic", "ollama"]


class PersonalSettingsPersistenceError(RuntimeError):
    """Report a scoped settings storage failure without path or secret data."""

    def __str__(self) -> str:
        return "Personal settings are unavailable."


class PersonalSettings(BaseModel):
    """Validated Personal Lab RAG and provider configuration without a secret."""

    model_config = ConfigDict(frozen=True)

    provider: ProviderName = "deepseek"
    model: str = Field(default="gpt-4o-mini", min_length=1, max_length=200)
    temperature: float = Field(default=1.0, ge=0.0, le=2.0)
    max_tokens: int = Field(default=2048, ge=1, le=32768)
    system_prompt: str = Field(default="", max_length=20000)
    top_k: int = Field(default=5, ge=1, le=100)
    chunking: ChunkingSettings = Field(default_factory=ChunkingSettings)


class PersonalSettingsResponse(BaseModel):
    """Masked Personal settings response safe for browser state."""

    model_config = ConfigDict(frozen=True)

    provider: ProviderName
    model: str
    temperature: float
    max_tokens: int
    system_prompt: str
    top_k: int
    chunk_size: int
    chunk_overlap: int
    chunking: ChunkingSettings
    api_key: str | None


class PersonalSettingsSaveResponse(PersonalSettingsResponse):
    """Masked save response with chunk replacement signalling."""

    chunks_changed: bool


class PersonalSettingsSaveRequest(PersonalSettings):
    """Validated settings and an optional secret for one atomic publication."""

    api_key: str | None = Field(default=None, min_length=1, max_length=4096)

    def settings(self) -> PersonalSettings:
        return PersonalSettings(
            provider=self.provider,
            model=self.model,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            system_prompt=self.system_prompt,
            top_k=self.top_k,
            chunking=self.chunking,
        )


class ValidatePersonalKeyRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    provider: ProviderName
    api_key: str = Field(min_length=1, max_length=4096)


class ClearPersonalKeyRequest(BaseModel):
    """Require an explicit browser confirmation before key removal."""

    model_config = ConfigDict(frozen=True)

    confirm: Literal[True]


class ValidatePersonalKeyResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    valid: bool
    provider: ProviderName
    error: str | None = None


class PersonalModelsResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    provider: ProviderName
    models: list[str]
    cached: bool = False
    error: str | None = None


class _StoredPersonalSettings(BaseModel):
    model_config = ConfigDict(frozen=True)

    version: Literal[1] = 1
    settings: PersonalSettings = Field(default_factory=PersonalSettings)
    provider_secrets: dict[str, str] = Field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class PersonalSettingsRecord:
    """Server-only settings record with masked-read helpers."""

    settings: PersonalSettings
    provider_secrets: dict[str, str]

    @property
    def provider_secret(self) -> str | None:
        """Return the selected provider secret only to trusted server code."""
        return self.provider_secrets.get(self.settings.provider)

    @property
    def masked_secret(self) -> str | None:
        """Expose only whether the selected provider has a stored secret."""
        return _MASKED_SECRET if self.provider_secret is not None else None


class PersonalLabSettingsStore:
    """Load and atomically replace one scope-owned encrypted settings file."""

    def load(self, scope: PersonalLabScope) -> PersonalSettingsRecord:
        """Load a validated record or return isolated defaults when absent."""
        path = self.path_for(scope)
        if not path.exists():
            return PersonalSettingsRecord(PersonalSettings(), {})
        try:
            plaintext = decrypt_api_key(path.read_text(encoding="utf-8"))
            stored = _StoredPersonalSettings.model_validate_json(plaintext)
        except InvalidToken, OSError, UnicodeError, ValidationError, ValueError:
            raise PersonalSettingsPersistenceError from None
        return PersonalSettingsRecord(stored.settings, dict(stored.provider_secrets))

    def save(
        self,
        scope: PersonalLabScope,
        settings: PersonalSettings,
        *,
        provider_secret: str | None = None,
    ) -> PersonalSettingsRecord:
        """Validate, encrypt, and atomically publish one complete record."""
        current = self.load(scope)
        secrets = dict(current.provider_secrets)
        if provider_secret is not None:
            secrets[settings.provider] = provider_secret
        stored = _StoredPersonalSettings(settings=settings, provider_secrets=secrets)
        ciphertext = encrypt_api_key(stored.model_dump_json())
        self._atomic_write(self.path_for(scope), ciphertext)
        return PersonalSettingsRecord(settings, secrets)

    def clear_provider_secret(
        self, scope: PersonalLabScope, provider: ProviderName
    ) -> PersonalSettingsRecord:
        """Atomically remove one selected provider secret and retain non-secret settings."""
        current = self.load(scope)
        secrets = dict(current.provider_secrets)
        secrets.pop(provider, None)
        stored = _StoredPersonalSettings(
            settings=current.settings,
            provider_secrets=secrets,
        )
        ciphertext = encrypt_api_key(stored.model_dump_json())
        self._atomic_write(self.path_for(scope), ciphertext)
        return PersonalSettingsRecord(current.settings, secrets)

    def path_for(self, scope: PersonalLabScope) -> Path:
        """Return the fixed file below the trusted server-derived scope root."""
        return scope.data_root / _SETTINGS_FILENAME

    def _atomic_write(self, path: Path, ciphertext: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=path.parent,
                prefix=".settings-",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary_path = Path(temporary.name)
                temporary.write(ciphertext)
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_path, path)
        except OSError:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
            raise PersonalSettingsPersistenceError from None
