from __future__ import annotations

from pathlib import Path

from src.api.saas_workspace_models import (
    WorkspaceErrorCode,
    WorkspaceOperationError,
)

_ROOT = Path(__file__).resolve().parents[2]


def test_compose_bootstrap_applies_canonical_tenant_migrations() -> None:
    # Given: the task-owned fresh Compose database bootstrap contract.
    compose = (_ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    # When: its mounted inputs and migration command are inspected.
    bootstrap_mount = "./supabase/migrations:/bootstrap/migrations:ro"
    canonical_glob = "/bootstrap/migrations/*.sql"

    # Then: the canonical migrations are applied after the auth compatibility schema.
    assert bootstrap_mount in compose
    assert canonical_glob in compose
    assert compose.index("/bootstrap/001-auth-schema.sql") < compose.index(
        canonical_glob
    )


def test_workspace_operation_error_allows_traceback_assignment() -> None:
    # Given: the sanitized typed exception crossing an async context boundary.
    error = WorkspaceOperationError(WorkspaceErrorCode.UNAVAILABLE)

    # When: contextlib-compatible traceback state is assigned.
    error.__traceback__ = None

    # Then: typed behavior and sanitized text remain intact.
    assert error.code is WorkspaceErrorCode.UNAVAILABLE
    assert str(error) == "workspace operation unavailable"
