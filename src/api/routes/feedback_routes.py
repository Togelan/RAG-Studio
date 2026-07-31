"""FastAPI router for chat message feedback (like/dislike)."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/chat", tags=["chat"])

logger = logging.getLogger(__name__)


class FeedbackSubmit(BaseModel):
    """Request schema for submitting message feedback."""

    session_id: str = Field(..., description="Session containing the message.")
    message_id: str = Field(..., description="ID of the message receiving feedback.")
    feedback: str = Field(
        ...,
        pattern=r"^(positive|negative)$",
        description="Feedback type: 'positive' or 'negative'.",
    )
    reason: str | None = Field(
        default=None,
        description="Optional reason for negative feedback.",
        max_length=1000,
    )


@router.post("/feedback", status_code=201)
async def submit_feedback(
    body: FeedbackSubmit,
) -> dict[str, str]:
    """Submit feedback (like/dislike) for an assistant message.

    Feedback is stored in ~/.rag-studio/feedback.jsonl for future analysis.

    Args:
        body: Feedback details including session_id, message_id, and feedback type.

    Returns:
        Confirmation message.
    """
    # Determine feedback file path
    feedback_dir = Path.home() / ".rag-studio"
    feedback_dir.mkdir(parents=True, exist_ok=True)
    feedback_path = feedback_dir / "feedback.jsonl"

    record: dict[str, object] = {
        "session_id": body.session_id,
        "message_id": body.message_id,
        "feedback": body.feedback,
        "reason": body.reason,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    with open(feedback_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

    logger.info(
        "Feedback recorded: session=%s, message=%s, feedback=%s",
        body.session_id,
        body.message_id,
        body.feedback,
    )
    return {"status": "saved", "feedback": body.feedback}
