from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import patch

import pytest

import src.paths as runtime_paths
from src.api import billing_runtime
from src.api.main import create_app
from src.api.saas_runtime import (
    RuntimeMode,
    SaasConfigurationError,
    load_runtime_configuration,
)

PROJECT_ROOT = Path(__file__).parents[2]
ENV_EXAMPLE_PATH = PROJECT_ROOT / ".env.example"
BILLING_ENVIRONMENT_NAMES = (
    "RAG_STUDIO_BILLING_ENABLED",
    "RAG_STUDIO_STRIPE_RESTRICTED_KEY",
    "RAG_STUDIO_STRIPE_WEBHOOK_SECRET",
    "RAG_STUDIO_STRIPE_PRICE_ID",
    "RAG_STUDIO_PUBLIC_APP_URL",
    "RAG_STUDIO_STRIPE_CUSTOMER_PORTAL_CONFIGURATION_ID",
    "RAG_STUDIO_STRIPE_TEST_OBJECT_PAIRS",
)


def _test_restricted_key() -> str:
    return "rk_" + "test_" + "runtimefixturevalue0001"


def _configure_saas_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    project_root = tmp_path / "project"
    monkeypatch.setattr(runtime_paths, "PROJECT_ROOT", project_root)
    monkeypatch.setenv("RAG_STUDIO_RUNTIME_MODE", "saas")
    monkeypatch.setenv("RAG_STUDIO_DATA_ROOT", str(project_root / "saas-data"))
    monkeypatch.setenv("RAG_STUDIO_SUPABASE_URL", "http://127.0.0.1:9999")
    monkeypatch.setenv(
        "RAG_STUDIO_SUPABASE_JWT_ISSUER", "http://127.0.0.1:8013/auth/v1"
    )
    monkeypatch.setenv("RAG_STUDIO_SUPABASE_JWT_AUDIENCE", "authenticated")
    monkeypatch.setenv(
        "RAG_STUDIO_SUPABASE_DATABASE_URL", "postgresql://local.invalid/postgres"
    )
    monkeypatch.setenv("RAG_STUDIO_SESSION_SIGNING_KEY", "x" * 32)
    monkeypatch.setenv("QDRANT_URL", "http://127.0.0.1:6333")
    monkeypatch.setenv("RAG_STUDIO_CORS_ORIGINS", "http://127.0.0.1:8013")


def _configure_valid_billing_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RAG_STUDIO_BILLING_ENABLED", "true")
    monkeypatch.setenv("RAG_STUDIO_STRIPE_RESTRICTED_KEY", _test_restricted_key())
    monkeypatch.setenv(
        "RAG_STUDIO_STRIPE_WEBHOOK_SECRET", "whsec_" + "runtimefixturevalue0001"
    )
    monkeypatch.setenv("RAG_STUDIO_STRIPE_PRICE_ID", "price_runtimefixture0001")
    monkeypatch.setenv("RAG_STUDIO_PUBLIC_APP_URL", "http://127.0.0.1:8013/saas")
    monkeypatch.setenv(
        "RAG_STUDIO_STRIPE_CUSTOMER_PORTAL_CONFIGURATION_ID",
        "bpc_runtimefixture0001",
    )
    monkeypatch.setenv(
        "RAG_STUDIO_STRIPE_TEST_OBJECT_PAIRS",
        "price_runtimefixture0001|bpc_runtimefixture0001",
    )


def test_local_runtime_loads_without_billing_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: the authoritative local runtime with no billing variables configured.
    monkeypatch.setenv("RAG_STUDIO_RUNTIME_MODE", "local")
    for name in BILLING_ENVIRONMENT_NAMES:
        monkeypatch.delenv(name, raising=False)

    # When: the existing runtime configuration boundary is loaded.
    configuration = load_runtime_configuration()

    # Then: local-first operation remains available without billing configuration.
    assert configuration.mode is RuntimeMode.LOCAL


