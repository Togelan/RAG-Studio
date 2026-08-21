from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import cast
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from src.api.dependencies import get_vector_store
from src.api.main import _mount_authenticated_personal_lab_routes
from src.api.saas_auth_context import AuthContext, BffAuthContextResolver
from src.api.saas_security import SaasCsrfMiddleware
from src.vector_store.pagination import ListingPage


@dataclass(slots=True)
class SessionAuthority:
    allowed: bool
    paths: list[str] = field(default_factory=list)

    async def resolve(
        self, request: Request, *, require_workspace: bool
    ) -> AuthContext:
        assert require_workspace is False
        path = request.url.path
        self.paths.append(path)
        if not self.allowed:
            raise HTTPException(status_code=401, detail="Authentication required.")
        return cast(AuthContext, object())


class EmptyVectorStore:
    async def list_documents(self, cursor: str | None = None) -> ListingPage:
        assert cursor is None
        return ListingPage((), None, False, 0, 0)


@pytest.mark.parametrize(
    "path", ("/api/settings", "/api/ingest/documents", "/api/chat/sessions")
)
def test_personal_lab_browser_routes_require_current_bff_session(path: str) -> None:
    authority = SessionAuthority(allowed=False)
    app = FastAPI()
    _mount_authenticated_personal_lab_routes(
        app, cast(BffAuthContextResolver, authority)
    )

    with TestClient(app, base_url="https://testserver") as client:
        response = client.get(path)

    assert response.status_code == 401
    assert authority.paths == [path]


def test_authenticated_personal_lab_browser_routes_reach_real_handlers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("RAG_STUDIO_DATA_ROOT", str(tmp_path))
    authority = SessionAuthority(allowed=True)
    app = FastAPI()
    app.dependency_overrides[get_vector_store] = lambda: EmptyVectorStore()
    _mount_authenticated_personal_lab_routes(
        app, cast(BffAuthContextResolver, authority)
    )

    with (
        patch("src.api.routes.chat.get_graph", return_value=object()),
        patch(
            "src.api.routes.chat.list_all_sessions",
            new_callable=AsyncMock,
            return_value=[],
        ),
        TestClient(app, base_url="https://testserver") as client,
    ):
        responses = [
            client.get(path)
            for path in (
                "/api/settings",
                "/api/ingest/documents",
                "/api/chat/sessions",
            )
        ]

    assert [response.status_code for response in responses] == [200, 200, 200]
    assert authority.paths == [
        "/api/settings",
        "/api/ingest/documents",
        "/api/chat/sessions",
    ]


@pytest.mark.parametrize(
    "path", ("/api/settings", "/api/ingest/upload", "/api/chat/sessions")
)
def test_personal_lab_mutations_require_csrf_and_trusted_origin(path: str) -> None:
    calls: list[str] = []
    app = FastAPI()
    app.add_middleware(
        SaasCsrfMiddleware,
        trusted_origins=("https://testserver",),
        protected_roots=("/api/saas", "/api/settings", "/api/ingest", "/api/chat"),
    )

    @app.post(path)
    async def sentinel() -> dict[str, bool]:
        calls.append(path)
        return {"ok": True}

    with TestClient(app, base_url="https://testserver") as client:
        missing = client.post(path)
        client.cookies.set("__Host-ragstudio-csrf", "cookie-token")
        mismatched = client.post(path, headers={"X-CSRF-Token": "other-token"})
        hostile = client.post(
            path,
            headers={
                "X-CSRF-Token": "cookie-token",
                "Origin": "https://evil.example.test",
            },
        )
        accepted = client.post(
            path,
            headers={
                "X-CSRF-Token": "cookie-token",
                "Origin": "https://testserver",
            },
        )

    assert [missing.status_code, mismatched.status_code, hostile.status_code] == [
        403,
        403,
        403,
    ]
    assert accepted.status_code == 200
    assert calls == [path]
