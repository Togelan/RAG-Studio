"""Prompt injection detection and sanitization (SEC-H01).

Provides detect_prompt_injection() for defense-in-depth against
adversarial user messages that attempt to override system instructions.
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

# Patterns that should be STRIPPED (system-level token injection)
_STRIP_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"<\|im_start\|>", re.IGNORECASE),
    re.compile(r"<\|im_end\|>", re.IGNORECASE),
    re.compile(r"<<SYS>>", re.IGNORECASE),
    re.compile(r"\[INST\]", re.IGNORECASE),
    re.compile(r"\[/INST\]", re.IGNORECASE),
]

# Patterns that should FLAG but not strip (social engineering injections)
_FLAG_PATTERNS: list[re.Pattern[str]] = [
    re.compile(
        r"ignore\s+(all\s+)?(previous|prior|above)\s+(instructions?|prompts?)",
        re.IGNORECASE,
    ),
    re.compile(
        r"you\s+are\s+now\s+(DAN|jailbroken|unrestricted)",
        re.IGNORECASE,
    ),
    re.compile(r"pretend\s+(you\s+are|to\s+be)", re.IGNORECASE),
    re.compile(
        r"new\s+system\s+(prompt|message|instruction)",
        re.IGNORECASE,
    ),
    re.compile(r"forget\s+(all\s+)?(your\s+)?training", re.IGNORECASE),
]


def detect_prompt_injection(text: str) -> tuple[str, bool]:
    """Detect and sanitize prompt injection patterns.

    System tokens like <|im_start|> are STRIPPED from the output.
    Social engineering patterns (DAN, ignore instructions, etc.) are
    FLAGGED in logs but preserved in the text — delimiter wrapping in
    graph nodes provides defense-in-depth.

    Args:
        text: The raw user input to scan.

    Returns:
        A tuple of (sanitized_text, was_flagged).
        sanitized_text has system tokens replaced with [REMOVED].
        was_flagged is True if any injection pattern was detected.
    """
    sanitized = text
    was_stripped = False

    for pattern in _STRIP_PATTERNS:
        if pattern.search(sanitized):
            was_stripped = True
            sanitized = pattern.sub("[REMOVED]", sanitized)
            logger.warning(
                "Prompt injection: stripped system token matching '%s'",
                pattern.pattern,
            )

    was_flagged = was_stripped
    for pattern in _FLAG_PATTERNS:
        match = pattern.search(text)
        if match:
            was_flagged = True
            logger.warning(
                "Prompt injection: flagged pattern '%s' in message: %.100s",
                pattern.pattern,
                text,
            )
            break  # One warning is enough — avoid log spam

    if was_flagged:
        logger.info(
            "Prompt injection summary: stripped=%s, total_flagged=%s, "
            "original_len=%d, sanitized_len=%d",
            was_stripped,
            was_flagged,
            len(text),
            len(sanitized),
        )

    return sanitized, was_flagged
