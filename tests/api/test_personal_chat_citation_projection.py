from __future__ import annotations

from src.api.personal_citations import project_safe_citations


def test_citations_preserve_offsets_and_deduplicate_identical_final_locations() -> None:
    citations = project_safe_citations(
        (
            {
                "score": 0.9,
                "metadata": {
                    "doc_id": "doc-a",
                    "filename": "guide.pdf",
                    "chunk_index": 2,
                    "start_offset": 120,
                    "end_offset": 240,
                },
            },
            {
                "score": 0.8,
                "metadata": {
                    "doc_id": "doc-a",
                    "filename": "guide.pdf",
                    "chunk_index": 2,
                    "start_offset": 120,
                    "end_offset": 240,
                },
            },
            {
                "score": 0.7,
                "metadata": {
                    "doc_id": "doc-a",
                    "filename": "guide.pdf",
                    "chunk_index": 3,
                    "start_offset": 241,
                    "end_offset": 360,
                },
            },
        )
    )

    assert citations == (
        {
            "doc_id": "doc-a",
            "filename": "guide.pdf",
            "chunk_index": 2,
            "start_offset": 120,
            "end_offset": 240,
            "location": "Characters 120–240",
            "score": 0.9,
        },
        {
            "doc_id": "doc-a",
            "filename": "guide.pdf",
            "chunk_index": 3,
            "start_offset": 241,
            "end_offset": 360,
            "location": "Characters 241–360",
            "score": 0.7,
        },
    )


def test_citations_without_a_final_location_are_not_collapsed() -> None:
    citations = project_safe_citations(
        (
            {"metadata": {"filename": "unknown.txt"}},
            {"metadata": {"filename": "unknown.txt"}},
        )
    )

    assert citations == (
        {"filename": "unknown.txt"},
        {"filename": "unknown.txt"},
    )


def test_same_page_distinct_chunks_remain_distinct() -> None:
    citations = project_safe_citations(
        (
            {"metadata": {"doc_id": "doc-a", "page": 4, "chunk_index": 1}},
            {"metadata": {"doc_id": "doc-a", "page": 4, "chunk_index": 2}},
        )
    )

    assert citations == (
        {"doc_id": "doc-a", "page": 4, "chunk_index": 1},
        {"doc_id": "doc-a", "page": 4, "chunk_index": 2},
    )


def test_untrusted_location_and_paths_do_not_cross_the_projection() -> None:
    citation = project_safe_citations(
        (
            {
                "api_key": "must-not-cross",
                "location": "private content marker",
                "metadata": {
                    "doc_id": "doc-a",
                    "filename": "private/system/guide.pdf",
                    "source": "private\\system\\guide.pdf",
                    "start_offset": -5,
                    "end_offset": 2,
                },
            },
        )
    )

    assert citation == (
        {
            "doc_id": "doc-a",
            "filename": "guide.pdf",
            "source": "guide.pdf",
        },
    )
