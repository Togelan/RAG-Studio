from __future__ import annotations

from fastapi.testclient import TestClient

from src.api.dependencies import get_vector_store
from src.api.main import create_app
from src.vector_store.pagination import ListedPoint, ListingPage


class StrategyListingStore:
    async def list_documents(self, cursor: str | None = None) -> ListingPage:
        del cursor
        return ListingPage(
            items=(
                ListedPoint(
                    "indexed",
                    {
                        "doc_id": "new-doc",
                        "source": "new.txt",
                        "total_chunks": 2,
                        "chunk_size": 512,
                        "chunk_overlap": 64,
                        "created_at": "created",
                        "strategy": "sentence_window",
                        "schema_version": 1,
                    },
                ),
                ListedPoint(
                    "legacy",
                    {
                        "doc_id": "legacy-doc",
                        "source": "legacy.txt",
                        "total_chunks": 1,
                        "chunk_size": 512,
                        "chunk_overlap": 64,
                        "created_at": "created",
                    },
                ),
            ),
            next_cursor=None,
            truncated=False,
            scanned_points=2,
            matched_items=2,
        )


def test_document_listing_exposes_strategy_and_legacy_default() -> None:
    # Given
    app = create_app()
    app.dependency_overrides[get_vector_store] = StrategyListingStore

    # When
    with TestClient(app) as client:
        response = client.get("/api/ingest/documents")

    # Then
    assert response.status_code == 200
    documents = {item["doc_id"]: item for item in response.json()["documents"]}
    assert documents["new-doc"]["strategy"] == "sentence_window"
    assert documents["new-doc"]["schema_version"] == 1
    assert documents["legacy-doc"]["strategy"] == "recursive"
    assert documents["legacy-doc"]["schema_version"] == 1
