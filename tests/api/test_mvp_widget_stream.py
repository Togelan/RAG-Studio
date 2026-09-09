from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.mvp_public_admission import (
    BurstRateLimiter,
    PublicAdmissionAuthority,
    PublicAuthoritySnapshot,
    ReservationOutcome,
)
from src.api.mvp_public_execution import PublicExecutionScopeResolver
from src.api.mvp_public_proof import PublicProofSigner
from src.api.mvp_publication import PublicationState
from src.api.mvp_publication_origin import canonicalize_origin
from src.api.personal_chat_state import project_safe_citation
from src.api.personal_lab_scope import PersonalLabScope
from src.api.public_stream_jobs import PublicStreamJobRegistry
from src.api.routes.mvp_public import create_mvp_public_router
from src.api.routes.mvp_public_stream import create_mvp_public_stream_router
from src.graph.public_personal_lab_execution import PublicResult, PublicToken
from src.vector_store.models import JsonValue

NOW = datetime(2026, 8, 25, 12, 0, tzinfo=UTC)
PUBLICATION = UUID("10000000-0000-4000-8000-000000000001")
KEY = UUID("20000000-0000-4000-8000-000000000002")
LAB = UUID("30000000-0000-4000-8000-000000000003")
ORIGIN = "https://widget.example.test"
SIGNING_KEY = b"proof-key-material-that-is-at-least-32"


class _AdmissionStore:
    def __init__(self) -> None:
        self.state = PublicationState.ENABLED
        self.entitled = True
        self.reservations: dict[UUID, str] = {}

    async def resolve(self, public_key: UUID) -> PublicAuthoritySnapshot | None:
        if public_key != KEY:
            return None
        return PublicAuthoritySnapshot(
            PUBLICATION, 1, canonicalize_origin(ORIGIN), self.state, self.entitled
        )

    async def reserve_once(
        self, publication_id: UUID, reservation_id: UUID
    ) -> ReservationOutcome:
        if publication_id != PUBLICATION or reservation_id in self.reservations:
            return ReservationOutcome.REPLAYED
        self.reservations[reservation_id] = "reserved"
        return ReservationOutcome.ACCEPTED

    async def commit(self, reservation_id: UUID) -> bool:
        if self.reservations.get(reservation_id) != "reserved":
            return False
        self.reservations[reservation_id] = "committed"
        return True

    async def release(self, reservation_id: UUID) -> bool:
        if self.reservations.get(reservation_id) != "reserved":
            return False
        self.reservations[reservation_id] = "released"
        return True


class _ScopeSource:
    def __init__(self) -> None:
        self.enabled = True

    async def resolve_scope_id(self, publication_id: UUID) -> UUID | None:
        return LAB if self.enabled and publication_id == PUBLICATION else None


class _Executor:
    def __init__(self) -> None:
        self.calls: list[tuple[UUID, str, str]] = []
        self.failure: RuntimeError | None = None

    async def __call__(
        self, scope: PersonalLabScope, query: str, session_id: str
    ) -> AsyncIterator[PublicToken | PublicResult]:
        self.calls.append((scope.id, query, session_id))
        if self.failure is not None:
            raise self.failure
        yield PublicToken("grounded ")
        yield PublicToken("answer")
        yield PublicResult(
            (
                {
                    "filename": "guide.pdf",
                    "page": 2,
                    "chunk_text": "private source text",
                    "provider": "private-provider",
                },
            )
        )


def _fixture(
    tmp_path: Path, *, capacity: int = 10
) -> tuple[
    TestClient,
    _AdmissionStore,
    _ScopeSource,
    _Executor,
    PublicProofSigner,
    PublicStreamJobRegistry,
]:
    store = _AdmissionStore()
    signer = PublicProofSigner(SIGNING_KEY)
    authority = PublicAdmissionAuthority(
        True,
        store,
        signer,
        BurstRateLimiter(limit=20, window_seconds=60, capacity=100),
    )
    source = _ScopeSource()
    executor = _Executor()
    app = FastAPI()
    app.include_router(create_mvp_public_router(authority, clock=lambda: NOW))
    jobs = PublicStreamJobRegistry(capacity)
    app.include_router(
        create_mvp_public_stream_router(
            authority,
            PublicExecutionScopeResolver(source, tmp_path / "personal-labs"),
            jobs,
            execute=executor,
            clock=lambda: NOW,
        )
    )
    return TestClient(app), store, source, executor, signer, jobs


def _proof(client: TestClient) -> str:
    response = client.post(
        f"/api/public/widgets/{KEY}/proof", json={}, headers={"Origin": ORIGIN}
    )
    assert response.status_code == 200
    return str(response.json()["proof"])


