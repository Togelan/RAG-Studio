"""FastAPI application factory with lifespan management.

Handles:
- Startup: Qdrant health polling (NFR-023) with 30s timeout
- Shutdown: Graceful SIGTERM handling with 10s timeout (AC-008.9)
- Route mounting
"""

from __future__ import annotations

import asyncio  # noqa: ANYIO_OK
import logging
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, assert_never, cast
from urllib.parse import urlsplit

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from src.api.dependencies import log_audit
from src.api.public_cors import PartitionedCORSMiddleware
from src.api.rate_limiter import RateLimitMiddleware
from src.api.routes.chat import router as chat_router
from src.api.routes.chat import set_graph, shutdown_chat_jobs
from src.api.routes.health import router as health_router
from src.api.routes.settings import router as settings_router
from src.api.routes.ui import create_ui_router
from src.api.saas_composition import (
    load_application_ui_configuration,
    mount_saas_routes,
)
from src.api.saas_runtime import (
    RuntimeMode,
    create_saas_runtime_router,
    load_runtime_configuration,
)
from src.api.saas_security import SaasCsrfMiddleware
from src.graph import create_graph
from src.graph.llm_provider import OpenAIProviderFactory
from src.ingestion.router import router as ingestion_router
from src.paths import data_path, resolve_project_path
from src.vector_store.client import (
    close_qdrant_client,
    wait_for_qdrant_ready,
)

_WIDGET_ARTIFACT_NAME = "rag-studio-widget.v1.js"


def _widget_artifact_path() -> Path | None:
    root = resolve_project_path(
        os.getenv("RAG_STUDIO_WIDGET_DIST", "widget/dist")
    ).resolve()
    artifact = (root / _WIDGET_ARTIFACT_NAME).resolve()
    try:
        artifact.relative_to(root)
    except ValueError:
        return None
    return artifact if artifact.is_file() else None


logger = logging.getLogger(__name__)


class CorsConfigurationError(ValueError):
    """Raised when the explicit browser-origin allowlist is malformed."""


# Shutdown timeout (AC-008.9)
_SHUTDOWN_TIMEOUT = 10  # seconds

# The bundled UI is same-origin. Keep default cross-origin access local-only;
# deployments that have a separate frontend must explicitly configure it.
_DEFAULT_CORS_ORIGINS = (
    "http://localhost:8000",
    "http://127.0.0.1:8000",
    "http://[::1]:8000",
)
_CORS_METHODS = ("GET", "POST", "PATCH", "DELETE")
_CORS_HEADERS = ("Content-Type", "X-API-Key", "X-CSRF-Token")

# Track in-progress tasks for graceful shutdown
_pending_tasks: set[asyncio.Task[Any]] = set()


def _cors_origins_from_environment() -> tuple[str, ...]:
    """Return a validated, explicit CORS origin allowlist.

    ``RAG_STUDIO_CORS_ORIGINS`` is a comma-separated list of complete HTTP(S)
    origins. An unset value uses local-only defaults; an explicitly empty value
    disables cross-origin access. Invalid configuration fails application
    creation instead of silently using a broader policy.
    """
    configured_origins = os.getenv("RAG_STUDIO_CORS_ORIGINS")
    if configured_origins is None:
        return _DEFAULT_CORS_ORIGINS
    if not configured_origins.strip():
        return ()

    origins: list[str] = []
    for origin in configured_origins.split(","):
        origin = origin.strip()
        if not origin:
            raise CorsConfigurationError(
                "RAG_STUDIO_CORS_ORIGINS must not contain empty origin entries."
            )
        if origin == "*":
            raise CorsConfigurationError(
                "RAG_STUDIO_CORS_ORIGINS must list explicit origins; "
                "'*' is not allowed."
            )

        try:
            parsed = urlsplit(origin)
        except ValueError as exc:
            raise CorsConfigurationError(f"Invalid CORS origin {origin!r}.") from exc
        try:
            _ = parsed.port  # Validates malformed port values.
        except ValueError as exc:
            raise CorsConfigurationError(
                f"Invalid CORS origin {origin!r}: port must be a valid number."
            ) from exc
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.hostname is None
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path
            or parsed.query
            or parsed.fragment
        ):
            raise CorsConfigurationError(
                f"Invalid CORS origin {origin!r}: use a complete HTTP(S) origin "
                "without a path."
            )
        if origin not in origins:
            origins.append(origin)

    return tuple(origins)


