"""SQLite persistence isolated beneath the explicit SaaS data root."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import aiosqlite

from src.api.saas_chat_models import (
    ChatbotConfiguration,
    ChatFeedback,
    ChatPersistenceUnavailableError,
    ChatSessionNotFoundError,
    ChatSessionRecord,
)
from src.api.saas_chat_schema import CHAT_SCHEMA
from src.api.saas_chat_scope import SaasChatContext, SaasChatScope

__all__ = [
    "ChatFeedback",
    "ChatPersistenceUnavailableError",
    "ChatSessionNotFoundError",
    "ChatSessionRecord",
    "ChatbotConfiguration",
    "TenantChatStore",
]


class TenantChatStore:
    """Persist tenant chat records under exact composite ownership keys."""

    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path

    async def initialize(self) -> None:
        """Create the isolated persistence schema idempotently."""
        self._database_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            async with aiosqlite.connect(self._database_path) as connection:
                await connection.execute("PRAGMA foreign_keys = ON")
                await connection.executescript(CHAT_SCHEMA)
                await connection.commit()
        except aiosqlite.Error:
            raise ChatPersistenceUnavailableError from None

    async def save_configuration(
        self, context: SaasChatContext, configuration: ChatbotConfiguration
    ) -> None:
        """Upsert validated non-secret configuration for one chatbot."""
        await self._execute(
            """
            INSERT INTO chatbot_configurations
                (workspace_id, chatbot_id, provider, model_name,
                 instructions, workspace_all)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(workspace_id, chatbot_id) DO UPDATE SET
                provider=excluded.provider,
                model_name=excluded.model_name,
                instructions=excluded.instructions,
                workspace_all=excluded.workspace_all
            """,
            (
                str(context.workspace_id),
                str(context.chatbot_id),
                configuration.provider,
                configuration.model_name,
                configuration.instructions,
                int(configuration.workspace_all),
            ),
        )

    async def get_configuration(
        self, context: SaasChatContext
    ) -> ChatbotConfiguration | None:
        """Return configuration only within the selected workspace."""
        row = await self._fetchone(
            """
            SELECT provider, model_name, instructions, workspace_all
              FROM chatbot_configurations
             WHERE workspace_id = ? AND chatbot_id = ?
            """,
            (str(context.workspace_id), str(context.chatbot_id)),
        )
        if row is None:
            return None
        return ChatbotConfiguration(
            provider=str(row[0]),
            model_name=str(row[1]),
            instructions=str(row[2]),
            workspace_all=bool(row[3]),
        )

    async def create_session(
        self, scope: SaasChatScope, title: str
    ) -> ChatSessionRecord:
        """Create an idempotent session inside one exact tenant scope."""
        timestamp = datetime.now(UTC).isoformat()
        await self._execute(
            """
            INSERT INTO chat_sessions
                (workspace_id, user_id, chatbot_id, session_id,
                 title, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(workspace_id, user_id, chatbot_id, session_id) DO NOTHING
            """,
            (*_scope_values(scope), title, timestamp, timestamp),
        )
        return await self.get_session(scope)

    async def list_sessions(
        self, context: SaasChatContext
    ) -> tuple[ChatSessionRecord, ...]:
        """List sessions for only one workspace, user, and chatbot."""
        rows = await self._fetchall(
            """
            SELECT session_id, title, created_at, updated_at
              FROM chat_sessions
             WHERE workspace_id = ? AND user_id = ? AND chatbot_id = ?
             ORDER BY updated_at DESC, session_id
            """,
            _context_values(context),
        )
        return tuple(_session_record(row) for row in rows)

    async def get_session(self, scope: SaasChatScope) -> ChatSessionRecord:
        """Return a session only when every scope dimension matches."""
        row = await self._fetchone(
            """
            SELECT session_id, title, created_at, updated_at
              FROM chat_sessions
             WHERE workspace_id = ? AND user_id = ?
               AND chatbot_id = ? AND session_id = ?
            """,
            _scope_values(scope),
        )
        if row is None:
            raise ChatSessionNotFoundError
        return _session_record(row)

    async def rename_session(
        self, scope: SaasChatScope, title: str
    ) -> ChatSessionRecord:
        """Rename only the exact scoped session."""
        timestamp = datetime.now(UTC).isoformat()
        changed = await self._execute(
            """
            UPDATE chat_sessions SET title = ?, updated_at = ?
             WHERE workspace_id = ? AND user_id = ?
               AND chatbot_id = ? AND session_id = ?
            """,
            (title, timestamp, *_scope_values(scope)),
        )
        if changed == 0:
            raise ChatSessionNotFoundError
        return await self.get_session(scope)

    async def delete_session(self, scope: SaasChatScope) -> None:
        """Delete only the exact session and its scoped feedback."""
        changed = await self._execute(
            """
            DELETE FROM chat_sessions
             WHERE workspace_id = ? AND user_id = ?
               AND chatbot_id = ? AND session_id = ?
            """,
            _scope_values(scope),
        )
        if changed == 0:
            raise ChatSessionNotFoundError

    async def save_feedback(self, scope: SaasChatScope, feedback: ChatFeedback) -> None:
        """Persist idempotent feedback only for an existing scoped session."""
        await self.get_session(scope)
        await self._execute(
            """
            INSERT INTO chat_feedback
                (workspace_id, user_id, chatbot_id, session_id,
                 message_id, feedback, reason)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(workspace_id, user_id, chatbot_id, session_id, message_id)
            DO UPDATE SET feedback=excluded.feedback, reason=excluded.reason
            """,
            (
                *_scope_values(scope),
                str(feedback.message_id),
                feedback.feedback,
                feedback.reason,
            ),
        )

    async def list_feedback(self, scope: SaasChatScope) -> tuple[ChatFeedback, ...]:
        """Return feedback only for the exact scoped session."""
        rows = await self._fetchall(
            """
            SELECT message_id, feedback, reason FROM chat_feedback
             WHERE workspace_id = ? AND user_id = ?
               AND chatbot_id = ? AND session_id = ?
             ORDER BY message_id
            """,
            _scope_values(scope),
        )
        return tuple(
            ChatFeedback.model_validate(
                {"message_id": row[0], "feedback": row[1], "reason": row[2]}
            )
            for row in rows
        )

    async def _execute(
        self, statement: str, parameters: tuple[str | int | None, ...]
    ) -> int:
        try:
            async with aiosqlite.connect(self._database_path) as connection:
                await connection.execute("PRAGMA foreign_keys = ON")
                cursor = await connection.execute(statement, parameters)
                await connection.commit()
                return cursor.rowcount
        except aiosqlite.Error:
            raise ChatPersistenceUnavailableError from None

    async def _fetchone(
        self, statement: str, parameters: tuple[str, ...]
    ) -> tuple[str | int | None, ...] | None:
        try:
            async with aiosqlite.connect(self._database_path) as connection:
                cursor = await connection.execute(statement, parameters)
                row = await cursor.fetchone()
        except aiosqlite.Error:
            raise ChatPersistenceUnavailableError from None
        return tuple(row) if row is not None else None

    async def _fetchall(
        self, statement: str, parameters: tuple[str, ...]
    ) -> tuple[tuple[str | int | None, ...], ...]:
        try:
            async with aiosqlite.connect(self._database_path) as connection:
                cursor = await connection.execute(statement, parameters)
                rows = await cursor.fetchall()
        except aiosqlite.Error:
            raise ChatPersistenceUnavailableError from None
        return tuple(tuple(row) for row in rows)


def _context_values(context: SaasChatContext) -> tuple[str, str, str]:
    return str(context.workspace_id), str(context.user_id), str(context.chatbot_id)


def _scope_values(scope: SaasChatScope) -> tuple[str, str, str, str]:
    return (*_context_values(scope.context), str(scope.session_id))


def _session_record(row: tuple[str | int | None, ...]) -> ChatSessionRecord:
    return ChatSessionRecord(
        session_id=UUID(str(row[0])),
        title=str(row[1]),
        created_at=datetime.fromisoformat(str(row[2])),
        updated_at=datetime.fromisoformat(str(row[3])),
    )
