"""Schema for isolated tenant chat metadata and feedback persistence."""

from __future__ import annotations

from typing import Final

CHAT_SCHEMA: Final = """
CREATE TABLE IF NOT EXISTS chatbot_configurations (
    workspace_id TEXT NOT NULL,
    chatbot_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    model_name TEXT NOT NULL,
    instructions TEXT NOT NULL,
    workspace_all INTEGER NOT NULL,
    PRIMARY KEY (workspace_id, chatbot_id)
);
CREATE TABLE IF NOT EXISTS chat_sessions (
    workspace_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    chatbot_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    title TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (workspace_id, user_id, chatbot_id, session_id)
);
CREATE TABLE IF NOT EXISTS chat_feedback (
    workspace_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    chatbot_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    message_id TEXT NOT NULL,
    feedback TEXT NOT NULL,
    reason TEXT,
    PRIMARY KEY (workspace_id, user_id, chatbot_id, session_id, message_id),
    FOREIGN KEY (workspace_id, user_id, chatbot_id, session_id)
        REFERENCES chat_sessions(workspace_id, user_id, chatbot_id, session_id)
        ON DELETE CASCADE
);
"""
