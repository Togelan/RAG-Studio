from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.mvp_local_demo import (
    LocalDemoConfigurationError,
    create_mvp_local_demo_router,
    load_local_demo_mode,
)
from src.api.personal_lab_registry import PersonalLabRouteDependencies
from src.api.personal_lab_scope import PersonalLabScopeResolver
from tests.api.mvp_billing_route_fakes import CookieAuth, Scopes


def test_local_demo_requires_explicit_loopback_only_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RAG_STUDIO_LOCAL_DEMO_MODE", "true")

    assert (
        load_local_demo_mode(
            ("http://127.0.0.1:64840/",),
            billing_configured=False,
            publication_enabled=False,
        )
        is True
    )


@pytest.mark.parametrize(
    ("origins", "billing_configured", "publication_enabled"),
    [
        (("https://rag.example.com/",), False, False),
        (("http://127.0.0.1:64840/",), True, False),
        (("http://127.0.0.1:64840/",), False, True),
    ],
)
def test_local_demo_rejects_public_or_real_commerce_configuration(
    monkeypatch: pytest.MonkeyPatch,
    origins: tuple[str, ...],
    billing_configured: bool,
    publication_enabled: bool,
) -> None:
    monkeypatch.setenv("RAG_STUDIO_LOCAL_DEMO_MODE", "true")

    with pytest.raises(
        LocalDemoConfigurationError,
        match="Local demo mode requires a loopback-only SaaS runtime",
    ):
        load_local_demo_mode(
            origins,
            billing_configured=billing_configured,
            publication_enabled=publication_enabled,
        )


def test_local_demo_routes_are_authenticated_and_never_offer_publication_or_stripe(
    tmp_path: Path,
) -> None:
    dependencies = PersonalLabRouteDependencies(
        CookieAuth(), PersonalLabScopeResolver(Scopes(), tmp_path)
    )
    app = FastAPI()
    app.include_router(create_mvp_local_demo_router(dependencies))

    with TestClient(app) as client:
        unauthenticated = client.get("/api/personal/billing")
        client.cookies.set("identity", "authenticated")
        billing = client.get("/api/personal/billing")
        widget = client.get("/api/personal/widget-publication")
        checkout = client.post("/api/personal/billing/checkout")
        publish = client.put(
            "/api/personal/widget-publication",
            json={"allowed_origin": "https://example.test"},
        )

    assert unauthenticated.status_code == 401
    assert billing.json() == {
        "mode": "local_demo",
        "access": "demo",
        "stripe_configured": False,
        "plan": {
            "amount_usd_cents": 1_000,
            "currency": "USD",
            "interval": "month",
        },
    }
    assert widget.json() == {
        "mode": "local_demo",
        "protected_preview": True,
        "public_publication": False,
    }
    assert checkout.status_code == 404
    assert publish.status_code == 405
