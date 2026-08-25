from __future__ import annotations

import importlib
import json
import socket
import threading
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import pytest
import uvicorn
from fastapi import FastAPI, HTTPException, Request

from src.api.main import create_app


class FakeScopeRegistry:
    def __init__(self) -> None:
        self._scopes: dict[UUID, UUID] = {}

    async def resolve(self, user_id: UUID) -> UUID:
        return self._scopes.setdefault(user_id, uuid4())


@dataclass(frozen=True, slots=True)
class LiveClaims:
    user_id: UUID


@dataclass(frozen=True, slots=True)
class LiveAuthResult:
    claims: LiveClaims


@dataclass(frozen=True, slots=True)
class CookieAuthContext:
    identities: dict[str, UUID]

    async def resolve(self, request: Request, *, require_workspace: bool):
        del require_workspace
        user_id = self.identities.get(request.cookies.get("identity", ""))
        if user_id is None:
            raise HTTPException(status_code=401, detail="Authentication required.")
        return LiveAuthResult(LiveClaims(user_id))


@pytest.mark.asyncio
async def test_two_identities_resolve_stable_distinct_opaque_scopes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # Given: two authenticated identities and one durable registry authority.
    module = importlib.import_module("src.api.personal_lab_scope")
    registry = FakeScopeRegistry()
    first_user = uuid4()
    second_user = uuid4()

    # When: independent resolver instances model restart and key rotation.
    first_resolver = module.PersonalLabScopeResolver(registry, tmp_path)
    monkeypatch.setenv(
        "RAG_STUDIO_SESSION_ENCRYPTION_KEYS",
        "before:AQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQE",
    )
    first_scope = await first_resolver.resolve(first_user)
    repeated_scope = await first_resolver.resolve(first_user)
    monkeypatch.setenv(
        "RAG_STUDIO_SESSION_ENCRYPTION_KEYS",
        "after:AgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgI",
    )
    restarted_scope = await module.PersonalLabScopeResolver(registry, tmp_path).resolve(
        first_user
    )
    second_scope = await first_resolver.resolve(second_user)

    # Then: persistence, not an encryption key, owns the opaque namespace.
    assert first_scope == repeated_scope == restarted_scope
    assert first_scope.id != second_scope.id
    assert first_scope.namespace == f"pl_{first_scope.id.hex}"
    assert first_scope.collection_name == first_scope.namespace
    assert first_scope.data_root == tmp_path / first_scope.namespace
    assert str(first_user).replace("-", "") not in first_scope.namespace


def test_router_registry_requires_explicit_unique_registration() -> None:
    # Given: an empty declarative Personal Lab router registry.
    module = importlib.import_module("src.api.personal_lab_registry")
    registry = module.PersonalLabRouterRegistry()

    def leaf_factory(dependencies):
        del dependencies
        return module.APIRouter()

    # When: one leaf is registered explicitly.
    registry.register("knowledge", leaf_factory)

    # Then: its registration is inspectable and duplicate names fail closed.
    assert registry.names == ("knowledge",)
    with pytest.raises(module.PersonalLabRouterRegistrationError):
        registry.register("knowledge", leaf_factory)


