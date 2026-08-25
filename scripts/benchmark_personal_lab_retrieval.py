#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14"
# dependencies = ["anyio>=4.9", "httpx>=0.27", "pydantic>=2.10"]
# ///

from __future__ import annotations

import argparse
import json
import math
import statistics
import subprocess
import time
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Final, TypedDict
from uuid import UUID

import anyio
import httpx
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

if TYPE_CHECKING:
    from src.vector_store.contracts import VectorSearcher
    from src.vector_store.models import DenseVector, SparseVector

_CSRF_COOKIE: Final = "ragstudio-development-csrf"
_CONTAINER_SCRIPT: Final = "/qa/benchmark_personal_lab_retrieval.py"
_CONTAINER_PLAN: Final = "/qa/private/private-retrieval-plan.json"
BenchmarkInputError = RuntimeError


class RedactedHandoff(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    app_url: str = Field(pattern=r"^http://127\.0\.0\.1:\d+$")
    fixture_identity_handles: tuple[str, str]
    project_label: str = Field(pattern=r"^ragstudio-g2-[a-z0-9-]+$")
    evidence_manifest_path: str | None = None


class PrivateIdentity(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    handle: str
    email: str
    password: str


class RetrievalPlanEntry(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    handle: str
    scope_id: UUID
    namespace: str = Field(pattern=r"^pl_[0-9a-f]{32}$")
    query: str = Field(min_length=1, max_length=500)
    expected_filename: str = Field(min_length=1, max_length=255)


class MetricReport(TypedDict):
    request_count: int
    p50_ms: float
    p95_ms: float
    errors: int
    status_counts: dict[str, int]
    threshold_ms: float | None
    passed: bool


class BenchmarkReport(TypedDict):
    project_label: str
    identities: int
    identity_handles: list[str]
    concurrency: int
    requests_per_identity: int
    scoped_retrieval: MetricReport
    full_chat_e2e_queue_inclusive: MetricReport
    passed: bool


type _Measurement = tuple[float, int, bool]
type _PreparedRetrieval = tuple[
    RetrievalPlanEntry, VectorSearcher, DenseVector, SparseVector
]

_PRIVATE_IDENTITIES: Final = TypeAdapter(tuple[PrivateIdentity, PrivateIdentity])
_RETRIEVAL_PLAN: Final = TypeAdapter(tuple[RetrievalPlanEntry, RetrievalPlanEntry])
_METRIC_REPORT: Final = TypeAdapter(MetricReport)


def load_handoff(path: Path) -> RedactedHandoff:
    """Parse the redacted benchmark boundary and require two opaque identities."""
    try:
        handoff = RedactedHandoff.model_validate_json(path.read_text(encoding="utf-8"))
    except OSError, UnicodeError, ValidationError:
        raise BenchmarkInputError from None
    if len(set(handoff.fixture_identity_handles)) != 2:
        raise BenchmarkInputError
    return handoff


def build_metric(
    *,
    latencies_ms: list[float],
    errors: int,
    status_counts: dict[str, int] | None = None,
    threshold_ms: float | None = None,
) -> MetricReport:
    """Build one redacted latency metric with an optional hard threshold."""
    if not latencies_ms or any(value < 0 for value in latencies_ms) or errors < 0:
        raise BenchmarkInputError
    p95 = _percentile(latencies_ms, 0.95)
    passed = errors == 0 and (threshold_ms is None or p95 < threshold_ms)
    return MetricReport(
        request_count=len(latencies_ms),
        p50_ms=round(statistics.median(latencies_ms), 3),
        p95_ms=round(p95, 3),
        errors=errors,
        status_counts=status_counts or {},
        threshold_ms=threshold_ms,
        passed=passed,
    )


def build_report(
    handoff_path: Path,
    *,
    identities: int,
    concurrency: int,
    requests_per_identity: int,
    scoped_retrieval: MetricReport,
    full_chat: MetricReport,
) -> BenchmarkReport:
    """Build separate retrieval-gated and queue-inclusive Chat measurements."""
    handoff = load_handoff(handoff_path)
    expected = identities * requests_per_identity
    if identities != 2 or concurrency != 10 or requests_per_identity < 1:
        raise BenchmarkInputError
    if any(
        metric["request_count"] != expected for metric in (scoped_retrieval, full_chat)
    ):
        raise BenchmarkInputError
    return BenchmarkReport(
        project_label=handoff.project_label,
        identities=identities,
        identity_handles=list(handoff.fixture_identity_handles),
        concurrency=concurrency,
        requests_per_identity=requests_per_identity,
        scoped_retrieval=scoped_retrieval,
        full_chat_e2e_queue_inclusive=full_chat,
        passed=scoped_retrieval["passed"] and full_chat["passed"],
    )


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * percentile) - 1)]


