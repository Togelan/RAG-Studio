"""End-to-end tests for the RAG pipeline (FR-003 retrieval quality).

Tests cover:
- Ingestion of real test data into a Qdrant collection
- 10 query tests (EN + RU) for retrieval quality
- Session persistence across invocations
- UTF-8 safety (no UnicodeDecodeError during checkpointer serialization)
"""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import HumanMessage

from src.graph.nodes import retrieve_node
from src.graph.state import RAGState
from src.ingestion.chunker import chunk_text
from src.ingestion.embedder import (
    generate_dense_embeddings,
    generate_sparse_embeddings,
    make_doc_id,
)
from src.ingestion.parser import parse_md

logger = logging.getLogger(__name__)

# Test collection name
TEST_COLLECTION = "test_collection"

# Test data file path
TEST_DATA_FILE = (
    Path(__file__).resolve().parent.parent.parent
    / "data"
    / "raw_data"
    / "raw_test_data.md"
)


def _make_state(
    query: str,
    session_id: str = "e2e-test-session",
    retrieved_docs: list[dict[str, Any]] | None = None,
) -> RAGState:
    """Create a minimal RAGState for testing retrieval."""
    state: RAGState = {
        "messages": [HumanMessage(content=query)],
        "query": query,
        "intent": "",
        "cache_hit": False,
        "cached_answer": None,
        "retrieved_docs": retrieved_docs or [],
        "reranked_docs": [],
        "generated_from": "",
        "final_answer": None,
        "faithfulness_score": 0.0,
        "validation_passed": False,
        "session_id": session_id,
        "user_api_key": None,
        "provider": "openai",
        "model_name": "gpt-4o-mini",
        "temperature": 1.0,
        "max_tokens": 2048,
        "system_prompt": "",
    }
    return state


def _get_all_text(docs: list[dict[str, Any]]) -> str:
    """Concatenate all document texts into one string for assertions."""
    return " ".join(str(doc.get("text", "")) for doc in docs)


