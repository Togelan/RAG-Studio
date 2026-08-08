"""Run an informational local Qdrant benchmark for mixed chunking strategies."""

from __future__ import annotations

import argparse
import json
import platform
import statistics
import time
from pathlib import Path

from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels

_COLLECTION = "chunking_strategy_benchmark"
_STRATEGIES = ("static", "recursive", "parent_document", "sentence_window")
_VECTOR = (1.0, 0.0, 0.0, 0.0)


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, round((len(ordered) - 1) * percentile))
    return ordered[index]


def _points(start: int, count: int) -> list[qmodels.PointStruct]:
    return [
        qmodels.PointStruct(
            id=index,
            vector=_VECTOR,
            payload={
                "doc_id": f"benchmark-doc-{index // 10}",
                "strategy": _STRATEGIES[index % len(_STRATEGIES)],
                "schema_version": 1,
                "text": f"Benchmark context unit {index}.",
                "start_offset": index * 10,
                "end_offset": index * 10 + 9,
            },
        )
        for index in range(start, start + count)
    ]


def _storage_bytes(data_root: Path) -> int:
    """Return the size of the isolated Qdrant storage directory."""
    return sum(path.stat().st_size for path in data_root.rglob("*") if path.is_file())


def _cgroup_memory_bytes() -> dict[str, int | None]:
    """Read Linux cgroup memory counters when the benchmark runs in Docker."""
    cgroup_root = Path("/sys/fs/cgroup")

    def read_counter(name: str) -> int | None:
        try:
            return int((cgroup_root / name).read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            return None

    return {
        "current": read_counter("memory.current"),
        "peak": read_counter("memory.peak"),
        "limit": read_counter("memory.max"),
    }


def run_benchmark(data_root: Path, points: int, queries: int) -> dict[str, object]:
    if points < 1 or queries < 1:
        raise ValueError("points_and_queries_must_be_positive")
    data_root.mkdir(parents=True, exist_ok=True)
    client = QdrantClient(path=str(data_root))
    try:
        if client.collection_exists(_COLLECTION):
            client.delete_collection(_COLLECTION)
        client.create_collection(
            collection_name=_COLLECTION,
            vectors_config=qmodels.VectorParams(
                size=4, distance=qmodels.Distance.COSINE
            ),
        )
        started = time.perf_counter()
        batch_size = 1_000
        for start in range(0, points, batch_size):
            client.upsert(
                collection_name=_COLLECTION,
                points=_points(start, min(batch_size, points - start)),
                wait=True,
            )
        ingestion_seconds = time.perf_counter() - started
        latencies: list[float] = []
        for _ in range(queries):
            query_started = time.perf_counter()
            client.query_points(
                collection_name=_COLLECTION,
                query=list(_VECTOR),
                limit=5,
                with_payload=True,
            )
            latencies.append((time.perf_counter() - query_started) * 1_000)
        distribution = {
            strategy: points // len(_STRATEGIES)
            + (1 if position < points % len(_STRATEGIES) else 0)
            for position, strategy in enumerate(_STRATEGIES)
        }
        return {
            "informational": True,
            "compose_profile": {"memory": "4g", "cpus": "2"},
            "host": {
                "platform": platform.platform(),
                "python": platform.python_version(),
            },
            "point_count": points,
            "query_count": queries,
            "strategy_distribution": distribution,
            "ingestion_seconds": round(ingestion_seconds, 3),
            "storage_bytes": _storage_bytes(data_root),
            "memory_bytes": _cgroup_memory_bytes(),
            "retrieval_ms": {
                "p50": round(statistics.median(latencies), 3),
                "p95": round(_percentile(latencies, 0.95), 3),
            },
            "failure_behavior": "completed",
        }
    finally:
        client.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--points", type=int, default=50_000)
    parser.add_argument("--queries", type=int, default=50)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = run_benchmark(args.data_root, args.points, args.queries)
    serialized = json.dumps(report, indent=2, sort_keys=True)
    print(serialized)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
