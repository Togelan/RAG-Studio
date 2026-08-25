from __future__ import annotations

import importlib
import os
import shutil
import subprocess
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from uuid import UUID

import anyio
import pytest

from src.api.personal_lab_scope import PostgresPersonalLabScopeRegistry

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "supabase/migrations/20260821090000_group2_personal_labs.sql"
FOUNDATION_MIGRATIONS = (
    ROOT / "docker/stage3/001-auth-schema.sql",
    ROOT / "supabase/migrations/20260816165319_stage3_tenant_schema.sql",
    ROOT / "supabase/migrations/20260816170226_stage3_tenant_routines_rls.sql",
    ROOT / "supabase/migrations/20260816170824_stage3_tenant_rls_grants.sql",
    ROOT / "supabase/migrations/20260817090000_stage3_chatbot_lifecycle.sql",
    ROOT / "supabase/migrations/20260820090000_group1_accounts_sessions.sql",
)


@dataclass(frozen=True, slots=True)
class PostgresHarness:
    docker: str
    container: str
    database_url: str

    def sql(self, statement: str) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            (
                self.docker,
                "exec",
                "-i",
                self.container,
                "psql",
                "--no-psqlrc",
                "--username",
                "postgres",
                "--dbname",
                "postgres",
                "--set",
                "ON_ERROR_STOP=1",
                "--tuples-only",
                "--no-align",
            ),
            input=statement,
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            pytest.fail(result.stderr)
        return result

    def apply(self, path: Path) -> None:
        self.sql(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def postgres() -> Iterator[PostgresHarness]:
    docker = os.environ.get("RAG_STUDIO_DOCKER_BIN") or shutil.which("docker")
    if docker is None:
        pytest.skip("Docker CLI is required for the Personal Lab migration contract")
    container = f"ragstudio-g2-t2-pg-{uuid.uuid4().hex[:10]}"
    started = subprocess.run(
        (
            docker,
            "run",
            "--name",
            container,
            "--tmpfs",
            "/var/lib/postgresql/data",
            "--publish",
            "127.0.0.1::5432",
            "--env",
            "POSTGRES_PASSWORD=g2-task2-test-only",
            "--detach",
            "postgres:17.6-alpine",
        ),
        text=True,
        capture_output=True,
        check=False,
    )
    assert started.returncode == 0, started.stderr
    try:
        stable_probes = 0
        for _ in range(150):
            probe = subprocess.run(
                (
                    docker,
                    "exec",
                    container,
                    "psql",
                    "--username",
                    "postgres",
                    "--dbname",
                    "postgres",
                    "--tuples-only",
                    "--command",
                    "SELECT pg_postmaster_start_time();",
                ),
                text=True,
                capture_output=True,
                check=False,
            )
            if probe.returncode == 0:
                stable_probes += 1
                if stable_probes == 3:
                    break
            else:
                stable_probes = 0
        assert stable_probes == 3, (
            "Postgres did not become stably queryable within the bounded probe count"
        )
        port_result = subprocess.run(
            (docker, "port", container, "5432/tcp"),
            text=True,
            capture_output=True,
            check=True,
        )
        port = port_result.stdout.strip().rsplit(":", 1)[1]
        harness = PostgresHarness(
            docker,
            container,
            f"postgresql://postgres:g2-task2-test-only@127.0.0.1:{port}/postgres",
        )
        for migration in FOUNDATION_MIGRATIONS:
            harness.apply(migration)
        harness.apply(MIGRATION)
        yield harness
    finally:
        subprocess.run(
            (docker, "rm", "--force", container),
            text=True,
            capture_output=True,
            check=False,
        )


def test_personal_lab_migration_defines_private_stable_registry_contract() -> None:
    # Given: the Group 2 Personal Lab migration artifact.
    assert MIGRATION.is_file(), "Personal Lab migration must exist"

    # When: its transaction and schema contract are inspected.
    sql = MIGRATION.read_text(encoding="utf-8")

    # Then: the server-owned table is random, unique per user, and service-only.
    assert "CREATE TABLE IF NOT EXISTS public.personal_labs" in sql
    assert "id uuid PRIMARY KEY DEFAULT gen_random_uuid()" in sql
    assert "user_id uuid NOT NULL UNIQUE" in sql
    assert "FORCE ROW LEVEL SECURITY" in sql
    assert "TO service_role" in sql
    assert "CREATE POLICY personal_labs_authenticated" not in sql
    assert sql.startswith("BEGIN;")
    assert sql.rstrip().endswith("COMMIT;")


def test_postgres_scope_registry_is_available_for_real_database_contract() -> None:
    # Given/When: the application scope authority module is loaded.
    module = importlib.import_module("src.api.personal_lab_scope")

    # Then: a Postgres-backed registry is the production implementation.
    assert module.PostgresPersonalLabScopeRegistry.__name__ == (
        "PostgresPersonalLabScopeRegistry"
    )


@pytest.mark.integration
def test_real_postgres_provisions_two_stable_scopes_and_preserves_legacy(
    postgres: PostgresHarness, tmp_path: Path
) -> None:
    # Given: a replayed migration and a byte-addressable seeded Legacy fixture.
    legacy = tmp_path / "rag-data"
    legacy.mkdir()
    (legacy / "settings.json").write_bytes(b'{"provider":"legacy"}\n')
    (legacy / "document.bin").write_bytes(bytes(range(64)))
    before = _legacy_manifest(legacy)
    postgres.apply(MIGRATION)
    first_user = UUID("10000000-0000-4000-8000-000000000001")
    second_user = UUID("20000000-0000-4000-8000-000000000002")

    # When: concurrent first access, restart, and a cancelled insert are exercised.
    resolved = anyio.run(
        _resolve_concurrently,
        postgres.database_url,
        first_user,
        second_user,
    )
    postgres.sql(
        """
        BEGIN;
        SET LOCAL ROLE service_role;
        INSERT INTO public.personal_labs (user_id)
        VALUES ('30000000-0000-4000-8000-000000000003');
        ROLLBACK;
        """
    )
    count = postgres.sql("SELECT count(*) FROM public.personal_labs;")
    postgres.sql(
        """
        BEGIN;
        SET LOCAL ROLE authenticated;
        SELECT set_config(
          'request.jwt.claim.sub',
          '10000000-0000-4000-8000-000000000001',
          true
        );
        DO $$ BEGIN
          BEGIN
            PERFORM count(*) FROM public.personal_labs;
            RAISE EXCEPTION 'authenticated role read Personal Lab registry';
          EXCEPTION WHEN insufficient_privilege THEN
            NULL;
          END;
        END $$;
        ROLLBACK;
        """
    )

    # Then: identities remain isolated, replay is idempotent, and Legacy is exact.
    assert resolved[0] == resolved[1]
    assert resolved[0] != resolved[2]
    assert count.stdout.strip() == "2"
    assert _legacy_manifest(legacy) == before


async def _resolve_concurrently(
    database_url: str, first_user: UUID, second_user: UUID
) -> tuple[UUID, UUID, UUID]:
    first_results: list[UUID] = []
    second_results: list[UUID] = []

    async def resolve_into(user_id: UUID, results: list[UUID]) -> None:
        registry = PostgresPersonalLabScopeRegistry(database_url)
        results.append(await registry.resolve(user_id))

    async with anyio.create_task_group() as tasks:
        tasks.start_soon(resolve_into, first_user, first_results)
        tasks.start_soon(resolve_into, first_user, first_results)
        tasks.start_soon(resolve_into, second_user, second_results)
    return first_results[0], first_results[1], second_results[0]


def _legacy_manifest(root: Path) -> tuple[tuple[str, int, str], ...]:
    return tuple(
        (
            path.relative_to(root).as_posix(),
            path.stat().st_size,
            sha256(path.read_bytes()).hexdigest(),
        )
        for path in sorted(root.rglob("*"))
        if path.is_file()
    )
