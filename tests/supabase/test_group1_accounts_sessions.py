from __future__ import annotations

import os
import shutil
import subprocess
import time
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "supabase/migrations/20260820090000_group1_accounts_sessions.sql"
BASE_MIGRATIONS = (
    ROOT / "docker/stage3/001-auth-schema.sql",
    ROOT / "supabase/migrations/20260816165319_stage3_tenant_schema.sql",
    ROOT / "supabase/migrations/20260816170226_stage3_tenant_routines_rls.sql",
    ROOT / "supabase/migrations/20260816170824_stage3_tenant_rls_grants.sql",
    ROOT / "supabase/migrations/20260817090000_stage3_chatbot_lifecycle.sql",
)


@dataclass(frozen=True, slots=True)
class PostgresHarness:
    docker: str
    container: str

    def sql(
        self, database: str, statement: str, *, check: bool = True
    ) -> subprocess.CompletedProcess[str]:
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
                database,
                "--set",
                "ON_ERROR_STOP=1",
            ),
            input=statement,
            text=True,
            capture_output=True,
            check=False,
        )
        if check and result.returncode != 0:
            pytest.fail(result.stderr)
        return result

    def apply(self, database: str, path: Path, *, check: bool = True) -> None:
        self.sql(database, path.read_text(encoding="utf-8"), check=check)


def _docker_binary() -> str:
    configured = os.environ.get("RAG_STUDIO_DOCKER_BIN")
    discovered = shutil.which("docker")
    if configured:
        return configured
    if discovered:
        return discovered
    pytest.skip("Docker CLI is required for the direct-Postgres migration contract")


@pytest.fixture(scope="module")
def postgres() -> Iterator[PostgresHarness]:
    docker = _docker_binary()
    suffix = uuid.uuid4().hex[:10]
    container = f"ragstudio-g1-t1-pytest-{suffix}"
    subprocess.run(
        (
            docker,
            "run",
            "--name",
            container,
            "--tmpfs",
            "/var/lib/postgresql/data",
            "--env",
            "POSTGRES_PASSWORD=task1-test-only",
            "--detach",
            "postgres:17.6-alpine",
        ),
        check=True,
        capture_output=True,
        text=True,
    )
    harness = PostgresHarness(docker=docker, container=container)
    try:
        deadline = time.monotonic() + 30
        postmaster_started_at = ""
        while time.monotonic() < deadline:
            ready = harness.sql(
                "postgres", "SELECT pg_postmaster_start_time();", check=False
            )
            current_start = ready.stdout.strip()
            if ready.returncode == 0 and current_start == postmaster_started_at:
                break
            postmaster_started_at = current_start if ready.returncode == 0 else ""
            time.sleep(0.2)
        else:
            pytest.fail("Postgres did not become stably queryable within 30 seconds")
        yield harness
    finally:
        subprocess.run(
            (docker, "rm", "--force", container),
            check=False,
            capture_output=True,
            text=True,
        )


def _prepare(
    postgres: PostgresHarness, database: str, *, invalid_owner: bool = False
) -> None:
    postgres.sql("postgres", f"CREATE DATABASE {database};")
    for migration in BASE_MIGRATIONS:
        postgres.apply(database, migration)
    owner_status = "'revoked', now()" if invalid_owner else "'active', NULL"
    workspace_state = (
        "'archived', now(), '20000000-0000-4000-8000-000000000002'"
        if invalid_owner
        else "'active', NULL, NULL"
    )
    postgres.sql(
        database,
        f"""
        BEGIN;
        INSERT INTO public.workspaces
            (id, name, status, created_by, archived_at, archived_by) VALUES
        ('10000000-0000-4000-8000-000000000001', 'Owned One', 'active',
         '20000000-0000-4000-8000-000000000001', NULL, NULL),
        ('10000000-0000-4000-8000-000000000002', 'Owned Two', 'active',
         '20000000-0000-4000-8000-000000000001', NULL, NULL),
        ('10000000-0000-4000-8000-000000000003', 'Foreign', {workspace_state.split(",")[0]},
         '20000000-0000-4000-8000-000000000002',
         {",".join(workspace_state.split(",")[1:])});
        INSERT INTO public.workspace_memberships
            (workspace_id, user_id, role, status, revoked_at) VALUES
        ('10000000-0000-4000-8000-000000000001',
         '20000000-0000-4000-8000-000000000001', 'owner', 'active', NULL),
        ('10000000-0000-4000-8000-000000000002',
         '20000000-0000-4000-8000-000000000001', 'owner', 'active', NULL),
        ('10000000-0000-4000-8000-000000000003',
         '20000000-0000-4000-8000-000000000002', 'owner', {owner_status});
        {"" if invalid_owner else "INSERT INTO public.workspace_memberships (workspace_id, user_id, role) VALUES ('10000000-0000-4000-8000-000000000003', '20000000-0000-4000-8000-000000000001', 'member');"}
        INSERT INTO public.workspace_chatbots
            (id, workspace_id, idempotency_key_hash, name_en, name_ru,
             provider, model_name, created_by, updated_by) VALUES
        ('30000000-0000-4000-8000-000000000001',
         '10000000-0000-4000-8000-000000000001', repeat('a', 64),
         'Owned Bot', 'Owned Bot', 'openai', 'test-model',
         '20000000-0000-4000-8000-000000000001',
         '20000000-0000-4000-8000-000000000001');
        COMMIT;
        """,
    )


