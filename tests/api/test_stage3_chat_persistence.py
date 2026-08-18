from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

import pytest

from src.api.saas_chat_persistence import (
    ChatbotConfiguration,
    ChatFeedback,
    ChatSessionNotFoundError,
    TenantChatStore,
)
from src.api.saas_chat_scope import SaasChatScope


def _scope(*, workspace_id: UUID, user_id: UUID, chatbot_id: UUID) -> SaasChatScope:
    return SaasChatScope(
        workspace_id=workspace_id,
        user_id=user_id,
        chatbot_id=chatbot_id,
        session_id=uuid4(),
    )


@pytest.mark.anyio
async def test_sessions_remain_isolated_when_session_uuid_matches(
    tmp_path: Path,
) -> None:
    # Given: two tenant scopes deliberately reuse one session UUID.
    store = TenantChatStore(tmp_path / "tenant-chat.sqlite3")
    await store.initialize()
    shared_session_id = uuid4()
    first = SaasChatScope(uuid4(), uuid4(), uuid4(), shared_session_id)
    second = SaasChatScope(uuid4(), uuid4(), uuid4(), shared_session_id)

    # When: both scopes persist different titles and feedback.
    await store.create_session(first, "First tenant")
    await store.create_session(second, "Second tenant")
    await store.save_feedback(
        first,
        ChatFeedback(message_id=uuid4(), feedback="positive", reason=None),
    )

    # Then: each exact composite scope sees only its own records.
    assert [item.title for item in await store.list_sessions(first.context)] == [
        "First tenant"
    ]
    assert [item.title for item in await store.list_sessions(second.context)] == [
        "Second tenant"
    ]
    assert len(await store.list_feedback(first)) == 1
    assert await store.list_feedback(second) == ()


@pytest.mark.anyio
async def test_scoped_records_survive_store_restart_without_secret_fields(
    tmp_path: Path,
) -> None:
    # Given: one chatbot config, session, and feedback in a task-owned database.
    database_path = tmp_path / "tenant-chat.sqlite3"
    scope = SaasChatScope(uuid4(), uuid4(), uuid4(), uuid4())
    first_store = TenantChatStore(database_path)
    await first_store.initialize()
    config = ChatbotConfiguration(
        provider="deepseek",
        model_name="chat-model",
        instructions="Use workspace sources.",
        workspace_all=True,
    )
    await first_store.save_configuration(scope.context, config)
    await first_store.create_session(scope, "Persistent session")
    await first_store.save_feedback(
        scope,
        ChatFeedback(message_id=uuid4(), feedback="negative", reason="not relevant"),
    )

    # When: a new store instance opens the same database after restart.
    restarted_store = TenantChatStore(database_path)
    await restarted_store.initialize()

    # Then: scoped non-secret state round-trips and no credential field exists.
    assert await restarted_store.get_configuration(scope.context) == config
    assert (await restarted_store.get_session(scope)).title == "Persistent session"
    assert len(await restarted_store.list_feedback(scope)) == 1
    assert "api_key" not in database_path.read_text(encoding="latin-1")


@pytest.mark.anyio
async def test_tampered_scope_cannot_rename_delete_or_submit_feedback(
    tmp_path: Path,
) -> None:
    # Given: a session owned by one exact execution scope.
    store = TenantChatStore(tmp_path / "tenant-chat.sqlite3")
    await store.initialize()
    owner_scope = SaasChatScope(uuid4(), uuid4(), uuid4(), uuid4())
    await store.create_session(owner_scope, "Owned")
    tampered_scope = SaasChatScope(
        uuid4(),
        owner_scope.user_id,
        owner_scope.chatbot_id,
        owner_scope.session_id,
    )

    # When/Then: cross-workspace mutations fail closed as not found.
    with pytest.raises(ChatSessionNotFoundError):
        await store.rename_session(tampered_scope, "Stolen")
    with pytest.raises(ChatSessionNotFoundError):
        await store.save_feedback(
            tampered_scope,
            ChatFeedback(message_id=uuid4(), feedback="positive", reason=None),
        )
    with pytest.raises(ChatSessionNotFoundError):
        await store.delete_session(tampered_scope)
    assert (await store.get_session(owner_scope)).title == "Owned"
