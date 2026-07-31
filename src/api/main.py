"""FastAPI application factory with lifespan management.

Handles:
- Startup: Qdrant health polling (NFR-023) with 30s timeout
- Shutdown: Graceful SIGTERM handling with 10s timeout (AC-008.9)
- Route mounting
"""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncGenerator, cast
from urllib.parse import urlsplit

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from src.api.dependencies import log_audit
from src.api.rate_limiter import RateLimitMiddleware
from src.api.routes.chat import router as chat_router
from src.api.routes.chat import set_graph
from src.api.routes.health import router as health_router
from src.api.routes.settings import router as settings_router
from src.api.routes.ui import router as ui_router
from src.graph import create_graph
from src.ingestion.router import router as ingestion_router
from src.paths import data_path
from src.vector_store.client import close_qdrant_client, wait_for_qdrant_ready

logger = logging.getLogger(__name__)

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
_CORS_HEADERS = ("Content-Type", "X-API-Key")

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
            raise ValueError(
                "RAG_STUDIO_CORS_ORIGINS must not contain empty origin entries."
            )
        if origin == "*":
            raise ValueError(
                "RAG_STUDIO_CORS_ORIGINS must list explicit origins; "
                "'*' is not allowed."
            )

        try:
            parsed = urlsplit(origin)
        except ValueError as exc:
            raise ValueError(f"Invalid CORS origin {origin!r}.") from exc
        try:
            parsed.port  # Validates malformed port values.
        except ValueError as exc:
            raise ValueError(
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
            raise ValueError(
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
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
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

    async with create_graph(db_path=_checkpoints_db) as graph:
        app.state.graph = graph
        set_graph(graph)
        logger.info("LangGraph compiled graph stored in app.state")
        yield
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
        except asyncio.TimeoutError:
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
    app = FastAPI(
        title="RAG-Studio",
        description="Local-first RAG tool — chat with your documents privately.",
        version="1.0.0",
        lifespan=lifespan,
    )

    # CORS middleware — allow local development
    # Apply per-IP sliding-window limits to API requests.
    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins_from_environment(),
        allow_credentials=False,
        allow_methods=_CORS_METHODS,
        allow_headers=_CORS_HEADERS,
    )

    # Mount route modules
    app.include_router(health_router)
    app.include_router(ingestion_router)
    app.include_router(chat_router)
    app.include_router(settings_router)
    app.include_router(ui_router)

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
