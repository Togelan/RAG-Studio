"""Scope-local durable sessions, messages, and feedback for Personal Chat."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final
from uuid import uuid4

from pydantic import TypeAdapter, ValidationError

from src.api.personal_citations import CitationPayload, project_safe_citation
from src.api.personal_lab_scope import PersonalLabScope
from src.vector_store.models import JsonValue

__all__ = ["CitationPayload", "project_safe_citation"]
_CITATIONS_ADAPTER: Final = TypeAdapter(list[dict[str, JsonValue]])


class PersonalChatNotFoundError(LookupError):
    """Hide missing and foreign Personal Chat resources behind one outcome."""


class PersonalChatConflictError(RuntimeError):
    """Reject reuse of an idempotency key with conflicting content."""


class PersonalChatStorageError(RuntimeError):
    """Report a sanitized scope-local persistence failure."""


@dataclass(frozen=True, slots=True)
class PersonalChatResult:
    """Secret-free graph result ready for safe citation projection."""

    answer: str
    generated_from: str
    citations: tuple[Mapping[str, JsonValue], ...] = ()


@dataclass(frozen=True, slots=True)
class PersonalChatSession:
    """One scope-owned session summary."""

    id: str
    title: str
    created_at: str
    message_count: int


@dataclass(frozen=True, slots=True)
class PersonalChatMessage:
    """One persisted user or assistant message."""

    id: str
    role: str
    content: str
    created_at: str
    in_reply_to: str | None = None
    generated_from: str | None = None
    citations: tuple[CitationPayload, ...] = ()


@dataclass(frozen=True, slots=True)
class PreparedPersonalTurn:
    """Idempotent turn preparation result."""

    user_message: PersonalChatMessage
    completed: PersonalChatMessage | None
    created: bool


class _PersonalChatSessionStore:
    def create_session(
        self, scope: PersonalLabScope, title: str
    ) -> PersonalChatSession:
        """Create a durable session below exactly one Personal Lab scope."""
        session = PersonalChatSession(
            id=str(uuid4()),
            title=title.strip()[:200] or "New Session",
            created_at=_now(),
            message_count=0,
        )
        with _connection(scope) as connection:
            connection.execute(
                "INSERT INTO sessions (id, title, created_at) VALUES (?, ?, ?)",
                (session.id, session.title, session.created_at),
            )
        return session

    def list_sessions(self, scope: PersonalLabScope) -> tuple[PersonalChatSession, ...]:
        """List scope-owned sessions without reading another scope database."""
        if not _path(scope).exists():
            return ()
        with _connection(scope) as connection:
            rows = connection.execute(
                """
                SELECT s.id, s.title, s.created_at, COUNT(m.id) AS message_count
                FROM sessions AS s LEFT JOIN messages AS m ON m.session_id = s.id
                GROUP BY s.id ORDER BY s.created_at DESC
                """
            ).fetchall()
        return tuple(
            PersonalChatSession(
                id=str(row["id"]),
                title=str(row["title"]),
                created_at=str(row["created_at"]),
                message_count=int(row["message_count"]),
            )
            for row in rows
        )

    def require_session(
        self, scope: PersonalLabScope, session_id: str
    ) -> PersonalChatSession:
        """Return a session or the uniform foreign/missing outcome."""
        if not _path(scope).exists():
            raise PersonalChatNotFoundError
        with _connection(scope) as connection:
            row = connection.execute(
                """
                SELECT s.id, s.title, s.created_at, COUNT(m.id) AS message_count
                FROM sessions AS s LEFT JOIN messages AS m ON m.session_id = s.id
                WHERE s.id = ? GROUP BY s.id
                """,
                (session_id,),
            ).fetchone()
        if row is None:
            raise PersonalChatNotFoundError
        return PersonalChatSession(
            id=str(row["id"]),
            title=str(row["title"]),
            created_at=str(row["created_at"]),
            message_count=int(row["message_count"]),
        )


class _PersonalChatTurnStore(_PersonalChatSessionStore):
    def prepare_turn(
        self,
        scope: PersonalLabScope,
        session_id: str,
        message_id: str,
        content: str,
    ) -> PreparedPersonalTurn:
        """Insert a user turn once and return any completed replay."""
        self.require_session(scope, session_id)
        with _connection(scope) as connection:
            existing = connection.execute(
                "SELECT * FROM messages WHERE id = ?", (message_id,)
            ).fetchone()
            if existing is not None:
                if existing["role"] != "user" or existing["content"] != content:
                    raise PersonalChatConflictError
                user = _message(existing)
                created = False
            else:
                user = PersonalChatMessage(
                    id=message_id,
                    role="user",
                    content=content,
                    created_at=_now(),
                )
                _insert_message(connection, session_id, user)
                created = True
            completed_row = connection.execute(
                "SELECT * FROM messages WHERE session_id = ? AND in_reply_to = ?",
                (session_id, message_id),
            ).fetchone()
        return PreparedPersonalTurn(
            user_message=user,
            completed=_message(completed_row) if completed_row is not None else None,
            created=created,
        )

    def discard_pending_turn(
        self, scope: PersonalLabScope, session_id: str, message_id: str
    ) -> None:
        """Remove a newly admitted user turn when live-job admission fails."""
        self.require_session(scope, session_id)
        with _connection(scope) as connection:
            completed = connection.execute(
                "SELECT 1 FROM messages WHERE session_id = ? AND in_reply_to = ?",
                (session_id, message_id),
            ).fetchone()
            if completed is None:
                connection.execute(
                    "DELETE FROM messages WHERE id = ? AND session_id = ? AND role = 'user'",
                    (message_id, session_id),
                )

    def complete_turn(
        self,
        scope: PersonalLabScope,
        session_id: str,
        message_id: str,
        result: PersonalChatResult,
    ) -> PersonalChatMessage:
        """Atomically publish one assistant response for a prepared turn."""
        self.require_session(scope, session_id)
        assistant = PersonalChatMessage(
            id=str(uuid4()),
            role="assistant",
            content=result.answer,
            created_at=_now(),
            in_reply_to=message_id,
            generated_from=result.generated_from,
            citations=tuple(dict(item) for item in result.citations),
        )
        with _connection(scope) as connection:
            _require_session_row(connection, session_id)
            user = connection.execute(
                "SELECT role FROM messages WHERE id = ? AND session_id = ?",
                (message_id, session_id),
            ).fetchone()
            if user is None or user["role"] != "user":
                raise PersonalChatNotFoundError
            existing = connection.execute(
                "SELECT * FROM messages WHERE session_id = ? AND in_reply_to = ?",
                (session_id, message_id),
            ).fetchone()
            if existing is not None:
                return _message(existing)
            _insert_message(connection, session_id, assistant)
        return assistant

    def messages(
        self, scope: PersonalLabScope, session_id: str
    ) -> tuple[PersonalChatMessage, ...]:
        """Return all messages after enforcing scope-owned session existence."""
        self.require_session(scope, session_id)
        with _connection(scope) as connection:
            rows = connection.execute(
                "SELECT * FROM messages WHERE session_id = ? ORDER BY rowid",
                (session_id,),
            ).fetchall()
        return tuple(_message(row) for row in rows)

    def save_feedback(
        self,
        scope: PersonalLabScope,
        session_id: str,
        message_id: str,
        feedback: str,
        reason: str | None,
    ) -> str:
        """Persist feedback only for an assistant message in the current scope."""
        self.require_session(scope, session_id)
        feedback_id = str(uuid4())
        with _connection(scope) as connection:
            owned = connection.execute(
                "SELECT role FROM messages WHERE id = ? AND session_id = ?",
                (message_id, session_id),
            ).fetchone()
            if owned is None or owned["role"] != "assistant":
                raise PersonalChatNotFoundError
            connection.execute(
                """
                INSERT INTO feedback (id, session_id, message_id, feedback, reason, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (feedback_id, session_id, message_id, feedback, reason, _now()),
            )
        return feedback_id