def test_live_saas_react_http_sequence_proves_scope_and_route_partition(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    record_property: pytest.RecordProperty,
) -> None:
    # Given: a valid SaaS+React app served on a task-owned loopback port.
    from src.api.personal_lab_registry import PersonalLabRouteDependencies
    from src.api.personal_lab_scope import PersonalLabScopeResolver
    from src.api.routes.personal_lab import create_personal_lab_router

    react_dist = tmp_path / "react-dist"
    _write_react_dist(react_dist)
    _configure_saas(monkeypatch, tmp_path)
    monkeypatch.setenv("RAG_STUDIO_UI_MODE", "react")
    monkeypatch.setenv("RAG_STUDIO_REACT_DIST", str(react_dist))
    auth = CookieAuthContext({"a": uuid4(), "b": uuid4()})
    scopes = PersonalLabScopeResolver(FakeScopeRegistry(), tmp_path / "personal")

    def mount_personal(app: FastAPI, runtime) -> CookieAuthContext:
        del runtime
        app.include_router(
            create_personal_lab_router(PersonalLabRouteDependencies(auth, scopes))
        )
        return auth

    monkeypatch.setattr("src.api.main.mount_saas_routes", mount_personal)
    server, thread, base_url = _start_live_server(create_app())
    try:
        with httpx.Client(base_url=base_url, timeout=5.0) as client:
            first = client.get(
                "/api/personal/context?scope_id=ffffffff-ffff-4fff-8fff-ffffffffffff",
                headers={"X-Personal-Lab-ID": "ffffffff-ffff-4fff-8fff-ffffffffffff"},
                cookies={"identity": "a"},
            )
            repeated = client.get("/api/personal/context", cookies={"identity": "a"})
            second = client.get("/api/personal/context", cookies={"identity": "b"})
            expired = client.get(
                "/api/personal/context", cookies={"identity": "expired"}
            )
            legacy_settings = client.get("/api/settings")
            knowledge = client.get("/app/knowledge")
            health = client.get("/health")

        # When/Then: HTTP observables match the frozen mode and authority contract.
        assert first.status_code == repeated.status_code == second.status_code == 200
        assert first.json() == repeated.json()
        assert first.json()["id"] != second.json()["id"]
        assert expired.status_code == 401
        assert legacy_settings.status_code == 404
        assert knowledge.status_code == 200
        assert 'data-group2-react="true"' in knowledge.text
        assert health.status_code == 200
        assert health.json() == {"status": "ok"}
        record_property("url", base_url)
        record_property("scope_statuses", "200,200,200")
        record_property("distinct_scopes", "true")
        record_property("expired_status", "401")
        record_property("legacy_settings_status", "404")
        record_property("knowledge_status", "200")
        record_property("health_status", "200")
    finally:
        server.should_exit = True
        thread.join(timeout=10.0)
        assert not thread.is_alive()


def _write_react_dist(root: Path) -> None:
    (root / ".vite").mkdir(parents=True)
    (root / "assets").mkdir()
    (root / "index.html").write_text(
        '<main data-group2-react="true"></main>', encoding="utf-8"
    )
    (root / "assets" / "app.js").write_text("export {};", encoding="utf-8")
    (root / ".vite" / "manifest.json").write_text(
        json.dumps({"src/main.tsx": {"file": "assets/app.js"}}), encoding="utf-8"
    )


def _configure_saas(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("RAG_STUDIO_RUNTIME_MODE", "saas")
    monkeypatch.setenv("RAG_STUDIO_DATA_ROOT", str(tmp_path / "saas-data"))
    monkeypatch.setenv("RAG_STUDIO_SUPABASE_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("RAG_STUDIO_SUPABASE_JWT_ISSUER", "http://127.0.0.1:9/auth/v1")
    monkeypatch.setenv("RAG_STUDIO_SUPABASE_JWT_AUDIENCE", "authenticated")
    monkeypatch.setenv("RAG_STUDIO_SUPABASE_DATABASE_URL", "postgresql://invalid/db")
    monkeypatch.setenv("RAG_STUDIO_SESSION_SIGNING_KEY", "x" * 32)
    monkeypatch.setenv(
        "RAG_STUDIO_SESSION_ENCRYPTION_KEYS",
        "v1:AQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQE",
    )
    monkeypatch.setenv("QDRANT_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("RAG_STUDIO_CORS_ORIGINS", "https://testserver")


def _start_live_server(app: FastAPI) -> tuple[uvicorn.Server, threading.Thread, str]:
    with socket.socket() as port_probe:
        port_probe.bind(("127.0.0.1", 0))
        port = port_probe.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host="127.0.0.1",
            port=port,
            lifespan="off",
            log_level="error",
        )
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(1000):
        if server.started:
            break
        thread.join(timeout=0.01)
    assert server.started
    return server, thread, f"http://127.0.0.1:{port}"
