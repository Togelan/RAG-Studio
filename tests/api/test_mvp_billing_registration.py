from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from pydantic import SecretStr

from src.api.billing_runtime import BillingConfiguration
from src.api.personal_lab_composition import mount_personal_lab_routes
from src.api.saas_runtime import RuntimeConfiguration, RuntimeMode
from tests.api.mvp_billing_route_fakes import fixture


def test_billing_configuration_does_not_register_publication_routes(
    tmp_path: Path,
) -> None:
    # Given: billing is enabled without any publication configuration authority.
    app = FastAPI()
    app.state.runtime_configuration = RuntimeConfiguration(
        mode=RuntimeMode.SAAS,
        billing=BillingConfiguration(
            api_key=SecretStr("rk_test_" + "x" * 24),
            webhook_secret=SecretStr("whsec_" + "x" * 24),
            price_id="price_routefixture0001",
            public_app_url="https://testserver/app",
            portal_configuration_id="bpc_routefixture0001",
            test_object_pairs="price_routefixture0001|bpc_routefixture0001",
        ),
    )
    authority = SimpleNamespace(auth_context=fixture(tmp_path)[1])

    # When: the Personal Lab composition mounts its independently owned leaves.
    mount_personal_lab_routes(app, authority.auth_context, "unused")
    paths = {route.path for route in app.routes}

    # Then: billing is present, but it cannot implicitly enable publication.
    assert "/api/personal/billing" in paths
    assert "/api/personal/billing/checkout" in paths
    assert "/api/billing/stripe/webhook" in paths
    assert "/api/personal/widget-publication" not in paths
