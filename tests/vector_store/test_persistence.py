"""Persistence verification test for FR-008 / AC-008.2, AC-008.10.

Verifies that Qdrant data survives client close/re-open when using
persistent disk storage (QDRANT_PATH).
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest
from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models as rest

COLLECTION_NAME = "test_persistence_col"
VECTOR_SIZE = 384


@pytest.mark.asyncio
async def test_qdrant_persistence_across_client_restarts() -> None:
    """AC-008.2, AC-008.10: Data persists after client close and re-open."""
    tmpdir = Path(tempfile.mkdtemp(prefix="test_qdrant_persist_"))
    try:
        # --- Phase 1: Create client, collection, upsert point ---
        client1 = AsyncQdrantClient(path=str(tmpdir), prefer_grpc=False)

        await client1.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=rest.VectorParams(
                size=VECTOR_SIZE,
                distance=rest.Distance.COSINE,
            ),
        )

        await client1.upsert(
            collection_name=COLLECTION_NAME,
            points=[
                rest.PointStruct(
                    id=1,
                    vector=[0.1] * VECTOR_SIZE,
                    payload={"text": "persistence test"},
                )
            ],
        )

        count1 = await client1.count(COLLECTION_NAME)
        assert count1.count == 1, f"Expected 1 point, got {count1.count}"

        await client1.close()

        # --- Phase 2: Re-open, verify data survived ---
        client2 = AsyncQdrantClient(path=str(tmpdir), prefer_grpc=False)

        collections = await client2.get_collections()
        collection_names = [c.name for c in collections.collections]
        assert COLLECTION_NAME in collection_names, (
            f"Collection '{COLLECTION_NAME}' not found after re-open."
        )

        count2 = await client2.count(COLLECTION_NAME)
        assert count2.count == 1, f"Expected 1 point after re-open, got {count2.count}."

        await client2.delete_collection(COLLECTION_NAME)
        await client2.close()

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
