"""Real LangGraph execution boundary for authenticated SaaS chat."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Mapping, Sequence
from typing import TypedDict
from uuid import uuid4

from src.api.chat_jobs import JobProducer, PublishEvent
from src.api.chat_stream import sse_event
from src.api.saas_chat_models import ChatbotConfiguration


class ProviderCredentialUnavailableError(RuntimeError):
    """The selected provider has no server-owned credential."""


class CitationMetadata(TypedDict, total=False):
    """Citation fields safe for the authenticated browser surface."""

    index: int
    filename: str
    score: float
    start_offset: int
    end_offset: int


def server_provider_key(configuration: ChatbotConfiguration) -> str | None:
    """Resolve credentials exclusively from the server environment."""
    if configuration.provider.casefold() == "ollama":
        return None
    key = os.getenv(f"{configuration.provider.upper()}_API_KEY")
    if not key:
        raise ProviderCredentialUnavailableError
    return key


def graph_job_producer(
    *,
    graph_events: AsyncIterator[Mapping[str, object]],
) -> JobProducer:
    """Build a bounded producer from a tenant-bound graph event stream."""

    async def produce(publish: PublishEvent) -> None:
        async for graph_event in graph_events:
            event_type = graph_event.get("type")
            if event_type == "token":
                token = graph_event.get("token")
                if isinstance(token, str) and token:
                    await publish(sse_event("token", {"token": token}))
            elif event_type == "result":
                result = graph_event.get("result")
                if isinstance(result, Mapping):
                    citations = _citation_metadata(result)
                    await publish(
                        sse_event(
                            "done",
                            {
                                "done": True,
                                "completed": True,
                                "message_id": str(uuid4()),
                                "full_response": str(result.get("final_answer", "")),
                                "generated_from": str(result.get("generated_from", "")),
                                "citations": citations,
                            },
                        )
                    )
                    return

    return produce


def _citation_metadata(result: Mapping[str, object]) -> list[CitationMetadata]:
    raw_citations = result.get("citations", ())
    if not isinstance(raw_citations, Sequence) or isinstance(
        raw_citations, (str, bytes)
    ):
        return []
    citations: list[CitationMetadata] = []
    for raw in raw_citations:
        if not isinstance(raw, Mapping):
            continue
        citation = CitationMetadata(
            index=int(raw.get("index", len(citations) + 1)),
            filename=str(raw.get("filename", "unknown")),
            score=float(raw.get("score", 0.0)),
        )
        start_offset = raw.get("start_offset")
        end_offset = raw.get("end_offset")
        if (
            isinstance(start_offset, int)
            and not isinstance(start_offset, bool)
            and isinstance(end_offset, int)
            and not isinstance(end_offset, bool)
        ):
            citation["start_offset"] = start_offset
            citation["end_offset"] = end_offset
        citations.append(citation)
    return citations
