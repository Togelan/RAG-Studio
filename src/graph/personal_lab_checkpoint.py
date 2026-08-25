"""Failure-preserving checkpoint storage for one Personal Lab scope."""

from __future__ import annotations

import os
import shutil
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class PersonalLabCheckpoint:
    """Own rollback around one scope-local LangGraph SQLite database."""

    path: Path

    @property
    def rollback_path(self) -> Path:
        """Return the task-local atomic rollback copy path."""
        return self.path.with_suffix(f"{self.path.suffix}.rollback")

    @contextmanager
    def preserve_on_failure(self) -> Iterator[None]:
        """Restore the prior database after exceptions or cancellation."""
        existed = self.path.exists()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if existed:
            shutil.copy2(self.path, self.rollback_path)
        try:
            yield
        except BaseException:  # noqa: BROAD_EXCEPT_OK -- cancellation rollback
            if existed:
                os.replace(self.rollback_path, self.path)
            else:
                self.path.unlink(missing_ok=True)
            raise
        else:
            self.rollback_path.unlink(missing_ok=True)