class PersonalChatStateStore(_PersonalChatTurnStore):
    """Persist Personal Chat state inside the server-resolved scope root."""

    def rename_session(
        self, scope: PersonalLabScope, session_id: str, title: str
    ) -> PersonalChatSession:
        """Rename exactly one current-scope session."""
        self.require_session(scope, session_id)
        with _connection(scope) as connection:
            connection.execute(
                "UPDATE sessions SET title = ? WHERE id = ?",
                (title.strip()[:200], session_id),
            )
        return self.require_session(scope, session_id)

    def delete_session(self, scope: PersonalLabScope, session_id: str) -> None:
        """Delete a session and its messages/feedback transactionally."""
        self.require_session(scope, session_id)
        with _connection(scope) as connection:
            connection.execute("DELETE FROM sessions WHERE id = ?", (session_id,))

    def clear_messages(self, scope: PersonalLabScope, session_id: str) -> None:
        """Clear messages and dependent feedback without deleting the session."""
        self.require_session(scope, session_id)
        with _connection(scope) as connection:
            connection.execute(
                "DELETE FROM messages WHERE session_id = ?", (session_id,)
            )


@contextmanager
def _connection(scope: PersonalLabScope) -> Iterator[sqlite3.Connection]:
    path = _path(scope)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with sqlite3.connect(path) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            _create_schema(connection)
            yield connection
    except sqlite3.Error:
        raise PersonalChatStorageError from None