def _private_handoff_path(handoff_path: Path) -> Path:
    evidence_root = next(
        (parent for parent in handoff_path.resolve().parents if parent.name == ".omo"),
        None,
    )
    if evidence_root is None:
        raise BenchmarkInputError
    return (
        evidence_root / "tmp/group-2-personal-lab/task-9/private-browser-handoff.json"
    )


def _load_private_handoff(
    path: Path, redacted: RedactedHandoff
) -> tuple[PrivateIdentity, PrivateIdentity]:
    try:
        identities = _PRIVATE_IDENTITIES.validate_json(path.read_text(encoding="utf-8"))
    except OSError, UnicodeError, ValidationError:
        raise BenchmarkInputError from None
    if tuple(item.handle for item in identities) != redacted.fixture_identity_handles:
        raise BenchmarkInputError
    return identities


def _load_retrieval_plan(path: Path) -> tuple[RetrievalPlanEntry, RetrievalPlanEntry]:
    try:
        plan = _RETRIEVAL_PLAN.validate_json(path.read_text(encoding="utf-8"))
    except OSError, UnicodeError, ValidationError:
        raise BenchmarkInputError from None
    if len({item.handle for item in plan}) != 2:
        raise BenchmarkInputError
    return plan


async def _sign_in(
    base_url: str, identity: PrivateIdentity
) -> tuple[httpx.AsyncClient, str]:
    client = httpx.AsyncClient(
        base_url=base_url,
        follow_redirects=False,
        limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        timeout=httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=10.0),
        trust_env=False,
    )
    try:
        response = await client.get("/api/saas/auth/csrf")
        response.raise_for_status()
        csrf = client.cookies.get(_CSRF_COOKIE)
        if csrf is None:
            raise BenchmarkInputError
        response = await client.post(
            "/api/saas/auth/signin",
            headers={"Origin": base_url, "X-CSRF-Token": csrf},
            json={"email": identity.email, "password": identity.password},
        )
        response.raise_for_status()
        return client, csrf
    except httpx.HTTPError, BenchmarkInputError:
        await client.aclose()
        raise


async def _create_sessions(
    client: httpx.AsyncClient, csrf: str, base_url: str, count: int
) -> list[str]:
    sessions: list[str] = []
    for _ in range(count):
        response = await client.post(
            "/api/personal/chat/sessions",
            headers={"Origin": base_url, "X-CSRF-Token": csrf},
            json={"title": "Synthetic benchmark"},
        )
        response.raise_for_status()
        session_id = response.json().get("id")
        if not isinstance(session_id, str):
            raise BenchmarkInputError
        sessions.append(session_id)
    return sessions


async def _measure_full_chat(
    client: httpx.AsyncClient,
    csrf: str,
    base_url: str,
    session_id: str,
    ordinal: int,
    limiter: anyio.CapacityLimiter,
    measurements: list[_Measurement],
) -> None:
    started = time.perf_counter()
    status_code = 0
    failed = True
    async with limiter:
        try:
            response = await client.post(
                "/api/personal/chat/send",
                headers={"Origin": base_url, "X-CSRF-Token": csrf},
                json={
                    "content": "Summarize the indexed synthetic QA fixture.",
                    "message_id": f"benchmark-{ordinal}",
                    "session_id": session_id,
                },
            )
            status_code = response.status_code
            failed = status_code != 200 or "event: done" not in response.text
        except httpx.HTTPError:
            failed = True
    measurements.append(((time.perf_counter() - started) * 1000, status_code, failed))


def _status_counts(measurements: list[_Measurement]) -> dict[str, int]:
    statuses: dict[str, int] = {}
    for _, status_code, _ in measurements:
        key = str(status_code)
        statuses[key] = statuses.get(key, 0) + 1
    return statuses


def _run_internal_process(
    args: argparse.Namespace, handoff: RedactedHandoff
) -> MetricReport:
    command = [
        str(args.docker_cli),
        "exec",
        f"{handoff.project_label}-rag-studio-saas-1",
        "python",
        _CONTAINER_SCRIPT,
        "--internal-plan",
        _CONTAINER_PLAN,
        "--identities",
        str(args.identities),
        "--concurrency",
        str(args.concurrency),
        "--requests-per-identity",
        str(args.requests_per_identity),
    ]
    try:
        completed = subprocess.run(
            command, capture_output=True, text=True, timeout=180, check=False
        )
        payload = _METRIC_REPORT.validate_json(completed.stdout)
    except OSError, subprocess.SubprocessError, ValidationError:
        raise BenchmarkInputError from None
    if completed.returncode not in (0, 1):
        raise BenchmarkInputError
    return payload


