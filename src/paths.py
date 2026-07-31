"""Canonical filesystem paths for RAG-Studio runtime data.

Runtime code must not depend on the process working directory for persisted
data. By default application data is kept in ``<project-root>/data``. Set
``RAG_STUDIO_DATA_ROOT`` to move that tree; relative overrides are resolved
from the project root so they are deterministic too.
"""

from __future__ import annotations

import os
from pathlib import Path

DATA_ROOT_ENV = "RAG_STUDIO_DATA_ROOT"
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def project_root() -> Path:
    """Return the absolute repository root containing the ``src`` package."""
    return PROJECT_ROOT


def resolve_project_path(path: str | Path) -> Path:
    """Return *path* as an absolute path, anchored at the project root."""
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = project_root() / candidate
    return candidate.resolve()


def data_root() -> Path:
    """Return the configured root for application-managed persistent data."""
    configured = os.getenv(DATA_ROOT_ENV)
    if configured:
        return resolve_project_path(configured)
    return project_root() / "data"


def data_path(*parts: str | Path) -> Path:
    """Return an absolute path below :func:`data_root`."""
    return data_root().joinpath(*parts)


def configured_path(environment_variable: str, *default_parts: str | Path) -> Path:
    """Use a component override, or otherwise return a data-root path.

    Existing overrides such as ``QDRANT_PATH`` and
    ``RAG_STUDIO_SETTINGS_PATH`` remain supported. Relative override values
    are anchored to the project root instead of the process working directory.
    """
    configured = os.getenv(environment_variable)
    if configured:
        return resolve_project_path(configured)
    return data_path(*default_parts)
