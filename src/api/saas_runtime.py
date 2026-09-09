"""Fail-closed runtime selection and SaaS dependency boundary."""

from __future__ import annotations

import os
import re
from collections.abc import Awaitable, Callable
from enum import StrEnum
from pathlib import Path
from typing import Final, Literal, assert_never

import anyio
import asyncpg
import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import (
    AnyHttpUrl,
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    ValidationError,
    field_validator,
)
from pydantic_core import PydanticCustomError

from src.api.billing_runtime import BillingConfiguration, load_billing_configuration
from src.api.mvp_local_demo import LocalDemoConfigurationError, load_local_demo_mode
from src.api.mvp_publication_runtime import load_publication_enabled
from src.api.react_ui import UiServingConfiguration, react_document_response
from src.api.saas_security import load_cookie_transport_policy
from src.paths import project_root, resolve_project_path

_RUNTIME_MODE_ENV: Final = "RAG_STUDIO_RUNTIME_MODE"
_DATA_ROOT_ENV: Final = "RAG_STUDIO_DATA_ROOT"
_SUPABASE_URL_ENV: Final = "RAG_STUDIO_SUPABASE_URL"
_SUPABASE_ISSUER_ENV: Final = "RAG_STUDIO_SUPABASE_JWT_ISSUER"
_SUPABASE_AUDIENCE_ENV: Final = "RAG_STUDIO_SUPABASE_JWT_AUDIENCE"
_SUPABASE_DATABASE_URL_ENV: Final = "RAG_STUDIO_SUPABASE_DATABASE_URL"
_SESSION_KEY_ENV: Final = "RAG_STUDIO_SESSION_SIGNING_KEY"
_QDRANT_URL_ENV: Final = "QDRANT_URL"
_TRUSTED_ORIGINS_ENV: Final = "RAG_STUDIO_CORS_ORIGINS"
_TRUSTED_ORIGIN_PATTERN: Final = re.compile(r"https?://[^/?#@]+/")
_IDENTITY_TIMEOUT: Final = httpx.Timeout(2.0)
_DATABASE_TIMEOUT_SECONDS: Final = 2.0
_PERSISTENCE_OVERRIDE_ENVS: Final = (
    "QDRANT_PATH",
    "RAG_STUDIO_SETTINGS_PATH",
    "RAG_STUDIO_LOGS_PATH",
)


class RuntimeMode(StrEnum):
    """Approved application runtime boundaries."""

    LOCAL = "local"
    SAAS = "saas"


class InvalidRuntimeModeError(ValueError):
    """Raised when runtime selection is outside the closed mode set."""


class SaasConfigurationError(ValueError):
    """Raised without echoing a malformed or secret SaaS configuration value."""


