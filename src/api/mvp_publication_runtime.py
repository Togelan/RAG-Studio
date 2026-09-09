"""Fail-closed runtime gate for Personal Lab publication management."""

from __future__ import annotations

import os
from typing import Final, Literal, assert_never

from pydantic import BaseModel, ConfigDict

_ENABLED_ENV: Final = "RAG_STUDIO_PUBLICATION_ENABLED"


class _PublicationFeatureFlag(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    enabled: Literal["true", "false"]


def load_publication_enabled() -> bool:
    """Return the independently configured, fail-closed publication state."""
    feature = _PublicationFeatureFlag.model_validate(
        {"enabled": os.getenv(_ENABLED_ENV, "false").strip().lower()}
    )
    match feature.enabled:
        case "true":
            return True
        case "false":
            return False
        case unreachable:
            assert_never(unreachable)
