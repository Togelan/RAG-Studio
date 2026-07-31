"""Real-socket deterministic benchmark for bounded chat SSE streaming."""

from __future__ import annotations

import argparse
import asyncio
import ctypes
import json
import os
import socket
import statistics
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from ctypes import wintypes
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import uvicorn

from src.api.chat_stream import MAX_CONCURRENT_STREAMS, StreamLifecycleManager


class _BenchmarkProvider:
    """Delayed fake provider with observable concurrency and completion gates."""

    def __init__(self) -> None:
        self.active = 0
        self.max_active = 0
        self._lock = asyncio.Lock()
        self.all_started = asyncio.Event()
        self.release = asyncio.Event()

    async def stream(
        self, *_args: Any, **_kwargs: Any
    ) -> AsyncIterator[dict[str, Any]]:
        async with self._lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            if self.active == MAX_CONCURRENT_STREAMS:
                self.all_started.set()
        try:
            await asyncio.sleep(0.02)
            yield {"type": "token", "token": "provider-token"}
            await self.release.wait()
            await asyncio.sleep(0.03)
            yield {
                "type": "result",
                "result": {
                    "final_answer": "provider-token",
                    "generated_from": "retrieval",
                    "faithfulness_score": 1.0,
                    "retrieved_docs": [],
                    "citations": [],
                },
            }
        finally:
            async with self._lock:
                self.active -= 1


@asynccontextmanager
async def _fake_graph(*_args: Any, **_kwargs: Any) -> AsyncIterator[object]:
    yield object()


def _rss_bytes() -> int:
    """Return this process's Windows working-set size without dependencies."""

    class ProcessMemoryCounters(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("page_fault_count", wintypes.DWORD),
            ("peak_working_set_size", ctypes.c_size_t),
            ("working_set_size", ctypes.c_size_t),
            ("quota_peak_paged_pool_usage", ctypes.c_size_t),
            ("quota_paged_pool_usage", ctypes.c_size_t),
            ("quota_peak_non_paged_pool_usage", ctypes.c_size_t),
            ("quota_non_paged_pool_usage", ctypes.c_size_t),
            ("pagefile_usage", ctypes.c_size_t),
            ("peak_pagefile_usage", ctypes.c_size_t),
        ]

    counters = ProcessMemoryCounters()
    counters.cb = ctypes.sizeof(counters)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    get_memory_info = kernel32.K32GetProcessMemoryInfo
    get_memory_info.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(ProcessMemoryCounters),
        wintypes.DWORD,
    ]
    get_memory_info.restype = wintypes.BOOL
    handle = kernel32.GetCurrentProcess()
    ok = get_memory_info(
        handle,
        ctypes.byref(counters),
        counters.cb,
    )
    return int(counters.working_set_size) if ok else 0


def _percentile(values: list[float], percentile: float) -> float:
    """Return a nearest-rank percentile for a non-empty sample."""
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * percentile)))
    return ordered[index]


async def _consume_stream(
    client: httpx.AsyncClient,
    session_id: str,
) -> dict[str, float | int]:
    started = time.perf_counter()
    first_token: float | None = None
    current_event = "message"
    status = 0
    async with client.stream(
        "POST",
        "/api/chat/send",
        json={"content": "benchmark", "session_id": session_id},
    ) as response:
        status = response.status_code
        async for line in response.aiter_lines():
            if line.startswith("event: "):
                current_event = line.removeprefix("event: ")
            elif (
                line.startswith("data: ")
                and current_event == "token"
                and first_token is None
            ):
                first_token = time.perf_counter()
    completed = time.perf_counter()
    if first_token is None:
        raise AssertionError(f"No provider token for {session_id}")
    return {
        "status": status,
        "ttft_ms": (first_token - started) * 1000,
        "total_ms": (completed - started) * 1000,
    }


async def run_benchmark(data_root: Path) -> dict[str, Any]:
    """Run ten streams plus conflict/overflow requests against real sockets."""
    data_root.mkdir(parents=True, exist_ok=True)
    os.environ["RAG_STUDIO_DATA_ROOT"] = str(data_root)

    from src.api import dependencies
    from src.api.main import create_app
    from src.api.routes import chat

    dependencies._audit_logger = None  # pyright: ignore[reportPrivateUsage]
    chat._stream_lifecycle = StreamLifecycleManager()  # pyright: ignore[reportPrivateUsage]
    provider = _BenchmarkProvider()

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(128)
    port = int(listener.getsockname()[1])

    with (
        patch("src.api.main.wait_for_qdrant_ready", new=AsyncMock(return_value=True)),
        patch("src.api.main.close_qdrant_client", new=AsyncMock(return_value=None)),
        patch("src.api.main.create_graph", new=_fake_graph),
        patch("src.api.routes.chat.stream_rag_graph", new=provider.stream),
    ):
        server = uvicorn.Server(
            uvicorn.Config(create_app(), log_level="error", lifespan="on")
        )
        server_task = asyncio.create_task(server.serve(sockets=[listener]))
        try:
            for _ in range(200):
                if server.started:
                    break
                await asyncio.sleep(0.01)
            if not server.started:
                raise RuntimeError("Benchmark server did not start")

            async with httpx.AsyncClient(
                base_url=f"http://127.0.0.1:{port}",
                timeout=10.0,
                trust_env=False,
            ) as client:
                tasks = [
                    asyncio.create_task(_consume_stream(client, f"load-{index}"))
                    for index in range(MAX_CONCURRENT_STREAMS)
                ]
                await asyncio.wait_for(provider.all_started.wait(), timeout=5.0)
                overflow = await client.post(
                    "/api/chat/send",
                    json={"content": "overflow", "session_id": "overflow"},
                )
                conflict = await client.post(
                    "/api/chat/send",
                    json={"content": "duplicate", "session_id": "load-0"},
                )
                provider.release.set()
                results = await asyncio.gather(*tasks)
        finally:
            provider.release.set()
            server.should_exit = True
            await server_task
            listener.close()

    ttft = [float(item["ttft_ms"]) for item in results]
    totals = [float(item["total_ms"]) for item in results]
    report = {
        "sessions": len(results),
        "statuses": [int(item["status"]) for item in results],
        "ttft_ms": {
            "p50": round(statistics.median(ttft), 2),
            "p95": round(_percentile(ttft, 0.95), 2),
        },
        "end_to_end_ms": {"p95": round(_percentile(totals, 0.95), 2)},
        "max_active_streams": provider.max_active,
        "overflow_status": overflow.status_code,
        "overflow_retry_after": overflow.headers.get("Retry-After"),
        "same_session_status": conflict.status_code,
        "rss_bytes": _rss_bytes(),
    }
    assert report["sessions"] == MAX_CONCURRENT_STREAMS
    assert report["statuses"] == [200] * MAX_CONCURRENT_STREAMS
    assert report["max_active_streams"] <= MAX_CONCURRENT_STREAMS
    assert report["overflow_status"] == 503
    assert str(report["overflow_retry_after"]).isdigit()
    assert report["same_session_status"] == 409
    assert report["ttft_ms"]["p95"] < report["end_to_end_ms"]["p95"]
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = asyncio.run(run_benchmark(args.data_root))
    serialized = json.dumps(report, indent=2, sort_keys=True)
    print(serialized)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
