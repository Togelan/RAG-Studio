from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.dependencies import get_qdrant_client
from src.api.routes.health import router as health_router
from src.api.saas_runtime import SaasConfigurationError, load_runtime_configuration

PROJECT_ROOT = Path(__file__).parents[2]
COMPOSE_PATH = PROJECT_ROOT / "docker-compose.yml"
ENV_EXAMPLE_PATH = PROJECT_ROOT / ".env.example"
RUNBOOK_PATH = PROJECT_ROOT / "docs" / "deployment" / "local-compose-and-hosting.md"


def _compose() -> dict[str, object]:
    return yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))


def _stage3_services() -> dict[str, dict[str, object]]:
    services = _compose()["services"]
    return {
        name: service
        for name, service in services.items()
        if "stage3" in service.get("profiles", [])
    }


def _memory_mib(value: str) -> float:
    normalized = value.strip().lower()
    units = {"m": 1.0, "mb": 1.0, "g": 1024.0, "gb": 1024.0}
    for suffix, multiplier in units.items():
        if normalized.endswith(suffix):
            return float(normalized.removesuffix(suffix)) * multiplier
    return float(normalized) / (1024.0 * 1024.0)


class UnavailableQdrant:
    async def get_collections(self) -> None:
        raise RuntimeError("provider detail must not escape")

    async def collection_exists(self, collection_name: str) -> bool:
        del collection_name
        return False


def _configure_valid_saas_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("RAG_STUDIO_RUNTIME_MODE", "saas")
    monkeypatch.setenv("RAG_STUDIO_DATA_ROOT", str(tmp_path / "app-data"))
    monkeypatch.setenv("RAG_STUDIO_SUPABASE_URL", "http://stage3-auth:9999")
    monkeypatch.setenv(
        "RAG_STUDIO_SUPABASE_JWT_ISSUER", "http://127.0.0.1:8013/auth/v1"
    )
    monkeypatch.setenv("RAG_STUDIO_SUPABASE_JWT_AUDIENCE", "authenticated")
    monkeypatch.setenv(
        "RAG_STUDIO_SUPABASE_DATABASE_URL",
        "postgresql://postgres:secret@stage3-db:5432/postgres",
    )
    monkeypatch.setenv("RAG_STUDIO_SESSION_SIGNING_KEY", "x" * 32)
    monkeypatch.setenv("QDRANT_URL", "http://stage3-qdrant:6333")
    monkeypatch.setenv("RAG_STUDIO_CORS_ORIGINS", "https://studio.example:8443")


def test_stage3_compose_has_pinned_qdrant_and_healthy_app_dependencies() -> None:
    # Given: the parsed Group-1 Compose model.
    services = _compose()["services"]

    # When: the Qdrant and application service contracts are resolved.
    qdrant = services["stage3-qdrant"]
    application = services["rag-studio-saas"]

    # Then: Qdrant is pinned and the app waits for every durable dependency.
    assert qdrant["image"] == "qdrant/qdrant:v1.15.4"
    assert qdrant["profiles"] == ["stage3"]
    assert "healthcheck" in qdrant
    for dependency in ("stage3-db", "stage3-auth", "stage3-qdrant"):
        assert application["depends_on"][dependency]["condition"] == "service_healthy"
    assert application["environment"]["QDRANT_URL"] == "http://stage3-qdrant:6333"


def test_stage3_compose_resources_and_persistence_are_bounded() -> None:
    # Given: every service selected by the Stage-3 profile.
    services = _stage3_services()

    # When: declared limits and durable volume mounts are aggregated.
    memory_mib = sum(
        _memory_mib(str(service["mem_limit"])) for service in services.values()
    )
    cpus = sum(float(service["cpus"]) for service in services.values())
    compose_volumes = set(_compose()["volumes"])

    # Then: the full profile stays within FR-019 and owns all durable stores.
    assert memory_mib <= 4096
    assert cpus <= 2.0
    assert {
        "stage3-postgres-data",
        "stage3-qdrant-data",
        "stage3-app-data",
    } <= compose_volumes
    assert (
        "stage3-postgres-data:/var/lib/postgresql/data"
        in services["stage3-db"]["volumes"]
    )
    assert "stage3-qdrant-data:/qdrant/storage" in services["stage3-qdrant"]["volumes"]
    assert "stage3-app-data:/app/data" in services["rag-studio-saas"]["volumes"]


def test_stage3_required_values_fail_during_compose_interpolation() -> None:
    # Given: parsed service environment mappings rather than source-text markers.
    services = _compose()["services"]
    app_environment = services["rag-studio-saas"]["environment"]
    database_environment = services["stage3-db"]["environment"]
    auth_environment = services["stage3-auth"]["environment"]

    # When/Then: secrets and trusted public origin use Compose required-value guards.
    assert ":?" in database_environment["POSTGRES_PASSWORD"]
    assert ":?" in auth_environment["GOTRUE_JWT_SECRET"]
    assert ":?" in app_environment["RAG_STUDIO_SESSION_SIGNING_KEY"]
    assert ":?" in app_environment["RAG_STUDIO_SESSION_ENCRYPTION_KEYS"]
    assert ":?" in app_environment["RAG_STUDIO_CORS_ORIGINS"]


def test_stage3_fake_provider_is_profile_scoped_and_not_persistent() -> None:
    # Given: the deterministic provider service selected for local acceptance.
    provider = _compose()["services"]["stage3-fake-deepseek"]

    # When/Then: it cannot join default/legacy runtime or retain customer data.
    assert provider["profiles"] == ["stage3"]
    assert provider["restart"] == "no"
    assert all(
        "stage3-" not in volume.split(":", 1)[0] for volume in provider["volumes"]
    )


