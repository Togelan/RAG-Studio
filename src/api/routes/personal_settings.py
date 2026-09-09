"""Authenticated settings endpoints for the Personal Lab namespace."""

from __future__ import annotations

from dataclasses import dataclass
from functools import partial
from typing import Final, Protocol

import anyio
from fastapi import APIRouter, HTTPException, Request
from pydantic import TypeAdapter, ValidationError

from src.api.personal_lab_registry import PersonalLabRouteDependencies
from src.api.personal_lab_scope import PersonalLabScope
from src.api.personal_lab_settings import (
    ClearPersonalKeyRequest,
    PersonalLabSettingsStore,
    PersonalModelsResponse,
    PersonalSettings,
    PersonalSettingsPersistenceError,
    PersonalSettingsRecord,
    PersonalSettingsResponse,
    PersonalSettingsSaveRequest,
    PersonalSettingsSaveResponse,
    ProviderName,
    ValidatePersonalKeyRequest,
    ValidatePersonalKeyResponse,
)
from src.api.routes.model_fetcher import (
    get_fallback_models,
    get_models_for_provider,
)

_PROVIDER_ADAPTER: Final[TypeAdapter[ProviderName]] = TypeAdapter(ProviderName)


class PersonalProviderGateway(Protocol):
    """Validate and enumerate a provider through a server-owned secret."""

    async def validate(self, provider: str, api_key: str) -> bool: ...

    async def models(self, provider: str, api_key: str | None) -> tuple[str, ...]: ...


class DefaultPersonalProviderGateway:
    """Adapt the existing bounded provider model probes for Personal settings."""

    async def validate(self, provider: str, api_key: str) -> bool:
        if provider == "ollama":
            return True
        models, error = await get_models_for_provider(provider, api_key)
        return bool(models) and error is None

    async def models(self, provider: str, api_key: str | None) -> tuple[str, ...]:
        models, error = await get_models_for_provider(provider, api_key)
        if error is not None:
            return ()
        return tuple(models)


@dataclass(frozen=True, slots=True)
class _PersonalSettingsHandlers:
    dependencies: PersonalLabRouteDependencies
    gateway: PersonalProviderGateway
    store: PersonalLabSettingsStore

    async def get_settings(self, request: Request) -> PersonalSettingsResponse:
        scope = await _resolve_scope(request, self.dependencies)
        return _response(await _load(self.store, scope))

    async def save_settings(
        self, request: Request, payload: PersonalSettingsSaveRequest
    ) -> PersonalSettingsSaveResponse:
        scope = await _resolve_scope(request, self.dependencies)
        current = await _load(self.store, scope)
        settings = payload.settings()
        if payload.api_key is not None:
            try:
                valid = await self.gateway.validate(settings.provider, payload.api_key)
            except OSError, RuntimeError, TimeoutError:
                raise HTTPException(
                    status_code=502, detail="Provider validation is unavailable."
                ) from None
            if not valid:
                raise HTTPException(
                    status_code=400, detail="Provider validation failed."
                )
        saved = await _save(
            self.store,
            scope,
            settings,
            provider_secret=payload.api_key,
        )
        return PersonalSettingsSaveResponse(
            **_response(saved).model_dump(),
            chunks_changed=(
                current.settings.chunking.fingerprint != settings.chunking.fingerprint
            ),
        )

    async def validate_key(
        self, request: Request, payload: ValidatePersonalKeyRequest
    ) -> ValidatePersonalKeyResponse:
        await _resolve_scope(request, self.dependencies)
        try:
            valid = await self.gateway.validate(payload.provider, payload.api_key)
        except OSError, RuntimeError, TimeoutError:
            raise HTTPException(
                status_code=502, detail="Provider validation is unavailable."
            ) from None
        return ValidatePersonalKeyResponse(
            valid=valid,
            provider=payload.provider,
            error=None if valid else "Provider validation failed.",
        )

    async def clear_credential(
        self, request: Request, payload: ClearPersonalKeyRequest
    ) -> PersonalSettingsResponse:
        """Remove only the selected provider credential after explicit confirmation."""
        del payload
        if "scope_id" in request.query_params or request.headers.get(
            "X-Personal-Lab-ID"
        ):
            raise HTTPException(
                status_code=400,
                detail="Personal Lab scope selectors are not accepted.",
            )
        scope = await _resolve_scope(request, self.dependencies)
        current = await _load(self.store, scope)
        cleared = await _clear_provider_secret(
            self.store,
            scope,
            current.settings.provider,
        )
        return _response(cleared)

    async def get_models(
        self, request: Request, provider: str
    ) -> PersonalModelsResponse:
        scope = await _resolve_scope(request, self.dependencies)
        try:
            provider_name = _PROVIDER_ADAPTER.validate_python(provider)
        except ValidationError:
            raise HTTPException(status_code=400, detail="Unsupported provider.")
        record = await _load(self.store, scope)
        api_key = record.provider_secrets.get(provider_name)
        try:
            models = await self.gateway.models(provider_name, api_key)
        except OSError, RuntimeError, TimeoutError:
            raise HTTPException(
                status_code=502, detail="Provider models are unavailable."
            ) from None
        fallback = get_fallback_models(provider_name)
        return PersonalModelsResponse(
            provider=provider_name,
            models=list(models) if models else fallback,
            error=None if models else "Models are unavailable; using defaults.",
        )


