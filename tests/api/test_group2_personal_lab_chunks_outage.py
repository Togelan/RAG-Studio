from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from qdrant_client.http.exceptions import ResponseHandlingException

from tests.api.test_group2_personal_lab_ingestion import _build_app


@pytest.mark.asyncio
async def test_owned_document_chunks_return_sanitized_503_when_qdrant_is_down(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given: an authenticated owner with one committed Personal document.
    user_id = uuid4()
    app, qdrant = _build_app(
        tmp_path,
        {"owner": user_id},
        {user_id: uuid4()},
    )
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    headers = {"X-CSRF-Token": "proof", "Origin": "https://testserver"}
    try:
        async with httpx.AsyncClient(
            transport=transport, base_url="https://testserver"
        ) as client:
            client.cookies.set("__Host-ragstudio-csrf", "proof")
            client.cookies.set("identity", "owner")
            uploaded = await client.post(
                "/api/personal/knowledge/upload",
                headers=headers,
                files={"file": ("private.txt", b"private body", "text/plain")},
            )

            async def unavailable(*args: str, **kwargs: str) -> bool:
                del args, kwargs
                raise ResponseHandlingException(
                    TimeoutError("provider-token=must-not-leak")
                )

            monkeypatch.setattr(qdrant, "collection_exists", unavailable)

            # When: the owner reads chunks while Qdrant is unavailable.
            response = await client.get(
                f"/api/personal/knowledge/documents/{uploaded.json()['doc_id']}/chunks"
            )
            monkeypatch.undo()
            recovered = await client.get(
                f"/api/personal/knowledge/documents/{uploaded.json()['doc_id']}/chunks"
            )

        # Then: the API exposes only its stable retryable boundary.
        assert uploaded.status_code == 201
        assert response.status_code == 503
        assert response.json() == {"detail": "Personal Knowledge is unavailable."}
        assert "provider-token" not in response.text
        assert "Retry-After" not in response.headers
        assert recovered.status_code == 200
        assert recovered.json()["chunks"][0]["text"] == "private body"
    finally:
        await qdrant.close()
