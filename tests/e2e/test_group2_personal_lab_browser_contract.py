from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
HARNESS = ROOT / "scripts" / "qa" / "group2_personal_lab_qa.ps1"
BENCHMARK = ROOT / "scripts" / "benchmark_personal_lab_retrieval.py"


def _load_benchmark() -> ModuleType:
    spec = importlib.util.spec_from_file_location("group2_benchmark", BENCHMARK)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_harness_exposes_only_bounded_task_owned_scenarios() -> None:
    source = HARNESS.read_text(encoding="utf-8")

    assert (
        'ValidateSet("SaasReact", "RefreshSaasApp", "NegativeContracts", "Teardown", "LocalLegacy")'
        in source
    )
    assert '"--no-deps", "--force-recreate", "rag-studio-saas"' in source
    assert "Invoke-NegativeContractsOnly" in source
    assert "COMPOSE_PARALLEL_LIMIT" in source
    assert "--volumes" in source and "--remove-orphans" in source
    assert "docker system prune" not in source.lower()
    assert "docker volume prune" not in source.lower()
    assert "restart Docker Desktop" not in source
    assert "private-retrieval-plan.json" in source
    assert "private_retrieval_plan_absent" in source
    assert "New-IndexedFixture" in source
    assert "/api/personal/knowledge/upload" in source


def test_harness_redirects_docker_process_streams_before_capture() -> None:
    source = HARNESS.read_text(encoding="utf-8")

    assert "$startInfo.RedirectStandardOutput = $true" in source
    assert "$startInfo.RedirectStandardError = $true" in source
    assert "$startInfo.UseShellExecute = $false" in source
    assert "$process.StandardOutput.ReadToEndAsync()" in source
    assert "$process.StandardError.ReadToEndAsync()" in source
    assert "$output = & $DockerCli @Arguments 2>&1" not in source


def test_compose_profile_fits_four_gibibytes_and_two_cpus() -> None:
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    services = compose["services"]
    names = (
        "rag-studio-saas",
        "stage3-db",
        "stage3-db-bootstrap",
        "stage3-auth",
        "stage3-mail",
        "stage3-fake-deepseek",
        "stage3-qdrant",
    )
    memory_mib = sum(_memory_mib(services[name]["mem_limit"]) for name in names)
    cpus = sum(float(services[name]["cpus"]) for name in names)

    assert memory_mib <= 4096
    assert cpus <= 2.0


def test_benchmark_report_rejects_threshold_and_redacts_handoff(tmp_path: Path) -> None:
    module = _load_benchmark()
    handoff = tmp_path / "handoff.json"
    handoff.write_text(
        json.dumps(
            {
                "app_url": "http://127.0.0.1:5792",
                "fixture_identity_handles": ["identity-a", "identity-b"],
                "project_label": "ragstudio-g2-qa",
            }
        ),
        encoding="utf-8",
    )

    retrieval = module.build_metric(
        latencies_ms=[10.0] * 37 + [3000.0] * 3,
        errors=0,
        threshold_ms=3000.0,
    )
    full_chat = module.build_metric(
        latencies_ms=[4000.0] * 40,
        errors=0,
        status_counts={"200": 40},
    )
    report = module.build_report(
        handoff,
        identities=2,
        concurrency=10,
        requests_per_identity=20,
        scoped_retrieval=retrieval,
        full_chat=full_chat,
    )

    assert report["identities"] == 2
    assert report["concurrency"] == 10
    assert report["scoped_retrieval"]["p95_ms"] == pytest.approx(3000.0)
    assert report["full_chat_e2e_queue_inclusive"]["p95_ms"] == 4000.0
    assert report["passed"] is False
    serialized = json.dumps(report).lower()
    assert "password" not in serialized
    assert "cookie" not in serialized
    assert "token" not in serialized


def test_benchmark_requires_exactly_two_fixture_handles(tmp_path: Path) -> None:
    module = _load_benchmark()
    handoff = tmp_path / "handoff.json"
    handoff.write_text(
        json.dumps(
            {
                "app_url": "http://127.0.0.1:5792",
                "fixture_identity_handles": ["identity-a"],
                "project_label": "ragstudio-g2-qa",
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(module.BenchmarkInputError):
        module.load_handoff(handoff)


def test_benchmark_uses_internal_scoped_retrieval_without_public_test_api() -> None:
    source = BENCHMARK.read_text(encoding="utf-8")

    assert "_personal_graph_vector_store" in source
    assert "hybrid_search" in source
    assert "use_reranker=True" in source
    assert "full_chat_e2e_queue_inclusive" in source
    assert "scoped_retrieval" in source
    assert "docker exec" not in source.lower()
    assert "/api/personal/retrieval" not in source


def _memory_mib(value: str) -> int:
    normalized = value.lower()
    if normalized.endswith("g"):
        return int(float(normalized[:-1]) * 1024)
    assert normalized.endswith("m")
    return int(normalized[:-1])
