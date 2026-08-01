"""Run the production UI with a deterministic delayed chat provider for QA."""

from __future__ import annotations

import argparse
import asyncio
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import uvicorn

from src.api.chat_jobs import ChatJobManager
from src.api.chat_stream import MAX_CONCURRENT_STREAMS


@asynccontextmanager
async def _fake_graph(*_args: Any, **_kwargs: Any) -> AsyncIterator[object]:
    yield object()


async def _fake_provider(*_args: Any, **_kwargs: Any) -> AsyncIterator[dict[str, Any]]:
    chunks = ["Привет, ", "это потоковый ", "ответ из документа [1]."]
    for chunk in chunks:
        await asyncio.sleep(1.0)
        yield {"type": "token", "token": chunk}
    answer = "".join(chunks)
    yield {
        "type": "result",
        "result": {
            "final_answer": answer,
            "generated_from": "retrieval",
            "faithfulness_score": 1.0,
            "retrieved_docs": [],
            "citations": [
                {
                    "index": 1,
                    "chunk_text": "Deterministic browser verification context.",
                    "filename": "qa-fixture.md",
                    "chunk_index": "0",
                    "score": 1.0,
                }
            ],
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8011)
    parser.add_argument("--data-root", type=Path, required=True)
    args = parser.parse_args()
    args.data_root.mkdir(parents=True, exist_ok=True)
    os.environ["RAG_STUDIO_DATA_ROOT"] = str(args.data_root)

    from src.api import dependencies
    from src.api.main import create_app
    from src.api.routes import chat

    dependencies._audit_logger = None  # pyright: ignore[reportPrivateUsage]
    chat._chat_jobs = ChatJobManager(  # pyright: ignore[reportPrivateUsage]
        MAX_CONCURRENT_STREAMS
    )
    with (
        patch("src.api.main.wait_for_qdrant_ready", new=AsyncMock(return_value=True)),
        patch("src.api.main.close_qdrant_client", new=AsyncMock(return_value=None)),
        patch("src.api.main.create_graph", new=_fake_graph),
        patch("src.api.routes.chat.stream_rag_graph", new=_fake_provider),
    ):
        uvicorn.run(create_app(), host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
