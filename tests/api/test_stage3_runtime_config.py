from __future__ import annotations

from pathlib import Path

import yaml


def test_stage3_auth_requires_the_explicit_jwt_secret_name() -> None:
    # Given: the checked-in Stage 3 Compose and environment template contracts.
    project_root = Path(__file__).parents[2]
    compose = yaml.safe_load(
        (project_root / "docker-compose.yml").read_text(encoding="utf-8")
    )
    template = (project_root / ".env.example").read_text(encoding="utf-8")

    # When: the GoTrue JWT secret mapping is inspected.
    mapping = compose["services"]["stage3-auth"]["environment"]["GOTRUE_JWT_SECRET"]

    # Then: Compose fails before Auth starts when the explicit secret is absent.
    assert mapping == (
        "${STAGE3_GOTRUE_JWT_SECRET:?Set STAGE3_GOTRUE_JWT_SECRET "
        "in the operator env file}"
    )
    assert "STAGE3_GOTRUE_JWT_SECRET=" in template.splitlines()
    assert "STAGE3_JWT_SECRET=" in template.splitlines()


def test_stage3_confirmation_returns_to_the_saas_entry_without_widening_cors() -> None:
    # Given: local auth mails use the public BFF path and the React SaaS entry.
    project_root = Path(__file__).parents[2]
    compose = yaml.safe_load(
        (project_root / "docker-compose.yml").read_text(encoding="utf-8")
    )
    template = (project_root / ".env.example").read_text(encoding="utf-8")

    # When: GoTrue and BFF public URL defaults are inspected.
    auth_environment = compose["services"]["stage3-auth"]["environment"]
    application_environment = compose["services"]["rag-studio-saas"]["environment"]

    # Then: confirmation lands at `/saas` while CORS stays an origin allowlist.
    assert (
        auth_environment["GOTRUE_SITE_URL"]
        == "${STAGE3_SAAS_APP_URL:-http://127.0.0.1:8013/saas}"
    )
    assert (
        auth_environment["GOTRUE_URI_ALLOW_LIST"]
        == "${STAGE3_SAAS_APP_URL:-http://127.0.0.1:8013/saas}"
    )
    assert application_environment["RAG_STUDIO_CORS_ORIGINS"] == (
        "${STAGE3_SITE_URL:?Set STAGE3_SITE_URL to the trusted public origin}"
    )
    assert "STAGE3_SAAS_APP_URL=http://127.0.0.1:8013/saas" in template.splitlines()


def test_stage3_auth_and_bff_derive_the_same_public_jwt_issuer() -> None:
    # Given: the task's single public SaaS origin is the authority for browser-facing Auth URLs.
    project_root = Path(__file__).parents[2]
    compose = yaml.safe_load(
        (project_root / "docker-compose.yml").read_text(encoding="utf-8")
    )
    template = (project_root / ".env.example").read_text(encoding="utf-8")

    # When: the GoTrue issuer and BFF verifier issuer mappings are inspected.
    auth_environment = compose["services"]["stage3-auth"]["environment"]
    application_environment = compose["services"]["rag-studio-saas"]["environment"]

    # Then: both derive from the exact task SaaS base instead of independent public URL overrides.
    expected_issuer = "${STAGE3_SITE_URL:-http://127.0.0.1:8013}/auth/v1"
    assert application_environment["RAG_STUDIO_SUPABASE_JWT_ISSUER"] == expected_issuer
    assert auth_environment["API_EXTERNAL_URL"] == expected_issuer
    assert auth_environment["GOTRUE_JWT_ISSUER"] == expected_issuer
    assert "STAGE3_SUPABASE_PUBLIC_URL=" not in template.splitlines()


def test_stage3_local_chat_stream_uses_a_deterministic_deepseek_adapter() -> None:
    project_root = Path(__file__).parents[2]
    compose = yaml.safe_load(
        (project_root / "docker-compose.yml").read_text(encoding="utf-8")
    )

    services = compose["services"]
    application = services["rag-studio-saas"]
    provider = services["stage3-fake-deepseek"]

    assert provider["profiles"] == ["stage3"]
    assert provider["image"] == "python:3.14-slim"
    assert provider["command"] == ["python", "/provider/fake_openai_provider.py"]
    assert any(
        volume.endswith("/provider/fake_openai_provider.py:ro")
        for volume in provider["volumes"]
    )
    assert (
        application["environment"]["DEEPSEEK_BASE_URL"]
        == "http://stage3-fake-deepseek:8080/v1"
    )
    assert application["environment"]["DEEPSEEK_API_KEY"] == "stage3-local-no-auth"
    assert (
        application["depends_on"]["stage3-fake-deepseek"]["condition"]
        == "service_started"
    )