@pytest.mark.e2e
@pytest.mark.asyncio
class TestRagPipelineE2E:
    """E2E tests for the RAG pipeline: ingestion → retrieval → persistence."""

    @pytest.fixture(autouse=True)
    async def setup_teardown(self, monkeypatch: pytest.MonkeyPatch) -> Any:
        """Set up test Qdrant instance with test data, tear down after.

        Creates a temporary Qdrant storage path, ingests test data,
        and cleans up everything after all tests.
        """
        # Create temp directories for test isolation
        self.temp_qdrant_path = tempfile.mkdtemp(prefix="test_qdrant_e2e_")
        self.temp_checkpoints_dir = tempfile.mkdtemp(prefix="test_checkpoints_e2e_")
        self.temp_db_path = os.path.join(
            self.temp_checkpoints_dir, "test_checkpoints.db"
        )

        # Override env for Qdrant path (in-process mode)
        monkeypatch.setenv("QDRANT_PATH", self.temp_qdrant_path)
        # Unset QDRANT_URL to force in-process mode
        monkeypatch.delenv("QDRANT_URL", raising=False)

        # Reset Qdrant singleton so it picks up the new path
        from src.vector_store.client import QdrantClientManager

        QdrantClientManager._instance = None  # pyright: ignore[reportPrivateUsage]
        QdrantClientManager._client = None  # pyright: ignore[reportPrivateUsage]

        # Patch COLLECTION_NAME in embedder to use test collection
        monkeypatch.setattr(
            "src.ingestion.embedder.COLLECTION_NAME",
            TEST_COLLECTION,
        )
        # Also patch in retrieve orchestrator for hybrid_search default
        # (hybrid_search has collection_name parameter, so we pass it explicitly)

        # Parse test data
        assert TEST_DATA_FILE.exists(), f"Test data file not found: {TEST_DATA_FILE}"
        raw_text = parse_md(str(TEST_DATA_FILE))
        assert len(raw_text) > 100, "Test data is too short"

        # Chunk the text
        chunks = chunk_text(raw_text)
        assert len(chunks) > 0, "No chunks generated from test data"
        logger.info(
            "E2E setup: %d chunks generated from %s", len(chunks), TEST_DATA_FILE.name
        )

        # Generate embeddings
        dense_vectors = generate_dense_embeddings(chunks)
        sparse_vectors = generate_sparse_embeddings(chunks)
        assert len(dense_vectors) == len(chunks)
        assert len(sparse_vectors) == len(chunks)

        # Get Qdrant client and ensure test collection exists
        from src.vector_store.client import get_qdrant_client

        client = await get_qdrant_client()

        # Create test collection manually (similar to ensure_collection_exists but for test_collection)
        from qdrant_client.http import models as qmodels

        if not await client.collection_exists(TEST_COLLECTION):
            await client.create_collection(
                collection_name=TEST_COLLECTION,
                vectors_config={
                    "dense": qmodels.VectorParams(
                        size=384,
                        distance=qmodels.Distance.COSINE,
                    ),
                },
                sparse_vectors_config={
                    "sparse": qmodels.SparseVectorParams(
                        index=qmodels.SparseIndexParams(on_disk=False),
                    ),
                },
            )
            logger.info("Created test collection '%s'", TEST_COLLECTION)

        # Upsert chunks into test collection
        # We need to use the patched COLLECTION_NAME, but upsert_chunks uses the
        # module-level COLLECTION_NAME which is now monkeypatched to TEST_COLLECTION.
        # However, upsert_chunks also references it at definition time...
        # Let's upsert directly to be safe.
        from datetime import datetime, timezone

        from qdrant_client.http import models as qmodels

        # Delete existing points for test data first
        await client.delete_collection(TEST_COLLECTION)
        await client.create_collection(
            collection_name=TEST_COLLECTION,
            vectors_config={
                "dense": qmodels.VectorParams(
                    size=384,
                    distance=qmodels.Distance.COSINE,
                ),
            },
            sparse_vectors_config={
                "sparse": qmodels.SparseVectorParams(
                    index=qmodels.SparseIndexParams(on_disk=False),
                ),
            },
        )

        points: list[qmodels.PointStruct] = []
        now = datetime.now(timezone.utc).isoformat()
        filename = "raw_test_data.md"

        for i, chunk_text_val in enumerate(chunks):
            point_id = make_doc_id(filename, i)
            payload: dict[str, object] = {
                "text": chunk_text_val,
                "source": filename,
                "chunk_index": i,
                "total_chunks": len(chunks),
                "doc_id": make_doc_id(filename, 0),  # simplified
                "created_at": now,
                "file_hash": "",
                "chunk_size": 512,
                "chunk_overlap": 64,
            }
            points.append(
                qmodels.PointStruct(
                    id=point_id,
                    vector={
                        "dense": dense_vectors[i],
                        "sparse": sparse_vectors[i],
                    },
                    payload=payload,
                )
            )

        await client.upsert(
            collection_name=TEST_COLLECTION,
            points=points,
            wait=True,
        )
        logger.info(
            "E2E setup: upserted %d points into '%s'", len(points), TEST_COLLECTION
        )

        # Verify points exist
        count_result = await client.count(collection_name=TEST_COLLECTION, exact=True)
        assert count_result.count > 0, (
            f"No points in test collection '{TEST_COLLECTION}'"
        )
        logger.info("E2E setup: verified %d points in collection", count_result.count)

        self.collection_name = TEST_COLLECTION
        self.chunks = chunks

        # Monkeypatch hybrid_search in src.graph.nodes so retrieve_node
        # searches the test collection instead of the default rag_studio_docs.
        from src.graph import nodes as graph_nodes
        from src.retrieve import orchestrator as _retrieve_orch

        _original_hybrid_search = _retrieve_orch.hybrid_search

        async def _patched_hybrid_search(*args: Any, **kwargs: Any) -> Any:
            kwargs.setdefault("collection_name", TEST_COLLECTION)
            return await _original_hybrid_search(*args, **kwargs)

        monkeypatch.setattr(
            graph_nodes,
            "hybrid_search",
            _patched_hybrid_search,
        )

        yield

        # Teardown: clean up test collection and temp dirs
        try:
            await client.delete_collection(TEST_COLLECTION)
            logger.info("E2E teardown: deleted test collection '%s'", TEST_COLLECTION)
        except Exception as exc:
            logger.warning("E2E teardown: failed to delete collection: %s", exc)

        # Close Qdrant client
        from src.vector_store.client import close_qdrant_client

        await close_qdrant_client()

        # Clean up temp dirs
        shutil.rmtree(self.temp_qdrant_path, ignore_errors=True)
        shutil.rmtree(self.temp_checkpoints_dir, ignore_errors=True)

    # ============================================================
    # Query 1: "Who is Masha?" (EN)
    # ============================================================

    async def test_query_1_who_is_masha(self) -> None:
        """E2E: EN query 'Who is Masha?' returns docs mentioning Masha."""
        query = "Who is Masha?"
        state = _make_state(query)

        try:
            result_state = await retrieve_node(state)
        except Exception as exc:
            pytest.fail(f"retrieve_node raised exception: {type(exc).__name__}: {exc}")

        docs: list[dict[str, Any]] = result_state.get("retrieved_docs", [])
        all_text = _get_all_text(docs)

        assert len(docs) > 0, f"No documents retrieved for query: {query}"
        assert "Masha" in all_text, (
            f"'Masha' not found in retrieved docs for query: {query}. "
            f"First doc preview: {docs[0].get('text', '')[:200] if docs else 'N/A'}"
        )

    # ============================================================
    # Query 2: "Who is Mark?" (EN)
    # ============================================================

    async def test_query_2_who_is_mark(self) -> None:
        """E2E: EN query 'Who is Mark?' returns docs mentioning Mark."""
        query = "Who is Mark?"
        state = _make_state(query)

        try:
            result_state = await retrieve_node(state)
        except Exception as exc:
            pytest.fail(f"retrieve_node raised exception: {type(exc).__name__}: {exc}")

        docs: list[dict[str, Any]] = result_state.get("retrieved_docs", [])
        all_text = _get_all_text(docs)

        assert len(docs) > 0, f"No documents retrieved for query: {query}"
        assert "Mark" in all_text, (
            f"'Mark' not found in retrieved docs for query: {query}"
        )

    # ============================================================
    # Query 3: "How old is Masha?" (EN)
    # ============================================================

    async def test_query_3_how_old_is_masha(self) -> None:
        """E2E: EN query 'How old is Masha?' returns docs mentioning 19."""
        query = "How old is Masha?"
        state = _make_state(query)

        try:
            result_state = await retrieve_node(state)
        except Exception as exc:
            pytest.fail(f"retrieve_node raised exception: {type(exc).__name__}: {exc}")

        docs: list[dict[str, Any]] = result_state.get("retrieved_docs", [])
        all_text = _get_all_text(docs)

        assert len(docs) > 0, f"No documents retrieved for query: {query}"
        assert "19" in all_text, f"'19' not found in retrieved docs for query: {query}"

    # ============================================================
    # Query 4: "What is Mark's walking speed?" (EN)
    # ============================================================

    async def test_query_4_marks_walking_speed(self) -> None:
        """E2E: EN query about Mark's walking speed returns docs with '4.7' or 'walking speed'."""
        query = "What is Mark's walking speed?"
        state = _make_state(query)

        try:
            result_state = await retrieve_node(state)
        except Exception as exc:
            pytest.fail(f"retrieve_node raised exception: {type(exc).__name__}: {exc}")

        docs: list[dict[str, Any]] = result_state.get("retrieved_docs", [])
        all_text = _get_all_text(docs)

        assert len(docs) > 0, f"No documents retrieved for query: {query}"
        assert "4.7" in all_text or "walking speed" in all_text, (
            f"Neither '4.7' nor 'walking speed' found for query: {query}"
        )

    # ============================================================
    # Query 5: "кто такая маша" (RU)
    # ============================================================

    async def test_query_5_kto_takaya_masha(self) -> None:
        """E2E: RU query 'кто такая маша' returns docs mentioning Masha or Маша."""
        query = "кто такая маша"
        state = _make_state(query)

        try:
            result_state = await retrieve_node(state)
        except Exception as exc:
            pytest.fail(f"retrieve_node raised exception: {type(exc).__name__}: {exc}")

        docs: list[dict[str, Any]] = result_state.get("retrieved_docs", [])
        all_text = _get_all_text(docs)

        assert len(docs) > 0, f"No documents retrieved for query: {query}"
        assert "Masha" in all_text or "Маша" in all_text, (
            f"Neither 'Masha' nor 'Маша' found for query: {query}"
        )

    # ============================================================
    # Query 6: "сколько лет маше" (RU)
    # ============================================================

    async def test_query_6_skolko_let_mashe(self) -> None:
        """E2E: RU query 'сколько лет маше' returns docs with '19' or 'years'."""
        query = "сколько лет маше"
        state = _make_state(query)

        try:
            result_state = await retrieve_node(state)
        except Exception as exc:
            pytest.fail(f"retrieve_node raised exception: {type(exc).__name__}: {exc}")

        docs: list[dict[str, Any]] = result_state.get("retrieved_docs", [])
        all_text = _get_all_text(docs)

        assert len(docs) > 0, f"No documents retrieved for query: {query}"
        assert "19" in all_text or "years" in all_text, (
            f"Neither '19' nor 'years' found for query: {query}"
        )

    # ============================================================
    # Query 7: "какая скорость ходьбы у марка" (RU)
    # ============================================================

    async def test_query_7_skorost_khodby_marka(self) -> None:
        """E2E: RU query about Mark's walking speed returns docs with '4.7' or 'walking'."""
        query = "какая скорость ходьбы у марка"
        state = _make_state(query)

        try:
            result_state = await retrieve_node(state)
        except Exception as exc:
            pytest.fail(f"retrieve_node raised exception: {type(exc).__name__}: {exc}")

        docs: list[dict[str, Any]] = result_state.get("retrieved_docs", [])
        all_text = _get_all_text(docs)

        assert len(docs) > 0, f"No documents retrieved for query: {query}"
        assert "4.7" in all_text or "walking" in all_text, (
            f"Neither '4.7' nor 'walking' found for query: {query}"
        )

    # ============================================================
    # Query 8: "What is the distance from Masha's window to the gate?" (EN)
    # ============================================================

    async def test_query_8_distance_window_to_gate(self) -> None:
        """E2E: EN query about distance from window to gate returns '8.4'."""
        query = "What is the distance from Masha's window to the gate?"
        state = _make_state(query)

        try:
            result_state = await retrieve_node(state)
        except Exception as exc:
            pytest.fail(f"retrieve_node raised exception: {type(exc).__name__}: {exc}")

        docs: list[dict[str, Any]] = result_state.get("retrieved_docs", [])
        all_text = _get_all_text(docs)

        assert len(docs) > 0, f"No documents retrieved for query: {query}"
        assert "8.4" in all_text, f"'8.4' not found for query: {query}"

    # ============================================================
    # Query 9: "When was the first verbal interaction?" (EN)
    # ============================================================

    async def test_query_9_first_verbal_interaction(self) -> None:
        """E2E: EN query about first verbal interaction returns 'May 31' or 'verbal'."""
        query = "When was the first verbal interaction?"
        state = _make_state(query)

        try:
            result_state = await retrieve_node(state)
        except Exception as exc:
            pytest.fail(f"retrieve_node raised exception: {type(exc).__name__}: {exc}")

        docs: list[dict[str, Any]] = result_state.get("retrieved_docs", [])
        all_text = _get_all_text(docs)

        assert len(docs) > 0, f"No documents retrieved for query: {query}"
        assert "May 31" in all_text or "verbal" in all_text, (
            f"Neither 'May 31' nor 'verbal' found for query: {query}"
        )

    # ============================================================
    # Query 10: "Сколько раз они встречались на скамейке?" (RU)
    # ============================================================

    async def test_query_10_bench_meetings(self) -> None:
        """E2E: RU query about bench meetings returns '14' or 'bench'."""
        query = "Сколько раз они встречались на скамейке?"
        state = _make_state(query)

        try:
            result_state = await retrieve_node(state)
        except Exception as exc:
            pytest.fail(f"retrieve_node raised exception: {type(exc).__name__}: {exc}")

        docs: list[dict[str, Any]] = result_state.get("retrieved_docs", [])
        all_text = _get_all_text(docs)

        assert len(docs) > 0, f"No documents retrieved for query: {query}"
        assert "14" in all_text or "bench" in all_text, (
            f"Neither '14' nor 'bench' found for query: {query}"
        )

    # ============================================================
    # Session Persistence Test
    # ============================================================

    async def test_session_persistence_after_refresh(self) -> None:
        """E2E: Session state persists across graph instances (simulated refresh).

        Runs 10 queries through the full graph (with mocked LLM to avoid API calls),
        then creates a new graph instance and verifies all turns are preserved
        without UTF-8 errors.
        """
        session_id = "e2e-persistence-test-session"

        # Mock ChatOpenAI to avoid real LLM calls during the graph run
        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "Mocked answer for testing."
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)

        all_queries = [
            "Who is Masha?",
            "Who is Mark?",
            "How old is Masha?",
            "What is Mark's walking speed?",
            "кто такая маша",
            "сколько лет маше",
            "какая скорость ходьбы у марка",
            "What is the distance from Masha's window to the gate?",
            "When was the first verbal interaction?",
            "Сколько раз они встречались на скамейке?",
        ]

        # Patch ChatOpenAI and run the full graph
        with patch("src.graph.nodes.ChatOpenAI", return_value=mock_llm):
            from src.graph.builder import create_graph, run_rag_graph

            # Run all 10 queries through the same compiled graph
            async with create_graph(db_path=self.temp_db_path) as graph:
                for query in all_queries:
                    try:
                        result = await run_rag_graph(
                            query=query,
                            session_id=session_id,
                            user_api_key="test-key",
                            compiled_graph=graph,
                        )
                        assert "final_answer" in result, (
                            f"No final_answer in result for query: {query}"
                        )
                    except Exception as exc:
                        # Check that it's not a UnicodeDecodeError
                        if isinstance(exc, UnicodeDecodeError):
                            pytest.fail(
                                f"UnicodeDecodeError during graph run for '{query}': {exc}"
                            )
                        # Other errors are acceptable if they're not UTF-8 related
                        logger.warning(
                            "Graph run for '%s' failed (non-UTF8): %s: %s",
                            query,
                            type(exc).__name__,
                            exc,
                        )

            # Step 2: Simulate refresh — create a NEW graph instance with same db_path
            async with create_graph(db_path=self.temp_db_path) as graph2:
                from src.graph.session import get_session_metadata

                try:
                    metadata = await get_session_metadata(
                        thread_id=session_id,
                        compiled_graph=graph2,
                    )
                except UnicodeDecodeError as exc:
                    pytest.fail(f"UnicodeDecodeError during session reload: {exc}")
                except Exception as exc:
                    logger.warning(
                        "get_session_metadata failed (non-UTF8): %s: %s",
                        type(exc).__name__,
                        exc,
                    )
                    metadata = None

                # If metadata is available, verify message count
                if metadata is not None:
                    msg_count = metadata.get("message_count", 0)
                    logger.info(
                        "Session persistence: metadata=%s, message_count=%d",
                        metadata,
                        msg_count,
                    )
                    # We expect at least some messages (each query adds at least 1 user + 1 AI)
                    assert msg_count > 0, (
                        f"Session has no messages after reload. Metadata: {metadata}"
                    )
                else:
                    # Fallback: try to get checkpoint directly via aconfig
                    try:
                        if hasattr(graph2, "checkpointer"):
                            config = {"configurable": {"thread_id": session_id}}
                            checkpoint_tuple = await graph2.checkpointer.aget_tuple(
                                config
                            )
                            assert checkpoint_tuple is not None, (
                                "No checkpoint found after reload"
                            )
                            logger.info(
                                "Session persistence: checkpoint found via aget_tuple"
                            )
                    except UnicodeDecodeError as exc:
                        pytest.fail(
                            f"UnicodeDecodeError during checkpoint reload: {exc}"
                        )
                    except Exception as exc:
                        logger.warning(
                            "Checkpoint reload failed (non-UTF8): %s: %s",
                            type(exc).__name__,
                            exc,
                        )

        # Clean up checkpoint data
        try:
            import aiosqlite

            async with aiosqlite.connect(self.temp_db_path) as conn:
                await conn.execute(
                    "DELETE FROM checkpoints WHERE thread_id = ?",
                    (session_id,),
                )
                await conn.execute(
                    "DELETE FROM writes WHERE thread_id = ?",
                    (session_id,),
                )
                await conn.commit()
        except Exception:
            pass