def _create_task(coro: Any) -> asyncio.Task[Any]:
    """Create an asyncio task and track it for graceful shutdown."""
    task = asyncio.ensure_future(coro)
    _pending_tasks.add(task)
    task.add_done_callback(_pending_tasks.discard)
    return cast(asyncio.Task[Any], task)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    """FastAPI lifespan context manager.

    Startup:
        1. Configure logging
        2. Poll Qdrant health with 30s timeout (NFR-023)
        3. Log application start

    Shutdown:
        1. Wait for in-progress tasks (up to 10s timeout)
        2. Close Qdrant connection
        3. Log application stop
    """
    # ============================================================
    # Startup
    # ============================================================
    logging.basicConfig(
        level=getattr(logging, os.getenv("LOG_LEVEL", "INFO")),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    logger.info("RAG-Studio starting up...")

    # Poll Qdrant health with 30s timeout, 2s retries (NFR-023)
    try:
        ready = await wait_for_qdrant_ready(timeout=30, retry_interval=2)
        if ready:
            logger.info("Qdrant health check passed.")
    except RuntimeError as e:
        logger.critical("Startup failed: %s", e)
        raise

    log_audit("settings_change", success=True, extra={"event": "application_start"})
    logger.info("RAG-Studio is ready.")

    # This is absolute and independent of the process working directory.
    _checkpoints_db = str(data_path("checkpoints", "checkpoints.db"))
    saas_chat_runtime = getattr(app.state, "saas_chat_runtime", None)
    if saas_chat_runtime is not None:
        await saas_chat_runtime.initialize()

    provider_factory = OpenAIProviderFactory()
    async with create_graph(
        db_path=_checkpoints_db,
        provider_factory=provider_factory,
    ) as graph:
        app.state.graph = graph
        set_graph(graph)
        logger.info("LangGraph compiled graph stored in app.state")
        try:
            yield
        finally:
            await shutdown_chat_jobs()
            if saas_chat_runtime is not None:
                await saas_chat_runtime.shutdown()
        logger.info("LangGraph checkpointer connection closed")

    # ============================================================
    # Shutdown (AC-008.9)
    # ============================================================
    logger.info("RAG-Studio shutting down...")

    # Wait for in-progress tasks with 10s timeout
    if _pending_tasks:
        logger.info(
            "Waiting for %d in-progress task(s) to complete...", len(_pending_tasks)
        )
        try:
            await asyncio.wait_for(
                asyncio.gather(*_pending_tasks, return_exceptions=True),
                timeout=_SHUTDOWN_TIMEOUT,
            )
        except TimeoutError:
            logger.warning(
                "Shutdown timeout (%ds) reached. %d task(s) will be cancelled.",
                _SHUTDOWN_TIMEOUT,
                len(_pending_tasks),
            )
            for task in _pending_tasks:
                task.cancel()
            # Wait briefly for cancellations to propagate
            await asyncio.sleep(0.5)

    # Close Qdrant connection
    await close_qdrant_client()

    log_audit("settings_change", success=True, extra={"event": "application_stop"})
    logger.info("RAG-Studio shut down complete.")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application.

    Returns:
        Configured FastAPI application instance.
    """
    runtime_configuration = load_runtime_configuration()
    ui_configuration = load_application_ui_configuration(runtime_configuration.mode)
    app = FastAPI(
        title="RAG-Studio",
        description="Local-first RAG tool — chat with your documents privately.",
        version="1.0.0",
        lifespan=lifespan,
    )
    app.state.ui_configuration = ui_configuration
    app.state.runtime_configuration = runtime_configuration
    csrf_protected_roots: tuple[str, ...] = ("/api/saas", "/api/personal")

    # CORS middleware — allow local development
    # Apply per-IP sliding-window limits to API requests.
    app.add_middleware(
        SaasCsrfMiddleware,
        trusted_origins=tuple(
            str(origin).rstrip("/") for origin in runtime_configuration.trusted_origins
        ),
        protected_roots=csrf_protected_roots,
    )
    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(
        PartitionedCORSMiddleware,
        allow_origins=_cors_origins_from_environment(),
        allow_credentials=False,
        allow_methods=_CORS_METHODS,
        allow_headers=_CORS_HEADERS,
    )

    # Mount route modules
    app.include_router(health_router)
    if runtime_configuration.mode is RuntimeMode.LOCAL:
        app.include_router(ingestion_router)
        app.include_router(chat_router)
        app.include_router(settings_router)
    match runtime_configuration.mode:
        case RuntimeMode.LOCAL:
            pass
        case RuntimeMode.SAAS:
            mount_saas_routes(app, runtime_configuration)
        case unreachable:
            assert_never(unreachable)
    app.include_router(create_ui_router(ui_configuration))
    app.include_router(
        create_saas_runtime_router(runtime_configuration, ui_configuration)
    )

    widget_artifact = _widget_artifact_path()
    if widget_artifact is not None:

        @app.get(f"/widget/{_WIDGET_ARTIFACT_NAME}", include_in_schema=False)
        async def serve_widget_artifact() -> FileResponse:
            return FileResponse(
                widget_artifact,
                media_type="text/javascript",
                headers={"Cache-Control": "public, max-age=31536000, immutable"},
            )

    # Mount static files (CSS, JS, images)
    static_dir = Path(__file__).resolve().parent / "static"
    static_dir.mkdir(parents=True, exist_ok=True)
    app.mount(
        "/static",
        StaticFiles(directory=str(static_dir)),
        name="static",
    )

    return app


# Application instance
app = create_app()