class _SaasEnvironment(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    supabase_url: AnyHttpUrl
    jwt_issuer: AnyHttpUrl
    jwt_audience: str = Field(min_length=1)
    database_url: SecretStr = Field(min_length=1)
    session_signing_key: SecretStr = Field(min_length=32)
    qdrant_url: AnyHttpUrl
    trusted_origins: tuple[AnyHttpUrl, ...] = Field(min_length=1)

    @field_validator("trusted_origins")
    @classmethod
    def validate_trusted_origins(
        cls, origins: tuple[AnyHttpUrl, ...]
    ) -> tuple[AnyHttpUrl, ...]:
        if any(
            _TRUSTED_ORIGIN_PATTERN.fullmatch(str(origin)) is None for origin in origins
        ):
            raise PydanticCustomError("trusted_origin_shape", "invalid trusted origin")
        return origins


class RuntimeConfiguration(BaseModel):
    """Validated local or SaaS process configuration."""

    model_config = ConfigDict(frozen=True)

    mode: RuntimeMode
    supabase_url: AnyHttpUrl | None = None
    jwt_issuer: AnyHttpUrl | None = None
    jwt_audience: str | None = None
    database_url: SecretStr | None = None
    session_signing_key: SecretStr | None = None
    qdrant_url: AnyHttpUrl | None = None
    trusted_origins: tuple[AnyHttpUrl, ...] = ()
    billing: BillingConfiguration | None = None
    publication_enabled: bool = False
    local_demo_mode: bool = False


class RuntimeStatus(BaseModel):
    """Public non-secret SaaS readiness status."""

    model_config = ConfigDict(frozen=True)

    mode: RuntimeMode
    status: str


class RuntimeCapabilities(BaseModel):
    """Public non-secret state for independently gated MVP capabilities."""

    model_config = ConfigDict(frozen=True)

    mode: Literal["saas"] = "saas"
    dependencies: Literal["ready", "unavailable"]
    personal_lab: Literal["configured"] = "configured"
    billing: Literal["disabled", "local_demo", "stripe_test_mode"]
    public_widget: Literal["disabled", "protected_preview", "configured"]


ReadinessProbe = Callable[[RuntimeConfiguration], Awaitable[bool]]


def load_runtime_configuration() -> RuntimeConfiguration:
    """Parse environment configuration once without falling back from SaaS."""
    configured_mode = os.getenv(_RUNTIME_MODE_ENV, RuntimeMode.LOCAL.value)
    try:
        mode = RuntimeMode(configured_mode.strip().lower())
    except ValueError:
        raise InvalidRuntimeModeError(
            "RAG_STUDIO_RUNTIME_MODE must be either 'local' or 'saas'."
        ) from None
    match mode:
        case RuntimeMode.LOCAL:
            return RuntimeConfiguration(mode=RuntimeMode.LOCAL)
        case RuntimeMode.SAAS:
            return _load_saas_configuration()
        case unreachable:
            assert_never(unreachable)


def _load_saas_configuration() -> RuntimeConfiguration:
    configured_origins = os.getenv(_TRUSTED_ORIGINS_ENV)
    try:
        environment = _SaasEnvironment.model_validate(
            {
                "supabase_url": os.getenv(_SUPABASE_URL_ENV),
                "jwt_issuer": os.getenv(_SUPABASE_ISSUER_ENV),
                "jwt_audience": os.getenv(_SUPABASE_AUDIENCE_ENV, "authenticated"),
                "database_url": os.getenv(_SUPABASE_DATABASE_URL_ENV),
                "session_signing_key": os.getenv(_SESSION_KEY_ENV),
                "qdrant_url": os.getenv(_QDRANT_URL_ENV),
                "trusted_origins": (
                    tuple(item.strip() for item in configured_origins.split(","))
                    if configured_origins is not None
                    else None
                ),
            }
        )
    except ValidationError:
        raise SaasConfigurationError(
            "SaaS runtime configuration is incomplete or invalid."
        ) from None
    try:
        billing = load_billing_configuration()
    except ValidationError:
        raise SaasConfigurationError(
            "Billing runtime configuration is incomplete or invalid."
        ) from None
    try:
        publication_enabled = load_publication_enabled()
    except ValidationError:
        raise SaasConfigurationError(
            "Publication runtime configuration is invalid."
        ) from None
    try:
        local_demo_mode = load_local_demo_mode(
            tuple(str(item) for item in environment.trusted_origins),
            billing_configured=billing is not None,
            publication_enabled=publication_enabled,
        )
    except ValidationError, LocalDemoConfigurationError:
        raise SaasConfigurationError(
            "Local demo runtime configuration is invalid."
        ) from None
    load_cookie_transport_policy(
        tuple(str(item) for item in environment.trusted_origins)
    )
    _validate_saas_persistence_boundary()
    return RuntimeConfiguration(
        mode=RuntimeMode.SAAS,
        supabase_url=environment.supabase_url,
        jwt_issuer=environment.jwt_issuer,
        jwt_audience=environment.jwt_audience,
        database_url=environment.database_url,
        session_signing_key=environment.session_signing_key,
        qdrant_url=environment.qdrant_url,
        trusted_origins=environment.trusted_origins,
        billing=billing,
        publication_enabled=publication_enabled,
        local_demo_mode=local_demo_mode,
    )


def _validate_saas_persistence_boundary() -> None:
    configured_root = os.getenv(_DATA_ROOT_ENV)
    if not configured_root:
        raise SaasConfigurationError(
            "SaaS runtime requires an explicit RAG_STUDIO_DATA_ROOT."
        )
    saas_root = resolve_project_path(configured_root)
    legacy_root = (project_root() / "rag-data").resolve()
    if _paths_overlap(saas_root, legacy_root):
        raise SaasConfigurationError("SaaS data root must not overlap legacy data.")
    for environment_variable in _PERSISTENCE_OVERRIDE_ENVS:
        configured_path = os.getenv(environment_variable)
        if configured_path and not resolve_project_path(configured_path).is_relative_to(
            saas_root
        ):
            raise SaasConfigurationError(
                "SaaS persistent path overrides must remain inside its data root."
            )
    for environment_variable in ("FASTEMBED_CACHE_PATH", "FLASHRANK_CACHE_PATH"):
        configured_path = os.getenv(environment_variable)
        if configured_path and _paths_overlap(
            resolve_project_path(configured_path), legacy_root
        ):
            raise SaasConfigurationError(
                "SaaS model cache overrides must not overlap legacy data."
            )


def _paths_overlap(first: Path, second: Path) -> bool:
    return first.is_relative_to(second) or second.is_relative_to(first)


async def identity_service_ready(configuration: RuntimeConfiguration) -> bool:
    """Return whether the configured identity service answers its health probe."""
    endpoint = configuration.supabase_url
    if endpoint is None:
        return False
    try:
        async with httpx.AsyncClient(
            timeout=_IDENTITY_TIMEOUT,
            follow_redirects=False,
            trust_env=False,
        ) as client:
            response = await client.get(f"{str(endpoint).rstrip('/')}/health")
    except httpx.ConnectError, httpx.TimeoutException, httpx.RemoteProtocolError:
        return False
    return response.status_code == 200


async def qdrant_service_ready(configuration: RuntimeConfiguration) -> bool:
    """Return whether the configured Qdrant service answers its health probe."""
    endpoint = configuration.qdrant_url
    if endpoint is None:
        return False
    try:
        async with httpx.AsyncClient(
            timeout=_IDENTITY_TIMEOUT,
            follow_redirects=False,
            trust_env=False,
        ) as client:
            response = await client.get(f"{str(endpoint).rstrip('/')}/healthz")
    except httpx.ConnectError, httpx.TimeoutException, httpx.RemoteProtocolError:
        return False
    return response.status_code == 200


async def database_service_ready(configuration: RuntimeConfiguration) -> bool:
    """Return whether the configured database answers a bounded query."""
    database_url = configuration.database_url
    if database_url is None:
        return False
    try:
        connection = await asyncpg.connect(
            dsn=database_url.get_secret_value(),
            timeout=_DATABASE_TIMEOUT_SECONDS,
            command_timeout=_DATABASE_TIMEOUT_SECONDS,
        )
        try:
            result: int | None = await connection.fetchval(
                "SELECT 1", timeout=_DATABASE_TIMEOUT_SECONDS
            )
            return result == 1
        finally:
            with anyio.move_on_after(_DATABASE_TIMEOUT_SECONDS, shield=True):
                await connection.close(timeout=_DATABASE_TIMEOUT_SECONDS)
    except asyncpg.PostgresError, OSError, TimeoutError:
        return False


async def saas_dependencies_ready(configuration: RuntimeConfiguration) -> bool:
    """Return one sanitized readiness decision for all mandatory dependencies."""
    return (
        await identity_service_ready(configuration)
        and await database_service_ready(configuration)
        and await qdrant_service_ready(configuration)
    )


def create_saas_runtime_router(
    runtime: RuntimeConfiguration,
    ui_configuration: UiServingConfiguration,
    readiness_probe: ReadinessProbe = saas_dependencies_ready,
) -> APIRouter:
    """Create the gated SaaS UI and BFF readiness routes."""
    router = APIRouter(tags=["saas-runtime"])

    @router.get("/saas", response_class=Response)
    @router.get("/saas/{saas_path:path}", response_class=Response)
    async def serve_saas_ui(saas_path: str = "") -> Response:
        del saas_path
        if runtime.mode is RuntimeMode.LOCAL:
            raise HTTPException(status_code=404, detail="Not found")
        return react_document_response(ui_configuration)

    @router.get("/api/saas/runtime", response_model=RuntimeStatus)
    async def runtime_status() -> RuntimeStatus:
        if runtime.mode is RuntimeMode.LOCAL:
            raise HTTPException(status_code=404, detail="Not found")
        if not await readiness_probe(runtime):
            raise HTTPException(
                status_code=503,
                detail="SaaS runtime dependencies are unavailable.",
            )
        return RuntimeStatus(mode=RuntimeMode.SAAS, status="ready")

    @router.get("/api/saas/capabilities", response_model=RuntimeCapabilities)
    async def runtime_capabilities() -> RuntimeCapabilities:
        if runtime.mode is RuntimeMode.LOCAL:
            raise HTTPException(status_code=404, detail="Not found")
        return RuntimeCapabilities(
            dependencies=("ready" if await readiness_probe(runtime) else "unavailable"),
            billing=_billing_capability(runtime),
            public_widget=_public_widget_capability(runtime),
        )

    return router


def _billing_capability(
    runtime: RuntimeConfiguration,
) -> Literal["disabled", "local_demo", "stripe_test_mode"]:
    if runtime.local_demo_mode:
        return "local_demo"
    if runtime.billing is not None:
        return "stripe_test_mode"
    return "disabled"


def _public_widget_capability(
    runtime: RuntimeConfiguration,
) -> Literal["disabled", "protected_preview", "configured"]:
    if runtime.local_demo_mode:
        return "protected_preview"
    if runtime.publication_enabled:
        return "configured"
    return "disabled"
