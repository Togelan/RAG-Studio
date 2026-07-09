"""Qdrant async client singleton — AC-008.1, AC-008.10, NFR-023.

Provides a lazy-initialized AsyncQdrantClient that connects to
an in-process Qdrant instance with persistent disk storage or
a remote Qdrant URL.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import TYPE_CHECKING

from qdrant_client import AsyncQdrantClient

if TYPE_CHECKING:
    from typing import Self

logger = logging.getLogger(__name__)

# Default Qdrant URL (in-process/embedded mode)
_QDRANT_DEFAULT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
_QDRANT_DEFAULT_API_KEY = os.getenv("QDRANT_API_KEY")  # None if unset


class QdrantClientManager:
    """Singleton manager for AsyncQdrantClient with lazy initialization.

    Provides health check polling on startup per NFR-023
    and graceful shutdown on application exit per AC-008.9.
    """

    # Startup health poll settings (NFR-023)
    STARTUP_TIMEOUT: float = 30  # seconds
    STARTUP_RETRY_INTERVAL: float = 2  # seconds

    _instance: Self | None = None
    _client: AsyncQdrantClient | None = None
    _lock: asyncio.Lock | None = None

    def __new__(cls) -> Self:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._lock = asyncio.Lock()
        return cls._instance

    async def get_client(self) -> AsyncQdrantClient:
        """Return the singleton AsyncQdrantClient, initializing if needed.

        Supports two modes:
        - Remote: QDRANT_URL set to a remote server
        - Local: QDRANT_URL unset → uses in-process Qdrant with persistent
          disk storage at QDRANT_PATH (default: data/qdrant_storage)
        """  # noqa: D205
        if self._client is None:
            assert self._lock is not None
            async with self._lock:
                if self._client is None:
                    qdrant_url = os.getenv("QDRANT_URL", "")

                    if qdrant_url:
                        # Remote Qdrant server
                        self._client = AsyncQdrantClient(
                            url=qdrant_url,
                            api_key=os.getenv("QDRANT_API_KEY"),
                        )
                        logger.info("Qdrant client initialized: url=%s", qdrant_url)
                    else:
                        # In-process (embedded) Qdrant with persistent disk storage
                        from pathlib import Path

                        qdrant_path = os.getenv("QDRANT_PATH", "data/qdrant_storage")
                        Path(qdrant_path).mkdir(parents=True, exist_ok=True)
                        self._client = AsyncQdrantClient(
                            path=qdrant_path,
                            prefer_grpc=False,
                        )
                        logger.info(
                            "Qdrant client initialized: in-process [path=%s]",
                            qdrant_path,
                        )
        return self._client

    async def health_check(self) -> bool:
        """Check Qdrant connectivity.

        Returns:
            True if Qdrant is reachable, False otherwise.
        """
        try:
            client = await self.get_client()
            await client.get_collections()
            return True
        except Exception as e:
            logger.warning("Qdrant health check failed: %s", e)
            return False

    async def wait_for_ready(
        self,
        timeout: float | None = None,
        retry_interval: float | None = None,
    ) -> bool:
        """Poll Qdrant health until ready or timeout (NFR-023).

        Args:
            timeout: Maximum total wait time in seconds (default: 30).
            retry_interval: Interval between retry attempts in seconds (default: 2).

        Returns:
            True if Qdrant became ready within the timeout.

        Raises:
            RuntimeError: If Qdrant is not ready after timeout.
        """
        if timeout is None:
            timeout = self.STARTUP_TIMEOUT
        if retry_interval is None:
            retry_interval = self.STARTUP_RETRY_INTERVAL
        deadline = asyncio.get_event_loop().time() + timeout
        last_exception: Exception | None = None

        while asyncio.get_event_loop().time() < deadline:
            if await self.health_check():
                logger.info("Qdrant is ready.")
                return True
            logger.info(
                "Waiting for Qdrant... retrying in %ss (timeout in %.0fs)",
                retry_interval,
                deadline - asyncio.get_event_loop().time(),
            )
            await asyncio.sleep(retry_interval)

        raise RuntimeError(
            f"Qdrant did not become ready within {timeout}s timeout. "
            f"Last error: {last_exception}"
        )

    async def close(self) -> None:
        """Close the Qdrant client connection gracefully."""
        if self._client is not None:
            try:
                await self._client.close()
                logger.info("Qdrant client closed.")
            except Exception as e:
                logger.warning("Error closing Qdrant client: %s", e)
            finally:
                self._client = None


# Module-level singleton
_qdrant_manager = QdrantClientManager()


async def get_qdrant_client() -> AsyncQdrantClient:
    """FastAPI dependency: return the singleton AsyncQdrantClient."""
    return await _qdrant_manager.get_client()


async def close_qdrant_client() -> None:
    """Close the Qdrant client (called during shutdown)."""
    await _qdrant_manager.close()


async def wait_for_qdrant_ready(
    timeout: float | None = None,
    retry_interval: float | None = None,
) -> bool:
    """Poll Qdrant health until ready or timeout (NFR-023).

    Public wrapper around QdrantClientManager.wait_for_ready.

    Args:
        timeout: Maximum total wait time in seconds (default: 30).
        retry_interval: Interval between retry attempts in seconds (default: 2).

    Returns:
        True if Qdrant became ready within the timeout.

    Raises:
        RuntimeError: If Qdrant is not ready after timeout.
    """
    return await _qdrant_manager.wait_for_ready(
        timeout=timeout if timeout is not None else QdrantClientManager.STARTUP_TIMEOUT,
        retry_interval=retry_interval
        if retry_interval is not None
        else QdrantClientManager.STARTUP_RETRY_INTERVAL,
    )
