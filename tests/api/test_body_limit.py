"""Unit tests for BodySizeLimitMiddleware (EDGE-H01)."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.responses import Response

from src.api.body_limit import BodySizeLimitMiddleware


def _build_app(
    chat_limit: int | None = None, upload_limit: int | None = None
) -> FastAPI:
    """Create a minimal FastAPI app with BodySizeLimitMiddleware."""
    app = FastAPI()

    @app.api_route("/api/chat/{rest:path}", methods=["GET", "POST", "PATCH"])
    async def chat_echo() -> Response:
        return Response(content='{"ok":true}', media_type="application/json")

    @app.api_route("/api/ingest/upload", methods=["GET", "POST"])
    async def upload_echo() -> Response:
        return Response(content='{"ok":true}', media_type="application/json")

    @app.api_route("/other", methods=["POST"])
    async def other_echo() -> Response:
        return Response(content='{"ok":true}', media_type="application/json")

    app.add_middleware(
        BodySizeLimitMiddleware,
        chat_limit=chat_limit,
        upload_limit=upload_limit,
    )

    return app


class TestSafeMethodsBypass:
    """AC: Safe methods (GET, HEAD, DELETE, OPTIONS) are never checked."""

    def test_get_chat_passes(self) -> None:
        client = TestClient(_build_app(chat_limit=10))
        resp = client.get("/api/chat/test")
        assert resp.status_code == 200

    def test_get_upload_passes(self) -> None:
        client = TestClient(_build_app(upload_limit=10))
        resp = client.get("/api/ingest/upload")
        assert resp.status_code == 200

    def test_delete_chat_passes(self) -> None:
        client = TestClient(_build_app(chat_limit=10))
        resp = client.delete("/api/chat/test")
        # DELETE is not a registered route → 405, but the middleware
        # did NOT reject it as 413. That is the correct behavior.
        assert resp.status_code != 413

    def test_options_chat_passes(self) -> None:
        client = TestClient(_build_app(chat_limit=10))
        resp = client.options("/api/chat/test")
        # OPTIONS may return 405 for unregistered routes, but
        # the body-size middleware must not block it.
        assert resp.status_code != 413

    def test_head_chat_passes(self) -> None:
        client = TestClient(_build_app(chat_limit=10))
        resp = client.head("/api/chat/test")
        # HEAD may return 405, but the body-size middleware
        # must pass it through without blocking.
        assert resp.status_code != 413


class TestChatEndpointRejectsOversized:
    """AC: Chat POST with Content-Length > limit returns 413."""

    def test_chat_over_limit_rejected(self) -> None:
        """POST to /api/chat/ with Content-Length exceeding chat limit."""
        client = TestClient(_build_app(chat_limit=100))
        resp = client.post(
            "/api/chat/test",
            headers={"Content-Length": "200"},
            content="x" * 200,
        )
        assert resp.status_code == 413
        data = resp.json()
        assert data["detail"] == "Payload Too Large"

    def test_chat_at_limit_passes(self) -> None:
        """POST to /api/chat/ with Content-Length at exactly the limit."""
        client = TestClient(_build_app(chat_limit=100))
        resp = client.post(
            "/api/chat/test",
            headers={"Content-Length": "100"},
            content="x" * 100,
        )
        assert resp.status_code == 200

    def test_chat_under_limit_passes(self) -> None:
        """POST to /api/chat/ with Content-Length under the limit."""
        client = TestClient(_build_app(chat_limit=100))
        resp = client.post(
            "/api/chat/test",
            headers={"Content-Length": "50"},
            content="x" * 50,
        )
        assert resp.status_code == 200


class TestUploadEndpointRejectsOversized:
    """AC: Upload POST with Content-Length > limit returns 413."""

    def test_upload_over_limit_rejected(self) -> None:
        """POST to /api/ingest/upload with Content-Length exceeding limit."""
        client = TestClient(_build_app(upload_limit=100))
        resp = client.post(
            "/api/ingest/upload",
            headers={"Content-Length": "200"},
            content="x" * 200,
        )
        assert resp.status_code == 413
        data = resp.json()
        assert data["detail"] == "Payload Too Large"

    def test_upload_at_limit_passes(self) -> None:
        """POST to /api/ingest/upload with Content-Length at the limit."""
        client = TestClient(_build_app(upload_limit=100))
        resp = client.post(
            "/api/ingest/upload",
            headers={"Content-Length": "100"},
            content="x" * 100,
        )
        assert resp.status_code == 200


class TestOtherPathsPassThrough:
    """AC: Paths outside chat/upload prefixes are never blocked."""

    def test_other_path_with_large_body_passes(self) -> None:
        client = TestClient(_build_app(chat_limit=10, upload_limit=10))
        resp = client.post(
            "/other",
            headers={"Content-Length": "999999"},
            content="x" * 1000,
        )
        assert resp.status_code == 200

    def test_other_path_no_content_length_passes(self) -> None:
        client = TestClient(_build_app(chat_limit=10, upload_limit=10))
        resp = client.post("/other", content="hello")
        assert resp.status_code == 200


class TestMissingContentLengthPasses:
    """AC: Requests without Content-Length header pass through."""

    def test_chat_without_content_length_passes(self) -> None:
        client = TestClient(_build_app(chat_limit=10))
        resp = client.post("/api/chat/test", content="some body")
        assert resp.status_code == 200

    def test_upload_without_content_length_passes(self) -> None:
        client = TestClient(_build_app(upload_limit=10))
        resp = client.post("/api/ingest/upload", content="data")
        assert resp.status_code == 200


class TestNonNumericContentLengthPasses:
    """AC: Unparseable Content-Length header passes through."""

    def test_garbage_content_length_passes(self) -> None:
        client = TestClient(_build_app(chat_limit=10))
        resp = client.post(
            "/api/chat/test",
            headers={"Content-Length": "garbage"},
            content="hello",
        )
        assert resp.status_code == 200


class TestResponseFormat:
    """AC: 413 response returns correct JSON body and content type."""

    def test_413_has_json_content_type(self) -> None:
        client = TestClient(_build_app(chat_limit=50))
        resp = client.post(
            "/api/chat/test",
            headers={"Content-Length": "100"},
            content="x" * 100,
        )
        assert resp.status_code == 413
        assert resp.headers["content-type"] == "application/json"
        assert resp.json() == {"detail": "Payload Too Large"}


class TestDefaultLimits:
    """Verify the default limit constants are sensible."""

    def test_default_chat_limit_is_100kb(self) -> None:
        from src.api.body_limit import _DEFAULT_CHAT_LIMIT

        assert _DEFAULT_CHAT_LIMIT == 100 * 1024

    def test_default_upload_limit_is_50mb(self) -> None:
        from src.api.body_limit import _DEFAULT_UPLOAD_LIMIT

        assert _DEFAULT_UPLOAD_LIMIT == 50 * 1024 * 1024