def create_personal_settings_router(
    dependencies: PersonalLabRouteDependencies,
    provider_gateway: PersonalProviderGateway | None = None,
    settings_store: PersonalLabSettingsStore | None = None,
) -> APIRouter:
    """Create the scoped Personal settings leaf from trusted authorities."""
    router = APIRouter(prefix="/api/personal/settings", tags=["personal-settings"])
    handlers = _PersonalSettingsHandlers(
        dependencies,
        provider_gateway or DefaultPersonalProviderGateway(),
        settings_store or PersonalLabSettingsStore(),
    )
    router.add_api_route(
        "",
        handlers.get_settings,
        methods=["GET"],
        response_model=PersonalSettingsResponse,
    )
    router.add_api_route(
        "",
        handlers.save_settings,
        methods=["POST"],
        response_model=PersonalSettingsSaveResponse,
    )
    router.add_api_route(
        "/validate-key",
        handlers.validate_key,
        methods=["POST"],
        response_model=ValidatePersonalKeyResponse,
    )
    router.add_api_route(
        "/credential",
        handlers.clear_credential,
        methods=["DELETE"],
        response_model=PersonalSettingsResponse,
    )
    router.add_api_route(
        "/models/{provider}",
        handlers.get_models,
        methods=["GET"],
        response_model=PersonalModelsResponse,
    )

    return router


async def _resolve_scope(
    request: Request, dependencies: PersonalLabRouteDependencies
) -> PersonalLabScope:
    if request.headers.get("X-API-Key"):
        raise HTTPException(
            status_code=400,
            detail="Browser API key headers are not accepted.",
        )
    trusted = await dependencies.auth_context.resolve(request, require_workspace=False)
    return await dependencies.scopes.resolve(trusted.claims.user_id)


async def _load(
    store: PersonalLabSettingsStore, scope: PersonalLabScope
) -> PersonalSettingsRecord:
    try:
        return await anyio.to_thread.run_sync(store.load, scope)
    except PersonalSettingsPersistenceError:
        raise HTTPException(
            status_code=500, detail="Personal settings are unavailable."
        ) from None


async def _save(
    store: PersonalLabSettingsStore,
    scope: PersonalLabScope,
    settings: PersonalSettings,
    *,
    provider_secret: str | None,
) -> PersonalSettingsRecord:
    try:
        save = partial(
            store.save,
            scope,
            settings,
            provider_secret=provider_secret,
        )
        return await anyio.to_thread.run_sync(save)
    except PersonalSettingsPersistenceError:
        raise HTTPException(
            status_code=500, detail="Personal settings could not be saved."
        ) from None


async def _clear_provider_secret(
    store: PersonalLabSettingsStore,
    scope: PersonalLabScope,
    provider: ProviderName,
) -> PersonalSettingsRecord:
    try:
        clear = partial(store.clear_provider_secret, scope, provider)
        return await anyio.to_thread.run_sync(clear)
    except PersonalSettingsPersistenceError:
        raise HTTPException(
            status_code=500, detail="Personal credential could not be removed."
        ) from None


def _response(record: PersonalSettingsRecord) -> PersonalSettingsResponse:
    settings = record.settings
    return PersonalSettingsResponse(
        provider=settings.provider,
        model=settings.model,
        temperature=settings.temperature,
        max_tokens=settings.max_tokens,
        system_prompt=settings.system_prompt,
        top_k=settings.top_k,
        chunk_size=settings.chunking.chunk_size,
        chunk_overlap=settings.chunking.chunk_overlap,
        chunking=settings.chunking,
        api_key=record.masked_secret,
    )