def _events(body: str) -> list[tuple[str, dict[str, JsonValue]]]:
    blocks = [block for block in body.split("\n\n") if block]
    return [
        (block.splitlines()[0][7:], json.loads(block.splitlines()[1][6:]))
        for block in blocks
    ]


def test_private_citation_projection_is_the_public_redaction_contract() -> None:
    projected = project_safe_citation(
        {
            "filename": "guide.pdf",
            "page": 2,
            "chunk_text": "private source text",
            "provider": "private-provider",
        }
    )

    assert projected == {"filename": "guide.pdf", "page": 2}


def test_public_stream_orders_tokens_citations_done_with_server_scope(
    tmp_path: Path,
) -> None:
    client, store, _, executor, _, _ = _fixture(tmp_path)
    with client:
        response = client.post(
            f"/api/public/widgets/{KEY}/streams",
            json={"proof": _proof(client), "message": "question"},
            headers={"Origin": ORIGIN},
        )

    events = _events(response.text)
    assert response.status_code == 200
    assert [event for event, _ in events] == [
        "start",
        "token",
        "token",
        "citations",
        "done",
    ]
    assert events[3][1] == {"citations": [{"filename": "guide.pdf", "page": 2}]}
    assert executor.calls[0][0] == LAB
    assert executor.calls[0][1] == "question"
    assert executor.calls[0][2].startswith("widget:")
    assert set(store.reservations.values()) == {"committed"}
    assert not (tmp_path / "personal-labs" / f"pl_{LAB.hex}" / "chat.sqlite").exists()
    assert not (
        tmp_path / "personal-labs" / f"pl_{LAB.hex}" / "checkpoints.sqlite"
    ).exists()


def test_failure_is_sanitized_releases_and_never_writes_history(tmp_path: Path) -> None:
    client, store, _, executor, _, _ = _fixture(tmp_path)
    executor.failure = RuntimeError("provider-secret C:/private/checkpoints.sqlite")
    with client:
        response = client.post(
            f"/api/public/widgets/{KEY}/streams",
            json={"proof": _proof(client), "message": "explode"},
            headers={"Origin": ORIGIN},
        )

    assert _events(response.text) == [
        ("start", {"protocol": "1"}),
        (
            "error",
            {
                "code": "response_failed",
                "message": "Response could not be completed.",
                "retryable": True,
            },
        ),
    ]
    assert "provider-secret" not in response.text
    assert set(store.reservations.values()) == {"released"}
    assert list(tmp_path.rglob("*.sqlite")) == []


@pytest.mark.parametrize("case", ("bad_proof", "disabled", "stale_scope"))
def test_rejected_or_stale_authority_never_executes(case: str, tmp_path: Path) -> None:
    client, store, source, executor, _, _ = _fixture(tmp_path)
    with client:
        proof = _proof(client)
        if case == "bad_proof":
            proof += "forged"
        elif case == "disabled":
            store.state = PublicationState.DISABLED
        else:
            source.enabled = False
        response = client.post(
            f"/api/public/widgets/{KEY}/streams",
            json={"proof": proof, "message": "question"},
            headers={"Origin": ORIGIN},
        )

    assert response.status_code in {401, 403, 503}
    assert executor.calls == []
    assert "personal" not in response.text.lower()
    assert all(state != "reserved" for state in store.reservations.values())


def test_private_same_id_collision_is_isolated_and_replay_does_not_recommit(
    tmp_path: Path,
) -> None:
    client, store, _, executor, signer, _ = _fixture(tmp_path)
    session_id = UUID("40000000-0000-4000-8000-000000000004")
    private_root = tmp_path / "personal-labs" / f"pl_{LAB.hex}"
    private_root.mkdir(parents=True)
    private_checkpoint = private_root / "checkpoints.sqlite"
    private_checkpoint.write_bytes(b"private-marker")
    proof = signer.issue(PUBLICATION, 1, ORIGIN, NOW, session_id=session_id)
    with client:
        first = client.post(
            f"/api/public/widgets/{KEY}/streams",
            json={"proof": proof, "message": "question"},
            headers={"Origin": ORIGIN},
        )
        replay = client.post(
            f"/api/public/widgets/{KEY}/streams",
            json={"proof": proof, "message": "question"},
            headers={"Origin": ORIGIN},
        )

    assert first.status_code == 200 and replay.status_code == 401
    assert private_checkpoint.read_bytes() == b"private-marker"
    assert len(executor.calls) == 1
    assert list(store.reservations.values()) == ["committed"]