async def _run_host(args: argparse.Namespace) -> BenchmarkReport:
    handoff = load_handoff(args.handoff)
    identities = _load_private_handoff(_private_handoff_path(args.handoff), handoff)
    plan = _load_retrieval_plan(args.private_plan)
    if tuple(item.handle for item in plan) != handoff.fixture_identity_handles:
        raise BenchmarkInputError
    scoped_retrieval = await anyio.to_thread.run_sync(
        partial(_run_internal_process, args, handoff)
    )
    clients: list[httpx.AsyncClient] = []
    measurements: list[_Measurement] = []
    try:
        runtimes: list[tuple[httpx.AsyncClient, str, list[str]]] = []
        for identity in identities:
            client, csrf = await _sign_in(handoff.app_url, identity)
            clients.append(client)
            sessions = await _create_sessions(
                client, csrf, handoff.app_url, args.requests_per_identity
            )
            runtimes.append((client, csrf, sessions))
        limiter = anyio.CapacityLimiter(args.concurrency)
        async with anyio.create_task_group() as tasks:
            ordinal = 0
            for index in range(args.requests_per_identity):
                for client, csrf, sessions in runtimes:
                    tasks.start_soon(
                        _measure_full_chat,
                        client,
                        csrf,
                        handoff.app_url,
                        sessions[index],
                        ordinal,
                        limiter,
                        measurements,
                    )
                    ordinal += 1
    finally:
        for client in clients:
            await client.aclose()
    full_chat = build_metric(
        latencies_ms=[item[0] for item in measurements],
        errors=sum(item[2] for item in measurements),
        status_counts=_status_counts(measurements),
    )
    return build_report(
        args.handoff,
        identities=args.identities,
        concurrency=args.concurrency,
        requests_per_identity=args.requests_per_identity,
        scoped_retrieval=scoped_retrieval,
        full_chat=full_chat,
    )


async def _measure_retrieval(
    prepared: _PreparedRetrieval,
    limiter: anyio.CapacityLimiter,
    measurements: list[_Measurement],
) -> None:
    from src.retrieve.orchestrator import hybrid_search

    entry, store, dense, sparse = prepared
    async with limiter:
        started = time.perf_counter()
        results = await hybrid_search(
            entry.query,
            list(dense.values),
            list(sparse.indices),
            list(sparse.values),
            top_k=5,
            use_reranker=True,
            vector_searcher=store,
        )
        failed = not results or any(
            not isinstance(item.get("metadata"), dict)
            or item["metadata"].get("source") != entry.expected_filename
            for item in results
        )
        elapsed = (time.perf_counter() - started) * 1000
    measurements.append((elapsed, 500 if failed else 200, failed))


async def _run_internal(args: argparse.Namespace) -> MetricReport:
    from src.api.personal_lab_scope import PersonalLabScope
    from src.graph.personal_lab_execution import _personal_graph_vector_store
    from src.ingestion.embedder import get_embedder

    plan = _load_retrieval_plan(args.internal_plan)
    embedder = get_embedder()
    prepared: list[_PreparedRetrieval] = []
    for entry in plan:
        scope = PersonalLabScope(
            entry.scope_id,
            entry.namespace,
            Path("/app/data/personal-labs") / entry.namespace,
            entry.namespace,
        )
        store = await _personal_graph_vector_store(scope)
        dense = embedder.embed_dense((entry.query,))[0]
        sparse = embedder.embed_sparse((entry.query,))[0]
        prepared.append((entry, store, dense, sparse))
    measurements: list[_Measurement] = []
    limiter = anyio.CapacityLimiter(args.concurrency)
    async with anyio.create_task_group() as tasks:
        for _ in range(args.requests_per_identity):
            for item in prepared:
                tasks.start_soon(_measure_retrieval, item, limiter, measurements)
    return build_metric(
        latencies_ms=[item[0] for item in measurements],
        errors=sum(item[2] for item in measurements),
        status_counts=_status_counts(measurements),
        threshold_ms=3000.0,
    )


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--handoff", type=Path)
    parser.add_argument("--private-plan", type=Path)
    parser.add_argument("--internal-plan", type=Path)
    parser.add_argument("--docker-cli", type=Path)
    parser.add_argument("--identities", type=int, required=True)
    parser.add_argument("--concurrency", type=int, required=True)
    parser.add_argument("--requests-per-identity", type=int, required=True)
    parser.add_argument("--report", type=Path)
    return parser.parse_args()


def main() -> int:
    args = _arguments()
    try:
        if args.internal_plan is not None:
            internal_report = anyio.run(_run_internal, args)
            print(json.dumps(internal_report, sort_keys=True))
            return 0 if internal_report["passed"] else 1
        if any(
            value is None
            for value in (args.handoff, args.private_plan, args.docker_cli, args.report)
        ):
            raise BenchmarkInputError
        host_report = anyio.run(_run_host, args)
    except BenchmarkInputError, httpx.HTTPError:
        return 2
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(host_report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(host_report, sort_keys=True))
    return 0 if host_report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