@pytest.mark.integration
def test_backfill_is_deterministic_idempotent_and_preserves_tenant_rows(
    postgres: PostgresHarness,
) -> None:
    _prepare(postgres, "task1_happy")

    postgres.apply("task1_happy", MIGRATION)
    postgres.apply("task1_happy", MIGRATION)

    postgres.sql(
        "task1_happy",
        """
        DO $$ BEGIN
          IF (SELECT count(*) FROM public.accounts) <> 2
             OR (SELECT count(*) FROM public.account_memberships) <> 2
             OR (SELECT count(*) FROM public.workspaces) <> 3
             OR (SELECT count(*) FROM public.workspace_memberships) <> 4
             OR (SELECT count(*) FROM public.workspace_collection_registry) <> 3
             OR (SELECT count(*) FROM public.workspace_chatbots) <> 1
             OR (SELECT count(DISTINCT account_id) FROM public.workspaces
                 WHERE created_by = '20000000-0000-4000-8000-000000000001') <> 1
             OR EXISTS (SELECT 1 FROM public.workspaces WHERE account_id IS NULL)
          THEN RAISE EXCEPTION 'backfill or preservation contract failed';
          END IF;
        END $$;
        BEGIN;
        INSERT INTO public.accounts (id, label)
        VALUES ('40000000-0000-4000-8000-000000000001', 'Constraint Probe');
        INSERT INTO public.account_memberships (account_id, user_id)
        VALUES ('40000000-0000-4000-8000-000000000001',
                '50000000-0000-4000-8000-000000000001');
        SET CONSTRAINTS ALL IMMEDIATE;
        ROLLBACK;
        """,
    )


@pytest.mark.integration
def test_rls_exposes_owned_account_and_foreign_workspace_label_only(
    postgres: PostgresHarness,
) -> None:
    _prepare(postgres, "task1_rls")
    postgres.apply("task1_rls", MIGRATION)

    postgres.sql(
        "task1_rls",
        """
        BEGIN;
        SET LOCAL ROLE authenticated;
        SELECT set_config('request.jwt.claim.sub',
          '20000000-0000-4000-8000-000000000001', true);
        DO $$ BEGIN
          IF (SELECT count(*) FROM public.account_owner_projection) <> 1
             OR (SELECT count(*) FROM public.workspace_account_labels) <> 3
             OR (SELECT count(*) FROM public.accounts) <> 1
             OR EXISTS (SELECT 1 FROM public.accounts
                        WHERE id = 'ffffffff-ffff-4fff-8fff-ffffffffffff')
             OR EXISTS (SELECT 1 FROM public.workspace_account_labels
                        WHERE workspace_id = 'ffffffff-ffff-4fff-8fff-ffffffffffff')
          THEN RAISE EXCEPTION 'account projection or tamper denial failed';
          END IF;
        END $$;
        ROLLBACK;
        SELECT 1 / CASE WHEN
          NOT has_table_privilege('authenticated', 'private.bff_sessions', 'SELECT')
          AND has_table_privilege('service_role', 'private.bff_sessions',
                                  'SELECT,INSERT,UPDATE,DELETE')
          THEN 1 ELSE 0 END;
        """,
    )


