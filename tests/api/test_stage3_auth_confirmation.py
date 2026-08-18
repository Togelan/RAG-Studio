from __future__ import annotations

from dataclasses import dataclass, field

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.routes.saas_auth_confirmation import create_saas_auth_confirmation_router


@dataclass(slots=True)
class RecordedConfirmationVerifier:
    queries: list[str] = field(default_factory=list)

    async def verify(self, query: str) -> None:
        self.queries.append(query)


def test_confirmation_link_is_verified_by_auth_then_returns_to_saas() -> None:
    # Given: GoTrue's public email link arrives at the BFF with its opaque query.
    verifier = RecordedConfirmationVerifier()
    app = FastAPI()
    app.include_router(
        create_saas_auth_confirmation_router(
            completion_url="/saas", verifier=verifier
        )
    )

    # When: the browser follows the confirmation link.
    with TestClient(app, base_url="https://testserver") as client:
        response = client.get(
            "/auth/v1/verify?token=opaque-confirmation-token&type=signup",
            follow_redirects=False,
        )

    # Then: only GoTrue receives the opaque query and the browser returns to SaaS.
    assert response.status_code == 303
    assert response.headers["location"] == "/saas"
    assert verifier.queries == ["token=opaque-confirmation-token&type=signup"]