def test_saas_runtime_requires_qdrant_and_trusted_origins(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Given: otherwise complete SaaS variables without the two dependency boundaries.
    monkeypatch.setenv("RAG_STUDIO_RUNTIME_MODE", "saas")
    monkeypatch.setenv("RAG_STUDIO_DATA_ROOT", str(tmp_path / "app-data"))
    monkeypatch.setenv("RAG_STUDIO_SUPABASE_URL", "http://stage3-auth:9999")
    monkeypatch.setenv(
        "RAG_STUDIO_SUPABASE_JWT_ISSUER", "http://127.0.0.1:8013/auth/v1"
    )
    monkeypatch.setenv("RAG_STUDIO_SUPABASE_JWT_AUDIENCE", "authenticated")
    monkeypatch.setenv(
        "RAG_STUDIO_SUPABASE_DATABASE_URL",
        "postgresql://postgres:secret@stage3-db:5432/postgres",
    )
    monkeypatch.setenv("RAG_STUDIO_SESSION_SIGNING_KEY", "x" * 32)
    monkeypatch.delenv("QDRANT_URL", raising=False)
    monkeypatch.delenv("RAG_STUDIO_CORS_ORIGINS", raising=False)

    # When/Then: startup fails through one sanitized configuration boundary.
    with pytest.raises(SaasConfigurationError) as error:
        load_runtime_configuration()
    assert str(error.value) == "SaaS runtime configuration is incomplete or invalid."
    assert "secret" not in str(error.value)


@pytest.mark.parametrize(
    "invalid_origin",
    (
        "https://user:password@studio.example",
        "https://studio.example/tenant",
        "https://studio.example?tenant=one",
        "https://studio.example#tenant-one",
    ),
)
def test_saas_runtime_rejects_non_origin_urls(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, invalid_origin: str
) -> None:
    # Given: otherwise valid SaaS configuration with a non-origin URL shape.
    _configure_valid_saas_environment(monkeypatch, tmp_path)
    monkeypatch.setenv("RAG_STUDIO_CORS_ORIGINS", invalid_origin)

    # When/Then: the boundary rejects credentials, path, query, or fragment safely.
    with pytest.raises(SaasConfigurationError) as error:
        load_runtime_configuration()
    assert str(error.value) == "SaaS runtime configuration is incomplete or invalid."
    assert invalid_origin not in str(error.value)


def test_saas_runtime_accepts_http_and_https_origins(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Given: valid scheme-host and scheme-host-port trusted origins.
    _configure_valid_saas_environment(monkeypatch, tmp_path)
    monkeypatch.setenv(
        "RAG_STUDIO_CORS_ORIGINS",
        "http://localhost:8013,https://studio.example",
    )

    # When: the SaaS configuration boundary parses the origins.
    configuration = load_runtime_configuration()

    # Then: both valid origin forms survive as typed HTTP URLs.
    assert tuple(
        str(origin).rstrip("/") for origin in configuration.trusted_origins
    ) == (
        "http://localhost:8013",
        "https://studio.example",
    )


def test_liveness_stays_live_while_readiness_fails_sanitized() -> None:
    # Given: a live FastAPI process whose Qdrant dependency is unavailable.
    app = FastAPI()
    app.include_router(health_router)
    qdrant = UnavailableQdrant()
    app.dependency_overrides[get_qdrant_client] = lambda: qdrant

    # When: orchestration and UI readiness probes run beside process liveness.
    with (
        patch(
            "src.vector_store.client.get_qdrant_client",
            new_callable=AsyncMock,
            return_value=qdrant,
        ),
        patch("src.api.dependencies.load_secrets", return_value={}),
        TestClient(app) as client,
    ):
        liveness = client.get("/health")
        readiness = client.get("/api/health")
        ui_readiness = client.get("/api/health/status")

    # Then: liveness is independent and both readiness surfaces fail alike.
    assert liveness.status_code == 200
    assert liveness.json() == {"status": "ok"}
    assert readiness.status_code == 503
    assert readiness.json() == {"qdrant": "unavailable", "status": "degraded"}
    assert ui_readiness.status_code == 503
    assert ui_readiness.json() == {
        "status": "degraded",
        "api_key_configured": False,
    }
    assert "provider detail" not in readiness.text + ui_readiness.text


def test_environment_template_contains_no_usable_stage3_secret() -> None:
    # Given: operator-facing example assignments.
    assignments = {
        line.partition("=")[0]: line.partition("=")[2]
        for line in ENV_EXAMPLE_PATH.read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#") and "=" in line
    }

    # When/Then: every Stage-3 secret remains an explicit empty placeholder.
    secret_names = {
        "STAGE3_POSTGRES_PASSWORD",
        "STAGE3_GOTRUE_JWT_SECRET",
        "RAG_STUDIO_SESSION_SIGNING_KEY",
        "RAG_STUDIO_SESSION_ENCRYPTION_KEYS",
    }
    assert secret_names <= assignments.keys()
    assert all(assignments[name] == "" for name in secret_names)


def test_group1_runbook_covers_bounded_local_and_hosting_operations() -> None:
    # Given: the deployment runbook delivered with the runtime contract.
    assert RUNBOOK_PATH.is_file()
    runbook = RUNBOOK_PATH.read_text(encoding="utf-8")

    # When/Then: every FR-019 operator responsibility has an executable section.
    required_sections = (
        "## Prerequisites and clean state",
        "## Start Stage 3",
        "## Restart without deleting data",
        "## Backup and restore",
        "## Dependency failure",
        "## Functional rollback",
        "## Hosting responsibility matrix",
        "## Cleanup",
    )
    assert all(section in runbook for section in required_sections)
    assert (
        "docker compose --env-file <operator-file> --profile stage3 up -d --build --wait"
        in runbook
    )
