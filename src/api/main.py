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

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from src.api.dependencies import log_audit
from src.api.routes.chat import router as chat_router
from src.api.routes.chat import set_graph
from src.api.routes.health import router as health_router
from src.api.routes.settings import router as settings_router
from src.api.routes.ui import router as ui_router
from src.graph import create_graph
from src.ingestion.router import router as ingestion_router
from src.vector_store.client import close_qdrant_client, wait_for_qdrant_ready

logger = logging.getLogger(__name__)

# Shutdown timeout (AC-008.9)
_SHUTDOWN_TIMEOUT = 10  # seconds

# Track in-progress tasks for graceful shutdown
_pending_tasks: set[asyncio.Task[Any]] = set()


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

    # Create the LangGraph graph with AsyncSqliteSaver checkpointer.
    # Use an absolute path derived from the project root so that sessions
    # persist across reloads regardless of the current working directory.
    # __file__ → src/api/main.py → src/api/ → src/ → project root (RAG-Studio/)
    _project_root = Path(__file__).resolve().parent.parent.parent
    _checkpoints_db = str(_project_root / "data" / "checkpoints" / "checkpoints.db")

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
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
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
