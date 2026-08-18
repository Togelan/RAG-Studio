from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import NotRequired, TypedDict
from uuid import UUID

import pytest

from src.api.saas_chat_execution import graph_job_producer


class _CitationInput(TypedDict):
    index: int
    filename: str
    score: float
    start_offset: int
    end_offset: int
    chunk_text: str


class _ResultInput(TypedDict):
    final_answer: str
    generated_from: str
    citations: list[_CitationInput]


class _GraphEvent(TypedDict):
    type: str
    token: NotRequired[str]
    result: NotRequired[_ResultInput]


@pytest.mark.anyio
async def test_graph_stream_keeps_citation_metadata_without_document_text() -> None:
    # Given: a graph result containing citation metadata and private chunk text.
    async def graph_events() -> AsyncIterator[_GraphEvent]:
        yield {"type": "token", "token": "Answer"}
        yield {
            "type": "result",
            "result": {
                "final_answer": "Answer [1]",
                "generated_from": "retrieval",
                "citations": [
                    {
                        "index": 1,
                        "filename": "guide.pdf",
                        "score": 0.9,
                        "start_offset": 0,
                        "end_offset": 12,
                        "chunk_text": "private document text",
                    }
                ],
            },
        }

    emitted: list[str] = []

    async def publish(event: str) -> None:
        emitted.append(event)

    producer = graph_job_producer(
        graph_events=graph_events(),
    )

    # When: the tenant test stream publishes the graph result.
    await producer(publish)

    # Then: the terminal event is shared-contract valid without private document text.
    done_event = next(event for event in emitted if event.startswith("event: done"))
    payload = json.loads(done_event.split("data: ", 1)[1])
    assert payload["done"] is True
    assert payload["completed"] is True
    assert UUID(payload["message_id"])
    assert payload["full_response"] == "Answer [1]"
    assert payload["generated_from"] == "retrieval"
    assert payload["citations"] == [
        {
            "index": 1,
            "filename": "guide.pdf",
            "score": 0.9,
            "start_offset": 0,
            "end_offset": 12,
        }
    ]
    assert "private document text" not in "".join(emitted)
    assert not any(event.startswith("event: result") for event in emitted)
