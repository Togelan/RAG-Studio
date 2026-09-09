from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from pydantic import SecretStr

from src.api.billing_runtime import BillingConfiguration
from src.api.mvp_publication import (
    Publication,
    disable_publication,
    revoke_publication,
    rotate_public_key,
)
from src.api.mvp_publication import (
    publish as publish_domain,
)
from src.api.mvp_publication_store import PublicationStoreUnavailableError
from src.api.personal_lab_composition import mount_personal_lab_routes
from src.api.personal_lab_registry import PersonalLabRouteDependencies
from src.api.personal_lab_scope import PersonalLabScopeResolver
from src.api.routes.mvp_publication import create_mvp_publication_router
from src.api.saas_runtime import RuntimeConfiguration, RuntimeMode
from src.api.saas_security import SaasCsrfMiddleware

USER = UUID("11000000-0000-4000-8000-000000000001")
LAB = UUID("22000000-0000-4000-8000-000000000002")
PUBLICATION = UUID("33000000-0000-4000-8000-000000000003")
KEY_1 = UUID("44000000-0000-4000-8000-000000000004")
KEY_2 = UUID("55000000-0000-4000-8000-000000000005")
KEY_3 = UUID("66000000-0000-4000-8000-000000000006")
NOW = datetime(2026, 8, 25, 14, 0, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class _Claims:
    user_id: UUID


@dataclass(frozen=True, slots=True)
class _AuthResult:
    claims: _Claims


class _Auth:
    async def resolve(
        self, request: Request, *, require_workspace: bool
    ) -> _AuthResult:
        del require_workspace
        if request.cookies.get("identity") != "authenticated":
            raise HTTPException(401, detail="Authentication required.")
        return _AuthResult(_Claims(USER))


class _Scopes:
    async def resolve(self, user_id: UUID) -> UUID:
        assert user_id == USER
        return LAB


class _Store:
    def __init__(self) -> None:
        self.current: Publication | None = None
        self.fail = False
        self.calls = 0

    async def read(self, personal_lab_id: UUID) -> Publication | None:
        self._check(personal_lab_id)
        return self.current

    async def publish(self, personal_lab_id: UUID, raw_origin: str) -> Publication:
        self._check(personal_lab_id)
        self.current = publish_domain(
            self.current, LAB, raw_origin, PUBLICATION, KEY_1, NOW
        )
        return self.current

    async def disable(self, personal_lab_id: UUID) -> Publication | None:
        self._check(personal_lab_id)
        if self.current is not None:
            self.current = disable_publication(self.current, NOW)
        return self.current

    async def rotate(self, personal_lab_id: UUID) -> Publication | None:
        self._check(personal_lab_id)
        if self.current is not None:
            self.current = rotate_public_key(self.current, KEY_2, NOW)
        return self.current

    async def revoke(self, personal_lab_id: UUID) -> Publication | None:
        self._check(personal_lab_id)
        if self.current is not None:
            self.current = revoke_publication(self.current, KEY_3, NOW)
        return self.current

    def _check(self, personal_lab_id: UUID) -> None:
        assert personal_lab_id == LAB
        self.calls += 1
        if self.fail:
            raise PublicationStoreUnavailableError


def _fixture(tmp_path: Path) -> tuple[TestClient, _Store]:
    store = _Store()
    dependencies = PersonalLabRouteDependencies(
        _Auth(), PersonalLabScopeResolver(_Scopes(), tmp_path)
    )
    app = FastAPI()
    app.add_middleware(
        SaasCsrfMiddleware,
        trusted_origins=("https://testserver",),
        protected_roots=("/api/personal",),
    )
    app.include_router(create_mvp_publication_router(dependencies, store))
    return TestClient(app, base_url="https://testserver"), store


def _csrf(client: TestClient) -> dict[str, str]:
    client.cookies.set("__Host-ragstudio-csrf", "proof")
    return {"X-CSRF-Token": "proof", "Origin": "https://testserver"}


def test_route_lifecycle_reads_fresh_status_and_retains_audit(tmp_path: Path) -> None:
    # Given: one authenticated Personal Lab and its server-owned lifecycle store.
    client, store = _fixture(tmp_path)
    with client:
        client.cookies.set("identity", "authenticated")
        headers = _csrf(client)

        # When: publish is replayed, disabled, re-enabled, rotated, and revoked.
        first = client.put(
            "/api/personal/widget-publication",
            json={"allowed_origin": "HTTPS://Widget.Example.TEST:443"},
            headers=headers,
        )
        replay = client.put(
            "/api/personal/widget-publication",
            json={"allowed_origin": "https://widget.example.test"},
            headers=headers,
        )
        disabled = client.post(
            "/api/personal/widget-publication/disable", headers=headers
        )
        stale_read = client.get("/api/personal/widget-publication")
        enabled = client.put(
            "/api/personal/widget-publication",
            json={"allowed_origin": "https://widget.example.test"},
            headers=headers,
        )
        rotated = client.post(
            "/api/personal/widget-publication/rotate", headers=headers
        )
        revoked = client.delete("/api/personal/widget-publication", headers=headers)

    # Then: status is fresh, replay adds no audit, and terminal history is retained.
    assert first.json()["allowed_origin"] == "https://widget.example.test"
    assert replay.json()["audit_event_count"] == 1
    assert disabled.json()["state"] == stale_read.json()["state"] == "disabled"
    assert enabled.json()["audit_event_count"] == 3
    assert rotated.json()["key_version"] == 2
    assert revoked.json()["state"] == "revoked"
    assert revoked.json()["key_version"] == 3
    assert revoked.json()["audit_event_count"] == 5
    assert store.current is not None and len(store.current.audit) == 5


def test_forged_scope_is_rejected_or_ignored_before_store_authority(
    tmp_path: Path,
) -> None:
    # Given: an authenticated caller attempting to select another Personal Lab.
    client, store = _fixture(tmp_path)
    forged = UUID("77000000-0000-4000-8000-000000000007")
    with client:
        client.cookies.set("identity", "authenticated")
        headers = _csrf(client)

        # When: a body selector and query/header selectors are supplied.
        body = client.put(
            "/api/personal/widget-publication",
            json={
                "allowed_origin": "https://widget.example.test",
                "personal_lab_id": str(forged),
            },
            headers=headers,
        )
        selected = client.put(
            f"/api/personal/widget-publication?personal_lab_id={forged}",
            json={"allowed_origin": "https://widget.example.test"},
            headers={**headers, "X-Personal-Lab-ID": str(forged)},
        )

    # Then: body authority is rejected and ignored selectors cannot alter trusted scope.
    assert body.status_code == 422
    assert selected.status_code == 200
    assert "personal_lab_id" not in selected.json()
    assert str(forged) not in selected.text
    assert store.calls == 1


def test_auth_csrf_invalid_alias_and_atomic_store_failure_are_bounded(
    tmp_path: Path,
) -> None:
    # Given: publication routes with no browser authority and one durable failure.
    client, store = _fixture(tmp_path)
    with client:
        missing_csrf = client.put(
            "/api/personal/widget-publication",
            json={"allowed_origin": "https://widget.example.test"},
        )
        headers = _csrf(client)
        missing_auth = client.put(
            "/api/personal/widget-publication",
            json={"allowed_origin": "https://widget.example.test"},
            headers=headers,
        )
        client.cookies.set("identity", "authenticated")
        alias = client.put(
            "/api/personal/widget-publication",
            json={"allowed_origin": "http://2130706433"},
            headers=headers,
        )
        store.fail = True
        failed = client.put(
            "/api/personal/widget-publication",
            json={"allowed_origin": "https://widget.example.test"},
            headers=headers,
        )

    # Then: each denial is sanitized and no partial publication survives.
    assert missing_csrf.status_code == 403
    assert missing_auth.status_code == 401
    assert alias.status_code == 422
    assert alias.json() == {"detail": "Invalid publication origin."}
    assert failed.status_code == 503
    assert failed.json() == {"detail": "Publication state is unavailable."}
    assert store.current is None


def test_publication_feature_flag_is_independent_from_billing() -> None:
    # Given: opposite publication and billing feature states.
    configuration = BillingConfiguration(
        api_key=SecretStr("rk_test_" + "x" * 24),
        webhook_secret=SecretStr("whsec_" + "x" * 24),
        price_id="price_publication001",
        public_app_url="https://testserver/app",
        portal_configuration_id="bpc_publication0001",
        test_object_pairs="price_publication001|bpc_publication0001",
    )
    publication_only, billing_only = FastAPI(), FastAPI()
    publication_only.state.runtime_configuration = RuntimeConfiguration(
        mode=RuntimeMode.SAAS, billing=None, publication_enabled=True
    )
    billing_only.state.runtime_configuration = RuntimeConfiguration(
        mode=RuntimeMode.SAAS, billing=configuration, publication_enabled=False
    )

    # When: the extracted composition seam mounts both combinations.
    mount_personal_lab_routes(
        publication_only, _Auth(), "postgresql://unused/publication"
    )
    mount_personal_lab_routes(billing_only, _Auth(), "postgresql://unused/billing")

    # Then: each route follows only its own runtime gate.
    assert "publication" in publication_only.state.personal_lab_router_registry.names
    assert "billing" not in publication_only.state.personal_lab_router_registry.names
    assert "publication" not in billing_only.state.personal_lab_router_registry.names
    assert "billing" in billing_only.state.personal_lab_router_registry.names
    assert any(
        route.path == "/api/personal/widget-publication"
        for route in publication_only.routes
    )
    assert all(
        not route.path.startswith("/api/personal/widget-publication")
        for route in billing_only.routes
    )