def _path(scope: PersonalLabScope) -> Path:
    return scope.data_root / "chat.sqlite"


def _require_session_row(connection: sqlite3.Connection, session_id: str) -> None:
    if (
        connection.execute(
            "SELECT 1 FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()
        is None
    ):
        raise PersonalChatNotFoundError


def _insert_message(
    connection: sqlite3.Connection,
    session_id: str,
    message: PersonalChatMessage,
) -> None:
    connection.execute(
        """
        INSERT INTO messages
        (id, session_id, role, content, created_at, in_reply_to, generated_from, citations)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            message.id,
            session_id,
            message.role,
            message.content,
            message.created_at,
            message.in_reply_to,
            message.generated_from,
            json.dumps(message.citations, ensure_ascii=False),
        ),
    )


def _create_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY, title TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS messages (
            id TEXT PRIMARY KEY, session_id TEXT NOT NULL, role TEXT NOT NULL,
            content TEXT NOT NULL, created_at TEXT NOT NULL, in_reply_to TEXT,
            generated_from TEXT, citations TEXT NOT NULL DEFAULT '[]',
            FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
        );
        CREATE UNIQUE INDEX IF NOT EXISTS one_response_per_turn
            ON messages(session_id, in_reply_to) WHERE in_reply_to IS NOT NULL;
        CREATE TABLE IF NOT EXISTS feedback (
            id TEXT PRIMARY KEY, session_id TEXT NOT NULL, message_id TEXT NOT NULL,
            feedback TEXT NOT NULL, reason TEXT, created_at TEXT NOT NULL,
            FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE,
            FOREIGN KEY (message_id) REFERENCES messages(id) ON DELETE CASCADE
        );
        """
    )


def _message(row: sqlite3.Row) -> PersonalChatMessage:
    try:
        citations = _CITATIONS_ADAPTER.validate_json(str(row["citations"]))
    except ValidationError:
        raise PersonalChatStorageError from None
    return PersonalChatMessage(
        id=str(row["id"]),
        role=str(row["role"]),
        content=str(row["content"]),
        created_at=str(row["created_at"]),
        in_reply_to=str(row["in_reply_to"]) if row["in_reply_to"] else None,
        generated_from=str(row["generated_from"]) if row["generated_from"] else None,
        citations=tuple(citations),
    )


def _now() -> str:
    return datetime.now(UTC).isoformat()