@pytest.mark.integration
def test_invalid_workspace_ownership_rolls_back_the_whole_migration(
    postgres: PostgresHarness,
) -> None:
    _prepare(postgres, "task1_invalid", invalid_owner=True)

    failed = postgres.sql(
        "task1_invalid", MIGRATION.read_text(encoding="utf-8"), check=False
    )

    assert failed.returncode != 0
    postgres.sql(
        "task1_invalid",
        """
        SELECT 1 / CASE WHEN to_regclass('public.accounts') IS NULL
          AND NOT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'workspaces'
              AND column_name = 'account_id')
          AND (SELECT count(*) FROM public.workspaces) = 3
          AND (SELECT count(*) FROM public.workspace_memberships) = 3
          AND (SELECT count(*) FROM public.workspace_collection_registry) = 3
          AND (SELECT count(*) FROM public.workspace_chatbots) = 1
          THEN 1 ELSE 0 END;
        """,
    )


@pytest.mark.integration
def test_private_session_shape_and_constraints_reject_tampering(
    postgres: PostgresHarness,
) -> None:
    _prepare(postgres, "task1_sessions")
    postgres.apply("task1_sessions", MIGRATION)

    postgres.sql(
        "task1_sessions",
        """
        BEGIN; SET ROLE service_role;
        INSERT INTO private.bff_sessions (user_id,email_ciphertext,session_handle_hmac,access_token_ciphertext,refresh_token_ciphertext,encryption_key_id,access_token_expires_at,refresh_token_expires_at)
        VALUES ('20000000-0000-4000-8000-000000000001',decode('eeff','hex'),repeat('e',64),decode('aabb','hex'),decode('ccdd','hex'),'key-1',now()+interval '5 minutes',now()+interval '1 hour');
        RESET ROLE; DO $$ DECLARE session_id uuid; owned_account uuid; foreign_workspace uuid; BEGIN
          SELECT id INTO session_id FROM private.bff_sessions;
          SELECT account_id INTO owned_account FROM public.workspaces WHERE id='10000000-0000-4000-8000-000000000001'; SELECT id INTO foreign_workspace FROM public.workspaces WHERE id='10000000-0000-4000-8000-000000000003';
          BEGIN UPDATE private.bff_sessions SET session_handle_hmac='bad' WHERE id=session_id; RAISE EXCEPTION 'malformed handle accepted'; EXCEPTION WHEN check_violation THEN NULL; END;
          BEGIN UPDATE private.bff_sessions SET active_account_id='ffffffff-ffff-4fff-8fff-ffffffffffff' WHERE id=session_id; RAISE EXCEPTION 'forged account accepted'; EXCEPTION WHEN foreign_key_violation THEN NULL; END;
          BEGIN UPDATE private.bff_sessions SET active_account_id=owned_account,active_workspace_id=foreign_workspace WHERE id=session_id; RAISE EXCEPTION 'mismatched selection accepted'; EXCEPTION WHEN check_violation THEN NULL; END;
          BEGIN UPDATE private.bff_sessions SET refresh_lease_id=gen_random_uuid() WHERE id=session_id; RAISE EXCEPTION 'unpaired lease accepted'; EXCEPTION WHEN check_violation THEN NULL; END;
          BEGIN UPDATE private.bff_sessions SET refresh_lease_id=gen_random_uuid(),refresh_lease_expires_at=created_at WHERE id=session_id;
            RAISE EXCEPTION 'expired lease accepted'; EXCEPTION WHEN check_violation THEN NULL; END;
        END $$;
        SELECT 1 / CASE WHEN
          (SELECT count(*) FROM information_schema.columns WHERE table_schema='private' AND table_name='bff_sessions' AND (column_name,data_type) IN
             (('email_ciphertext','bytea'),('active_account_id','uuid'),('active_workspace_id','uuid'),('last_used_at','timestamp with time zone'),('refresh_lease_id','uuid'),('refresh_lease_expires_at','timestamp with time zone')))=6
          AND (SELECT count(*) FROM pg_constraint WHERE conrelid='private.bff_sessions'::regclass AND conname IN ('bff_sessions_active_account_id_fkey','bff_sessions_active_workspace_id_fkey') AND confdeltype='n')=2
          AND (SELECT count(*) FROM pg_indexes WHERE schemaname='private' AND tablename='bff_sessions' AND indexname IN ('bff_sessions_refresh_expiry_idx','bff_sessions_refresh_lease_expiry_idx','bff_sessions_active_selection_idx'))=3
          AND (SELECT count(*) FROM private.bff_sessions WHERE session_handle_hmac=repeat('e',64)
             AND active_account_id IS NULL AND active_workspace_id IS NULL AND refresh_lease_id IS NULL)=1
          THEN 1 ELSE 0 END;
        ROLLBACK;
        """,
    )
