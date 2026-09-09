from __future__ import annotations

import anyio
import httpx
import pytest
from pytest import MonkeyPatch

from src.api.routes.model_fetcher import (
    ProviderModelsUnavailable,
    fetch_deepseek_models,
)
from src.api.routes.personal_settings import DefaultPersonalProviderGateway


def test_deepseek_models_use_configured_execution_base_url(
    monkeypatch: MonkeyPatch,
) -> None:
    # Given: execution is configured for the local DeepSeek-compatible provider.
    configured_base = "http://stage3-fake-deepseek:8080/v1/"
    requested_urls: list[str] = []
    monkeypatch.setenv("DEEPSEEK_BASE_URL", configured_base)

    async def provider_models(
        client: httpx.AsyncClient,
        url: str,
        *,
        headers: dict[str, str],
    ) -> httpx.Response:
        del client
        requested_urls.append(url)
        assert headers["Authorization"].startswith("Bearer ")
        return httpx.Response(
            200,
            json={"data": [{"id": "stage3-deterministic"}]},
        )

    monkeypatch.setattr(httpx.AsyncClient, "get", provider_models)

    # When: Personal Settings validates and enumerates DeepSeek models.
    models = anyio.run(fetch_deepseek_models, "synthetic-local-key")

    # Then: it probes the same configured base used by graph execution.
    assert requested_urls == ["http://stage3-fake-deepseek:8080/v1/models"]
    assert models == ["stage3-deterministic"]


def test_public_deepseek_models_keep_provider_filter(
    monkeypatch: MonkeyPatch,
) -> None:
    # Given: no compatible-provider base overrides the public DeepSeek service.
    monkeypatch.delenv("DEEPSEEK_BASE_URL", raising=False)

    async def public_models(
        client: httpx.AsyncClient,
        url: str,
        *,
        headers: dict[str, str],
    ) -> httpx.Response:
        del client
        assert url == "https://api.deepseek.com/v1/models"
        assert headers["Authorization"].startswith("Bearer ")
        return httpx.Response(
            200,
            json={
                "data": [
                    {"id": "deepseek-v4-flash"},
                    {"id": "unrelated-provider-model"},
                ]
            },
        )

    monkeypatch.setattr(httpx.AsyncClient, "get", public_models)

    # When: Personal Settings enumerates the public provider.
    models = anyio.run(fetch_deepseek_models, "synthetic-public-key")

    # Then: only DeepSeek model IDs are exposed as selectable.
    assert models == ["deepseek-v4-flash"]


def test_explicit_public_deepseek_base_keeps_provider_filter(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1/")

    async def public_models(
        client: httpx.AsyncClient,
        url: str,
        *,
        headers: dict[str, str],
    ) -> httpx.Response:
        del client
        assert url == "https://api.deepseek.com/v1/models"
        assert headers["Authorization"].startswith("Bearer ")
        return httpx.Response(
            200,
            json={
                "data": [
                    {"id": "deepseek-v4-flash"},
                    {"id": "unrelated-provider-model"},
                ]
            },
        )

    monkeypatch.setattr(httpx.AsyncClient, "get", public_models)

    models = anyio.run(fetch_deepseek_models, "synthetic-public-key")

    assert models == ["deepseek-v4-flash"]


def test_deepseek_timeout_becomes_sanitized_unavailable_provider_state(
    monkeypatch: MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Given: a configured adapter whose model probe times out with unsafe transport text.
    async def timeout(
        client: httpx.AsyncClient,
        url: str,
        *,
        headers: dict[str, str],
    ) -> httpx.Response:
        del client, url, headers
        raise httpx.ReadTimeout("unsafe-transport-marker")

    monkeypatch.setattr(httpx.AsyncClient, "get", timeout)

    # When: the server-owned settings gateway validates a replacement secret.
    with pytest.raises(ProviderModelsUnavailable):
        anyio.run(
            DefaultPersonalProviderGateway().validate,
            "deepseek",
            "synthetic-key",
        )

    # Then: timeout is retryable/unavailable and no transport detail is logged.
    assert "unsafe-transport-marker" not in caplog.text


def test_deepseek_invalid_credentials_remain_an_invalid_key(
    monkeypatch: MonkeyPatch,
) -> None:
    # Given: the provider explicitly rejects the replacement key.
    async def unauthorized(
        client: httpx.AsyncClient,
        url: str,
        *,
        headers: dict[str, str],
    ) -> httpx.Response:
        del client, url, headers
        return httpx.Response(401)

    monkeypatch.setattr(httpx.AsyncClient, "get", unauthorized)

    # When: validation reaches DeepSeek.
    valid = anyio.run(
        DefaultPersonalProviderGateway().validate,
        "deepseek",
        "synthetic-key",
    )

    # Then: an explicit credential rejection is not mislabeled as an outage.
    assert valid is False


def test_deepseek_probe_propagates_cancellation(
    monkeypatch: MonkeyPatch,
) -> None:
    # Given: a provider probe that has started but cannot complete.
    async def wait_forever(
        client: httpx.AsyncClient,
        url: str,
        *,
        headers: dict[str, str],
    ) -> httpx.Response:
        del client, url, headers
        await anyio.sleep_forever()
        raise AssertionError("unreachable")

    async def cancel_probe() -> bool:
        with anyio.move_on_after(0.01) as scope:
            await fetch_deepseek_models("synthetic-key")
        return scope.cancelled_caught

    monkeypatch.setattr(httpx.AsyncClient, "get", wait_forever)

    # When: the request is cancelled by its caller.
    cancelled = anyio.run(cancel_probe)

    # Then: cancellation is not converted into an invalid-key or outage result.
    assert cancelled is True