def test_enabled_billing_loads_typed_test_configuration(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Given: complete server-only Stripe test-mode configuration.
    _configure_saas_environment(monkeypatch, tmp_path)
    _configure_valid_billing_environment(monkeypatch)

    # When: the application configuration boundary is loaded.
    configuration = load_runtime_configuration()

    # Then: billing is enabled without exposing either secret value.
    assert configuration.billing is not None
    assert configuration.billing.price_id == "price_runtimefixture0001"
    assert configuration.billing.api_key.get_secret_value() == _test_restricted_key()
    assert _test_restricted_key() not in repr(configuration)


def test_valid_configuration_creates_pinned_instance_client_without_global_key(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Given: one validated enabled billing configuration.
    _configure_saas_environment(monkeypatch, tmp_path)
    _configure_valid_billing_environment(monkeypatch)
    configuration = load_runtime_configuration()
    assert configuration.billing is not None

    # When: the server-only Stripe client is created.
    client = billing_runtime.create_stripe_client(configuration.billing)

    # Then: an instance client uses the pinned API and does not publish its key.
    assert type(client).__name__ == "StripeClient"
    assert client._requestor._options.stripe_version == "2026-07-29.dahlia"
    assert _test_restricted_key() not in repr(client)


@pytest.mark.parametrize("missing_name", BILLING_ENVIRONMENT_NAMES[1:])
def test_enabled_billing_rejects_each_missing_value_before_app_mount(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, missing_name: str
) -> None:
    # Given: enabled billing with one required server value absent.
    _configure_saas_environment(monkeypatch, tmp_path)
    _configure_valid_billing_environment(monkeypatch)
    monkeypatch.delenv(missing_name)

    # When/Then: startup fails before the FastAPI application can be constructed.
    with (
        patch("src.api.main.FastAPI") as fastapi_constructor,
        pytest.raises(SaasConfigurationError) as error,
    ):
        create_app()
    assert not fastapi_constructor.called
    assert str(error.value) == "Billing runtime configuration is incomplete or invalid."
    assert _test_restricted_key() not in str(error.value)


@pytest.mark.parametrize(
    ("name", "invalid_value"),
    (
        ("RAG_STUDIO_BILLING_ENABLED", "yes"),
        ("RAG_STUDIO_STRIPE_RESTRICTED_KEY", "sk_" + "test_invalid"),
        ("RAG_STUDIO_STRIPE_RESTRICTED_KEY", "rk_" + "live_invalid"),
        (
            "RAG_STUDIO_STRIPE_RESTRICTED_KEY",
            "rk_" + "test_invalid value padded",
        ),
        ("RAG_STUDIO_STRIPE_WEBHOOK_SECRET", "invalid-webhook-secret"),
        (
            "RAG_STUDIO_STRIPE_WEBHOOK_SECRET",
            "whsec_" + "invalid value padded",
        ),
        ("RAG_STUDIO_STRIPE_PRICE_ID", "product_not_a_price"),
        ("RAG_STUDIO_PUBLIC_APP_URL", "https://user:pass@example.test/saas"),
        ("RAG_STUDIO_PUBLIC_APP_URL", "ftp://example.test/saas"),
        (
            "RAG_STUDIO_STRIPE_CUSTOMER_PORTAL_CONFIGURATION_ID",
            "portal_not_a_configuration",
        ),
        ("RAG_STUDIO_STRIPE_TEST_OBJECT_PAIRS", "price_runtimefixture0001"),
        ("RAG_STUDIO_STRIPE_TEST_OBJECT_PAIRS", "price_runtimefixture0001|"),
        (
            "RAG_STUDIO_STRIPE_TEST_OBJECT_PAIRS",
            "price_runtimefixture0001|bpc_runtimefixture0001|extra",
        ),
    ),
)
def test_billing_rejects_malformed_mixed_or_live_configuration_sanitized(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    name: str,
    invalid_value: str,
) -> None:
    # Given: a fresh otherwise-valid environment with one hostile value.
    _configure_saas_environment(monkeypatch, tmp_path)
    _configure_valid_billing_environment(monkeypatch)
    monkeypatch.setenv(name, invalid_value)

    # When/Then: the runtime fails closed through one sanitized category.
    with pytest.raises(SaasConfigurationError) as error:
        load_runtime_configuration()
    assert str(error.value) == "Billing runtime configuration is incomplete or invalid."
    assert invalid_value not in str(error.value)
    assert _test_restricted_key() not in str(error.value)


@pytest.mark.parametrize(
    ("name", "opaque_identifier"),
    (
        ("RAG_STUDIO_STRIPE_PRICE_ID", "price_otheropaque0001"),
        (
            "RAG_STUDIO_STRIPE_CUSTOMER_PORTAL_CONFIGURATION_ID",
            "bpc_otheropaque0001",
        ),
    ),
)
def test_billing_rejects_syntactically_valid_nonallowlisted_test_objects(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    name: str,
    opaque_identifier: str,
) -> None:
    # Given: a valid-shaped opaque Stripe object outside the server test allowlist.
    _configure_saas_environment(monkeypatch, tmp_path)
    _configure_valid_billing_environment(monkeypatch)
    monkeypatch.setenv(name, opaque_identifier)

    # When/Then: configuration fails before any client or application authority exists.
    with (
        patch("src.api.main.FastAPI") as fastapi_constructor,
        pytest.raises(SaasConfigurationError) as error,
    ):
        create_app()
    assert not fastapi_constructor.called
    assert str(error.value) == "Billing runtime configuration is incomplete or invalid."
    assert opaque_identifier not in str(error.value)


def test_billing_rejects_cross_pair_from_two_individually_allowlisted_pairs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Given: two approved opaque pairs but a configured Price-A/Portal-B cross-pair.
    _configure_saas_environment(monkeypatch, tmp_path)
    _configure_valid_billing_environment(monkeypatch)
    monkeypatch.setenv(
        "RAG_STUDIO_STRIPE_TEST_OBJECT_PAIRS",
        "price_runtimefixture0001|bpc_runtimefixture0001,"
        "price_secondfixture0002|bpc_secondfixture0002",
    )
    monkeypatch.setenv(
        "RAG_STUDIO_STRIPE_CUSTOMER_PORTAL_CONFIGURATION_ID",
        "bpc_secondfixture0002",
    )

    # When/Then: tuple mismatch fails before client or application construction.
    with (
        patch("src.api.main.FastAPI") as fastapi_constructor,
        pytest.raises(SaasConfigurationError) as error,
    ):
        create_app()
    assert not fastapi_constructor.called
    assert str(error.value) == "Billing runtime configuration is incomplete or invalid."


def test_disabled_billing_ignores_retained_values_without_creating_client(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Given: rollback disables billing while operator-owned values remain present.
    _configure_saas_environment(monkeypatch, tmp_path)
    _configure_valid_billing_environment(monkeypatch)
    monkeypatch.setenv("RAG_STUDIO_BILLING_ENABLED", "false")

    # When: the SaaS runtime configuration is loaded.
    configuration = load_runtime_configuration()

    # Then: no billing authority or client is mounted from stale values.
    assert configuration.billing is None


def test_environment_template_has_empty_billing_values_and_no_stripe_credentials() -> (
    None
):
    # Given: the committed operator environment template.
    contents = ENV_EXAMPLE_PATH.read_text(encoding="utf-8")

    # When: assignments and credential-shaped values are scanned as repository text.
    assignments = dict(
        line.split("=", maxsplit=1)
        for line in contents.splitlines()
        if line.startswith("RAG_STUDIO_STRIPE_")
    )
    credential_shape = re.compile(
        r"(?i)(?:[rs]k_(?:test|live)|whsec_)[A-Za-z0-9_-]{8,}"
    )

    # Then: every server-only Stripe value is a blank placeholder and none is usable.
    assert assignments == {
        "RAG_STUDIO_STRIPE_RESTRICTED_KEY": "",
        "RAG_STUDIO_STRIPE_WEBHOOK_SECRET": "",
        "RAG_STUDIO_STRIPE_PRICE_ID": "",
        "RAG_STUDIO_STRIPE_CUSTOMER_PORTAL_CONFIGURATION_ID": "",
        "RAG_STUDIO_STRIPE_TEST_OBJECT_PAIRS": "",
    }
    assert credential_shape.search(contents) is None
