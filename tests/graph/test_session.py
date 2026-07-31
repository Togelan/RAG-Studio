"""Regression tests for checkpoint-backed chat session boundaries."""

from __future__ import annotations

from collections import ChainMap
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from src.graph.builder import create_graph
from src.graph.session import (
    SessionPersistenceError,
    delete_session,
    get_session_metadata,
)


@pytest.mark.asyncio
async def test_fresh_unicode_session_has_no_checkpoint(tmp_path: Any) -> None:
    """A new Unicode thread is a valid empty session, not a read failure."""
    db_path = str(tmp_path / "checkpoints.db")
    session_id = "новая-сессия-🌿"

    async with create_graph(db_path=db_path) as graph:
        checkpointer = graph.checkpointer
        checkpoint = await checkpointer.aget_tuple(
            {"configurable": {"thread_id": session_id}}
        )

    assert checkpoint is None


@pytest.mark.asyncio
async def test_unicode_messages_and_metadata_survive_restart(tmp_path: Any) -> None:
    """Typed checkpoint data remains readable after recreating the graph."""
    from langgraph.checkpoint.base import empty_checkpoint

    db_path = str(tmp_path / "checkpoints.db")
    session_id = "сессия-重启-🌿"
    checkpoint = empty_checkpoint()
    checkpoint["channel_values"] = {
        "messages": [
            HumanMessage(content="Привет, 世界"),
            AIMessage(content="Ответ: всё сохранено."),
        ]
    }
    config = {"configurable": {"thread_id": session_id, "checkpoint_ns": ""}}

    async with create_graph(db_path=db_path) as graph:
        await graph.checkpointer.aput(config, checkpoint, {"source": "test"}, {})

    async with create_graph(db_path=db_path) as restarted_graph:
        restored = await restarted_graph.checkpointer.aget_tuple(
            {"configurable": {"thread_id": session_id}}
        )
        metadata = await get_session_metadata(
            session_id, compiled_graph=restarted_graph
        )

    assert restored is not None
    assert restored.metadata["source"] == "test"
    assert [message.content for message in restored.checkpoint["channel_values"]["messages"]] == [
        "Привет, 世界",
        "Ответ: всё сохранено.",
    ]
    assert metadata == {
        "id": session_id,
        "title": "Привет, 世界",
        "created_at": checkpoint["ts"],
        "message_count": 2,
    }


@pytest.mark.asyncio
async def test_metadata_accepts_mapping_and_message_sequence() -> None:
    """Checkpoint readers accept mapping/sequence implementations from savers."""
    checkpoint = ChainMap(
        {
            "ts": "2026-07-31T00:00:00+00:00",
            "channel_values": ChainMap(
                {
                    "messages": (
                        HumanMessage(content="mapped message"),
                        AIMessage(content="mapped answer"),
                    )
                }
            ),
        }
    )
    checkpointer = SimpleNamespace(
        aget_tuple=AsyncMock(return_value=SimpleNamespace(checkpoint=checkpoint))
    )

    metadata = await get_session_metadata(
        "mapping-session", compiled_graph=SimpleNamespace(checkpointer=checkpointer)
    )

    assert metadata == {
        "id": "mapping-session",
        "title": "mapped message",
        "created_at": "2026-07-31T00:00:00+00:00",
        "message_count": 2,
    }


@pytest.mark.asyncio
async def test_delete_failure_raises_safe_persistence_error(tmp_path: Any) -> None:
    """A failed checkpoint deletion never masquerades as a successful deletion."""
    checkpointer = SimpleNamespace(
        adelete_thread=AsyncMock(side_effect=OSError("internal database path"))
    )

    with pytest.raises(SessionPersistenceError, match="Unable to delete"):
        await delete_session(
            "delete-me",
            compiled_graph=SimpleNamespace(checkpointer=checkpointer),
            db_path=str(tmp_path / "missing" / "checkpoints.db"),
        )
