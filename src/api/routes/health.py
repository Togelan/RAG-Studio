"""FastAPI health check endpoint — AC-008.1, NFR-023."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel, Field
from qdrant_client import AsyncQdrantClient
from qdrant_client.http.exceptions import ApiException

from src.api.dependencies import get_qdrant_client

router = APIRouter(tags=["health"])


class SimpleHealthResponse(BaseModel):
    """Simple health check response for Docker HEALTHCHECK."""

    status: str = Field(default="ok", description="Simple health status")


class HealthResponse(BaseModel):
    """Detailed health check response schema."""

    qdrant: str = Field(description="Qdrant connection status: 'ok' or 'unavailable'")
    status: str = Field(description="Overall application status: 'ready' or 'degraded'")


@router.get("/health", response_model=SimpleHealthResponse)
async def simple_health() -> SimpleHealthResponse:
    """Return simple health status for Docker HEALTHCHECK.

    This endpoint is intentionally lightweight — no dependencies, no DB checks.
    Used by Docker HEALTHCHECK and container orchestrators.
    """
    return SimpleHealthResponse(status="ok")


@router.get("/api/health", response_model=HealthResponse)
async def health_check(
    response: Response,
    client: AsyncQdrantClient = Depends(get_qdrant_client),  # noqa: B008 - FastAPI dependency injection
) -> HealthResponse:
    """Return application health status.

    Checks Qdrant connectivity and returns overall readiness.
    Used by Docker HEALTHCHECK and monitoring.

    Returns:
        HealthResponse with qdrant status and overall readiness.
    """
    qdrant_ok = False
    try:
        await client.get_collections()
        qdrant_ok = True
    except ApiException, OSError, RuntimeError:
        qdrant_ok = False

    qdrant_status = "ok" if qdrant_ok else "unavailable"
    overall_status = "ready" if qdrant_ok else "degraded"
    if not qdrant_ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return HealthResponse(qdrant=qdrant_status, status=overall_status)


class StatusResponse(BaseModel):
    """Lightweight status response for UI polling."""

    status: str = Field(description="Overall application status: 'ready' or 'degraded'")
    api_key_configured: bool = Field(
        default=False,
        description="Whether an API key has been configured.",
    )


@router.get("/api/health/status", response_model=StatusResponse)
async def health_status(response: Response) -> StatusResponse:
    """Return lightweight status for UI status indicator polling.

    Used by the frontend status indicator (every 30s).
    Checks the secrets store for API keys (not just env vars)
    and uses the in-process Qdrant client for connectivity.

    Returns:
        StatusResponse with overall status and API key configuration.
    """
    import os

    from src.api.dependencies import load_secrets

    # Check env vars AND secrets store for any configured API key.
    # The secrets store holds keys saved via the Settings UI (encrypted).
    secrets = load_secrets()
    api_key_set = bool(
        os.getenv("OPENAI_API_KEY")
        or os.getenv("DEEPSEEK_API_KEY")
        or os.getenv("ANTHROPIC_API_KEY")
        or any(k.endswith("_api_key") for k in secrets)
    )

    # Use the in-process Qdrant client (same as the rest of the app).
    # Creating a separate client on localhost:6333 fails because we
    # use in-process Qdrant, not a standalone server.
    qdrant_ok = False
    try:
        from src.vector_store.client import get_qdrant_client

        client = await get_qdrant_client()
        qdrant_ok = await client.collection_exists("rag_studio_docs")
    except ApiException, OSError, RuntimeError:
        qdrant_ok = False

    overall = "ready" if qdrant_ok else "degraded"
    if not qdrant_ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return StatusResponse(status=overall, api_key_configured=api_key_set)
