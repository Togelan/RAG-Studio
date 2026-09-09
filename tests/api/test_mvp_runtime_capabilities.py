from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.billing_runtime import BillingConfiguration
from src.api.react_ui import UiMode, UiServingConfiguration
from src.api.saas_runtime import (
    RuntimeConfiguration,
    RuntimeMode,
    create_saas_runtime_router,
)


def _billing_configuration() -> BillingConfiguration:
    price_id = "price_capability0001"
    portal_id = "bpc_capability000001"
    return BillingConfiguration.model_validate(
        {
            "api_key": "rk_test_capabilityfixture0001",
            "webhook_secret": "whsec_capabilityfixture0001",
            "price_id": price_id,
            "public_app_url": "http://127.0.0.1:8013/saas",
            "portal_configuration_id": portal_id,
            "test_object_pairs": f"{price_id}|{portal_id}",
        }
    )


def _client(runtime: RuntimeConfiguration, *, dependencies_ready: bool) -> TestClient:
    async def readiness_probe(_runtime: RuntimeConfiguration) -> bool:
        return dependencies_ready

    app = FastAPI()
    app.include_router(
        create_saas_runtime_router(
            runtime,
            UiServingConfiguration(mode=UiMode.REACT, react_build=None),
            readiness_probe,
        )
    )
    return TestClient(app)


def test_capabilities_distinguish_local_demo_without_payment_or_public_access() -> None:
    runtime = RuntimeConfiguration(
        mode=RuntimeMode.SAAS,
        local_demo_mode=True,
    )

    with _client(runtime, dependencies_ready=True) as client:
        response = client.get("/api/saas/capabilities")

    assert response.status_code == 200
    assert response.json() == {
        "mode": "saas",
        "dependencies": "ready",
        "personal_lab": "configured",
        "billing": "local_demo",
        "public_widget": "protected_preview",
    }


def test_capabilities_distinguish_stripe_and_public_widget_configuration() -> None:
    runtime = RuntimeConfiguration(
        mode=RuntimeMode.SAAS,
        billing=_billing_configuration(),
        publication_enabled=True,
    )

    with _client(runtime, dependencies_ready=True) as client:
        first = client.get("/api/saas/capabilities")
        repeated = client.get("/api/saas/capabilities")

    expected = {
        "mode": "saas",
        "dependencies": "ready",
        "personal_lab": "configured",
        "billing": "stripe_test_mode",
        "public_widget": "configured",
    }
    assert first.json() == expected
    assert repeated.json() == expected
    combined = first.text + repeated.text
    assert "rk_test_" not in combined
    assert "whsec_" not in combined
    assert "price_capability" not in combined
    assert "bpc_capability" not in combined


def test_capabilities_report_partial_dependency_state_without_claiming_features() -> (
    None
):
    runtime = RuntimeConfiguration(mode=RuntimeMode.SAAS)

    with _client(runtime, dependencies_ready=False) as client:
        response = client.get("/api/saas/capabilities")

    assert response.status_code == 200
    assert response.json() == {
        "mode": "saas",
        "dependencies": "unavailable",
        "personal_lab": "configured",
        "billing": "disabled",
        "public_widget": "disabled",
    }


def test_capabilities_remain_absent_from_local_legacy_runtime() -> None:
    runtime = RuntimeConfiguration(mode=RuntimeMode.LOCAL)

    with _client(runtime, dependencies_ready=True) as client:
        response = client.get("/api/saas/capabilities")

    assert response.status_code == 404
    assert response.json() == {"detail": "Not found"}
