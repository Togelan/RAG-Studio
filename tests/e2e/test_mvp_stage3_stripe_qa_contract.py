from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from tests.api import test_mvp_public_routes as public_routes

ROOT = Path(__file__).resolve().parents[2]
HARNESS = ROOT / "scripts" / "qa" / "mvp_stage3_stripe_qa.ps1"
RUNBOOK = ROOT / "docs" / "deployment" / "mvp-stage3-stripe-qa.md"


def _run_preflight(
    tmp_path: Path,
    *,
    stripe_mode: str,
    environment: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    evidence = tmp_path / "evidence"
    state = tmp_path / "state"
    command = [
        "powershell.exe",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(HARNESS),
        "-Scenario",
        "Preflight",
        "-StripeMode",
        stripe_mode,
        "-ProjectName",
        "ragstudio-g2-mvp13-contract",
        "-EvidenceDirectory",
        str(evidence),
        "-StateDirectory",
        str(state),
    ]
    process_environment = os.environ.copy()
    for name in (
        "RAG_STUDIO_STRIPE_RESTRICTED_KEY",
        "RAG_STUDIO_STRIPE_WEBHOOK_SECRET",
        "RAG_STUDIO_STRIPE_PRICE_ID",
        "RAG_STUDIO_PUBLIC_APP_URL",
        "RAG_STUDIO_STRIPE_CUSTOMER_PORTAL_CONFIGURATION_ID",
        "RAG_STUDIO_STRIPE_TEST_OBJECT_PAIRS",
    ):
        process_environment.pop(name, None)
    process_environment.update(environment or {})
    return subprocess.run(
        command,
        cwd=ROOT,
        env=process_environment,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )


@pytest.mark.skipif(
    os.name != "nt", reason="PowerShell fixture contract is Windows-only"
)
def test_signed_fixture_preflight_needs_no_stripe_credentials(tmp_path: Path) -> None:
    # Given: no Stripe values are present in the process environment.
    # When: the deterministic signed-fixture preflight runs.
    result = _run_preflight(tmp_path, stripe_mode="SignedFixture")

    # Then: it succeeds without creating app state or reporting secret material.
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report == {
        "scenario": "preflight",
        "stripe_mode": "signed_fixture",
        "ready": True,
        "docker_operations": 0,
        "app_data_mutations": 0,
        "approved_origin": "http://widget-approved.test:8033",
        "rejected_origin": "http://widget-rejected.test:8034",
        "credentials": "not_required",
    }
    assert not (tmp_path / "state").exists()
    serialized = (result.stdout + result.stderr).lower()
    assert "rk_test_" not in serialized
    assert "whsec_" not in serialized


@pytest.mark.skipif(
    os.name != "nt", reason="PowerShell fixture contract is Windows-only"
)
@pytest.mark.parametrize(
    "environment",
    (
        {},
        {
            "RAG_STUDIO_STRIPE_RESTRICTED_KEY": "rk_" + "live_forbidden",
            "RAG_STUDIO_STRIPE_WEBHOOK_SECRET": "invalid",
            "RAG_STUDIO_STRIPE_PRICE_ID": "price_invalid",
            "RAG_STUDIO_PUBLIC_APP_URL": "https://user:pass@example.invalid/path?x=1",
            "RAG_STUDIO_STRIPE_CUSTOMER_PORTAL_CONFIGURATION_ID": "bpc_invalid",
            "RAG_STUDIO_STRIPE_TEST_OBJECT_PAIRS": "price_other|bpc_other",
        },
    ),
)
def test_live_preflight_fails_before_app_or_data_mutation(
    tmp_path: Path, environment: dict[str, str]
) -> None:
    # Given: live proof was selected with absent operator credentials.
    # When: the live Stripe preflight runs.
    result = _run_preflight(tmp_path, stripe_mode="LiveTest", environment=environment)

    # Then: it exits boundedly and records only a redacted readiness result.
    assert result.returncode == 2
    assert not (tmp_path / "state").exists()
    report_path = tmp_path / "evidence" / "preflight.json"
    report = json.loads(report_path.read_text(encoding="utf-8-sig"))
    assert report["ready"] is False
    assert report["credentials"] == "missing_or_invalid"
    assert report["docker_operations"] == report["app_data_mutations"] == 0
    serialized = report_path.read_text(encoding="utf-8-sig").lower()
    assert "restricted_key" not in serialized
    assert "webhook_secret" not in serialized


def test_harness_and_runbook_keep_live_proof_optional_and_task_owned() -> None:
    source = HARNESS.read_text(encoding="utf-8")
    runbook = RUNBOOK.read_text(encoding="utf-8")

    assert (
        'ValidateSet("Preflight", "SignedFixture", "Stage3Fixture", "LiveTest", "Teardown")'
        in source
    )
    assert '$env:COMPOSE_PARALLEL_LIMIT = "1"' in source
    assert "group2_personal_lab_qa.ps1" in source
    assert '"stage3-db", "stage3-db-bootstrap", "stage3-mail", "stage3-auth"' in source
    assert '"stage3-qdrant", "stage3-fake-deepseek", "rag-studio-saas"' in source
    assert '"ps", "--all", "--format", "json"' in source
    assert '@("up", "-d", "--wait") + $Stage3Services' in source
    assert "if ($matches.Count -ne 1)" in source
    assert 'if ($status.state -ne "exited" -or $status.exit_code -ne 0)' in source
    assert '$status.health -ne "healthy"' in source
    assert '"stats", "--no-stream"' in source
    assert '"test_signed_raw_webhook_applies_once_and_rejects_modified_bytes"' in source
    assert '"test_two_local_origins_allow_and_reject_exactly"' in source
    assert "docker system prune" not in source.lower()
    assert "docker volume prune" not in source.lower()
    assert "restart docker desktop" not in source.lower()
    assert "SignedFixture" in runbook and "LiveTest" in runbook
    assert "http://widget-approved.test:8033" in runbook
    assert "http://widget-rejected.test:8034" in runbook
    assert "optional" in runbook.lower()


def test_live_proof_restores_private_environment_after_success_or_failure() -> None:
    # Given: LiveTest temporarily writes operator-owned Stripe configuration.
    source = HARNESS.read_text(encoding="utf-8")
    live_test = source.split("function Invoke-LiveTest", maxsplit=1)[1].split(
        "function Invoke-Teardown", maxsplit=1
    )[0]

    # When: either the hosted-session request succeeds or raises.
    # Then: one unconditional finalizer restores the original file and app runtime.
    assert "finally {" in live_test
    finalizer = live_test.split("finally {", maxsplit=1)[1]
    assert (
        "Set-Content -LiteralPath $state.env_file -Value $originalEnvironment"
        in finalizer
    )
    assert (
        'Invoke-TaskDocker $state @("up", "-d", "--wait", "--no-deps", "--force-recreate", "rag-studio-saas")'
        in finalizer
    )


def test_two_local_origins_allow_and_reject_exactly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a publication authorizes one exact loopback host origin.
    monkeypatch.setattr(public_routes, "ORIGIN", "http://widget-approved.test:8033")
    client, _ = public_routes._fixture()

    # When: each local host sends the same public preflight.
    with client:
        approved = client.options(
            f"/api/public/widgets/{public_routes.KEY}/proof",
            headers={
                "Origin": "http://widget-approved.test:8033",
                "Access-Control-Request-Method": "POST",
            },
        )
        rejected = client.options(
            f"/api/public/widgets/{public_routes.KEY}/proof",
            headers={
                "Origin": "http://widget-rejected.test:8034",
                "Access-Control-Request-Method": "POST",
            },
        )

    # Then: only the exact approved origin receives CORS authority.
    assert approved.status_code == 204
    assert (
        approved.headers["access-control-allow-origin"]
        == "http://widget-approved.test:8033"
    )
    assert rejected.status_code == 403
    assert "access-control-allow-origin" not in rejected.headers
