"""Behavioral coverage for final context-unit expansion."""

from __future__ import annotations

from types import MappingProxyType

from src.retrieve.context_expansion import expand_context_units
from src.retrieve.orchestrator import hybrid_search
from src.vector_store.models import VectorSearchHit, VectorSearchQuery


def _hit(
    point_id: str,
    score: float,
    text: str,
    **payload: str | int | bool,
) -> VectorSearchHit:
    return VectorSearchHit(
        point_id=point_id,
        score=score,
        payload=MappingProxyType({"text": text, **payload}),
    )


def test_parent_children_expand_once_to_their_parent() -> None:
    units = expand_context_units(
        (
            _hit(
                "child-2",
                0.8,
                "second child",
                strategy="parent_document",
                doc_id="document-a",
                parent_id="paragraph-1",
                parent_text="The entire paragraph.",
                parent_start_offset=4,
                parent_end_offset=25,
                source="guide.txt",
            ),
            _hit(
                "child-1",
                0.9,
                "first child",
                strategy="parent_document",
                doc_id="document-a",
                parent_id="paragraph-1",
                parent_text="The entire paragraph.",
                parent_start_offset=4,
                parent_end_offset=25,
                source="guide.txt",
            ),
        ),
        top_k=5,
        character_budget=200,
    )

    assert len(units) == 1
    assert units[0].text == "The entire paragraph."
    assert units[0].score == 0.9
    assert units[0].metadata["start_offset"] == 4
    assert units[0].metadata["end_offset"] == 25


def test_sentence_windows_deduplicate_and_refill_after_budget_skip() -> None:
    units = expand_context_units(
        (
            _hit(
                "too-large",
                0.99,
                "child",
                strategy="sentence_window",
                doc_id="document-a",
                window_text="x" * 60,
                window_start_offset=0,
                window_end_offset=60,
            ),
            _hit(
                "window-2",
                0.8,
                "child two",
                strategy="sentence_window",
                doc_id="document-a",
                window_text="Sentence one. Sentence two.",
                window_start_offset=0,
                window_end_offset=27,
            ),
            _hit(
                "window-1",
                0.7,
                "child one",
                strategy="sentence_window",
                doc_id="document-a",
                window_text="Sentence one. Sentence two.",
                window_start_offset=0,
                window_end_offset=27,
            ),
            _hit("raw", 0.6, "Short fallback.", doc_id="document-b"),
        ),
        top_k=2,
        character_budget=50,
    )

    assert [unit.text for unit in units] == [
        "Sentence one. Sentence two.",
        "Short fallback.",
    ]


def test_malformed_strategy_or_offsets_use_safe_raw_context_and_location_fallback() -> (
    None
):
    units = expand_context_units(
        (
            _hit(
                "legacy",
                0.7,
                "Legacy text.",
                strategy="unknown",
                start_offset="bad",
                end_offset="also-bad",
                source="legacy.txt",
            ),
        ),
        top_k=1,
        character_budget=100,
    )

    assert units[0].text == "Legacy text."
    assert units[0].metadata["strategy"] == "recursive"
    assert units[0].metadata["location_unavailable"] is True


def test_csv_rows_do_not_expose_synthetic_text_offsets_as_citations() -> None:
    units = expand_context_units(
        (
            _hit(
                "csv-row",
                0.8,
                "name,amount",
                strategy="csv_row",
                start_offset=0,
                end_offset=11,
            ),
        ),
        top_k=1,
        character_budget=100,
    )

    assert units[0].metadata["location_unavailable"] is True
    assert "start_offset" not in units[0].metadata
    assert "end_offset" not in units[0].metadata


class _Searcher:
    def __init__(self, hits: tuple[VectorSearchHit, ...]) -> None:
        self._hits = hits

    async def search(self, query: VectorSearchQuery) -> tuple[VectorSearchHit, ...]:
        return self._hits


async def test_hybrid_search_reranks_expanded_parent_context_not_raw_children() -> None:
    results = await hybrid_search(
        query="paragraph",
        dense_vector=[0.0],
        sparse_indices=[0],
        sparse_values=[1.0],
        top_k=10,
        use_reranker=False,
        vector_searcher=_Searcher(
            (
                _hit(
                    "child",
                    0.9,
                    "a raw child",
                    strategy="parent_document",
                    doc_id="document-a",
                    parent_id="paragraph-1",
                    parent_text="The complete parent paragraph.",
                    parent_start_offset=0,
                    parent_end_offset=30,
                ),
            )
        ),
    )

    assert [result["text"] for result in results] == ["The complete parent paragraph."]
