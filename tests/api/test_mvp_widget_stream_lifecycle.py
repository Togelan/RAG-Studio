from __future__ import annotations

from collections.abc import AsyncIterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from uuid import UUID

import anyio
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.mvp_public_admission import BurstRateLimiter, PublicAdmissionAuthority
from src.api.mvp_public_execution import PublicExecutionScopeResolver
from src.api.mvp_public_proof import PublicProofSigner
from src.api.personal_lab_scope import PersonalLabScope
from src.api.public_stream_jobs import PublicStreamJobRegistry, PublicStreamKey
from src.api.routes.mvp_public import create_mvp_public_router
from src.api.routes.mvp_public_stream import _Handlers, create_mvp_public_stream_router
from src.graph.public_personal_lab_execution import PublicToken
from tests.api.test_mvp_widget_stream import (
    KEY,
    NOW,
    ORIGIN,
    PUBLICATION,
    SIGNING_KEY,
    _AdmissionStore,
    _events,
    _Executor,
    _fixture,
    _proof,
    _ScopeSource,
)


class _ActiveExecutor:
    def __init__(self) -> None:
        self.started = Event()

    async def __call__(
        self, scope: PersonalLabScope, query: str, session_id: str
    ) -> AsyncIterator[PublicToken]:
        del scope, query, session_id
        self.started.set()
        await anyio.sleep_forever()
        yield PublicToken("unreachable")


@pytest.mark.anyio
async def test_disconnect_releases_reservation_and_removes_public_job(
    tmp_path: Path,
) -> None:
    store = _AdmissionStore()
    authority = PublicAdmissionAuthority(
        True,
        store,
        PublicProofSigner(SIGNING_KEY),
        BurstRateLimiter(limit=10, window_seconds=60, capacity=10),
    )
    source = _ScopeSource()
    resolver = PublicExecutionScopeResolver(source, tmp_path)
    jobs = PublicStreamJobRegistry()
    executor = _Executor()
    proof = await authority.issue(KEY, ORIGIN, NOW)
    admission = await authority.admit(KEY, ORIGIN, proof.proof, "198.51.100.1", NOW)
    scope = await resolver.resolve(admission)
    key = PublicStreamKey(PUBLICATION, admission.session_id)
    lease = await jobs.acquire(key)
    handlers = _Handlers(authority, resolver, jobs, executor, lambda: NOW)
    events = handlers._events(lease, scope, "question", admission.reservation_id)

    first = await anext(events)
    await events.aclose()

    assert first.startswith("event: start")
    assert store.reservations[admission.reservation_id] == "released"
    assert executor.calls == []
    assert not await jobs.cancel(key)
    assert list(tmp_path.rglob("*.sqlite")) == []


@pytest.mark.anyio
async def test_repeated_public_cancellation_is_idempotent() -> None:
    jobs = PublicStreamJobRegistry()
    key = PublicStreamKey(PUBLICATION, KEY)
    lease = await jobs.acquire(key)

    first = await jobs.cancel(key)
    second = await jobs.cancel(key)
    await jobs.release(lease)
    after_release = await jobs.cancel(key)

    assert first and second
    assert lease.cancel_scope.cancel_called
    assert not after_release


def test_capacity_releases_reservation_before_execution(tmp_path: Path) -> None:
    client, store, _, executor, _, jobs = _fixture(tmp_path, capacity=1)
    occupied = PublicStreamKey(UUID(int=90), UUID(int=91))
    lease = anyio.run(jobs.acquire, occupied)
    with client:
        response = client.post(
            f"/api/public/widgets/{KEY}/streams",
            json={"proof": _proof(client), "message": "question"},
            headers={"Origin": ORIGIN},
        )
    anyio.run(jobs.release, lease)

    assert response.status_code == 503
    assert response.headers["retry-after"] == "1"
    assert executor.calls == []
    assert set(store.reservations.values()) == {"released"}


def test_stream_preflight_echoes_only_the_verified_origin(tmp_path: Path) -> None:
    client, _, _, executor, _, _ = _fixture(tmp_path)
    with client:
        allowed = client.options(
            f"/api/public/widgets/{KEY}/streams",
            headers={"Origin": ORIGIN, "Access-Control-Request-Method": "POST"},
        )
        hostile = client.options(
            f"/api/public/widgets/{KEY}/streams",
            headers={
                "Origin": "https://attacker.example.test",
                "Access-Control-Request-Method": "POST",
            },
        )

    assert allowed.status_code == 204
    assert allowed.headers["access-control-allow-origin"] == ORIGIN
    assert hostile.status_code == 403
    assert "access-control-allow-origin" not in hostile.headers
    assert executor.calls == []


def test_active_http_cancel_releases_without_durable_history(tmp_path: Path) -> None:
    store = _AdmissionStore()
    authority = PublicAdmissionAuthority(
        True,
        store,
        PublicProofSigner(SIGNING_KEY),
        BurstRateLimiter(limit=10, window_seconds=60, capacity=10),
    )
    executor = _ActiveExecutor()
    jobs = PublicStreamJobRegistry()
    app = FastAPI()
    app.include_router(create_mvp_public_router(authority, clock=lambda: NOW))
    app.include_router(
        create_mvp_public_stream_router(
            authority,
            PublicExecutionScopeResolver(_ScopeSource(), tmp_path),
            jobs,
            execute=executor,
            clock=lambda: NOW,
        )
    )
    client = TestClient(app)
    with client:
        proof_response = client.post(
            f"/api/public/widgets/{KEY}/proof",
            json={},
            headers={"Origin": ORIGIN},
        )
        proof = str(proof_response.json()["proof"])
        session_id = str(proof_response.json()["session_id"])
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(
                client.post,
                f"/api/public/widgets/{KEY}/streams",
                json={"proof": proof, "message": "active cancellation"},
                headers={"Origin": ORIGIN},
            )
            started = executor.started.wait(timeout=5)
            canceled = client.post(
                f"/api/public/widgets/{KEY}/streams/{session_id}/cancel",
                json={"proof": proof},
                headers={"Origin": ORIGIN},
            )
            streamed = future.result(timeout=5)

    assert started
    assert canceled.status_code == 200
    assert canceled.json() == {"status": "stopped"}
    assert [event for event, _ in _events(streamed.text)] == ["start", "error"]
    assert set(store.reservations.values()) == {"released"}
    assert list(tmp_path.rglob("*.sqlite")) == []
