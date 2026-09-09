from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID, uuid4

import anyio
import asyncpg
import pytest

from src.api.mvp_publication import PublicationState
from src.api.mvp_publication_store import (
    PostgresMvpPublicationStore,
    PublicationStoreUnavailableError,
)

ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS = (
    ROOT / "docker/stage3/001-auth-schema.sql",
    ROOT / "supabase/migrations/20260816165319_stage3_tenant_schema.sql",
    ROOT / "supabase/migrations/20260816170226_stage3_tenant_routines_rls.sql",
    ROOT / "supabase/migrations/20260816170824_stage3_tenant_rls_grants.sql",
    ROOT / "supabase/migrations/20260817090000_stage3_chatbot_lifecycle.sql",
    ROOT / "supabase/migrations/20260820090000_group1_accounts_sessions.sql",
    ROOT / "supabase/migrations/20260821090000_group2_personal_labs.sql",
    ROOT / "supabase/migrations/20260825120000_mvp_personal_lab_billing_widget.sql",
)


@pytest.mark.integration
def test_postgres_publication_races_and_faults_are_atomic() -> None:
    # Given: an administrator connection capable of creating one disposable database.
    admin_url = os.environ.get("RAG_STUDIO_MVP_DISPOSABLE_DATABASE_URL")
    if admin_url is None:
        pytest.skip("set RAG_STUDIO_MVP_DISPOSABLE_DATABASE_URL for live proof")

    # When/Then: real procedures serialize races, retain audit, and roll back faults.
    anyio.run(_exercise_disposable_database, admin_url)


async def _exercise_disposable_database(admin_url: str) -> None:
    database_name = f"ragstudio_task6_{uuid4().hex}"
    database_url = _database_url(admin_url, database_name)
    admin = await asyncpg.connect(admin_url, timeout=10)
    created = False
    try:
        await admin.execute(f'CREATE DATABASE "{database_name}"')
        created = True
        await _exercise_store(database_url)
    finally:
        if created:
            await admin.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname=$1 AND pid<>pg_backend_pid()",
                database_name,
            )
            await admin.execute(f'DROP DATABASE "{database_name}"')
            remaining = await admin.fetchval(
                "SELECT count(*) FROM pg_database WHERE datname=$1", database_name
            )
            assert remaining == 0
        await admin.close(timeout=10)


async def _exercise_store(database_url: str) -> None:
    connection = await asyncpg.connect(database_url, timeout=10)
    lab_id, user_id = uuid4(), uuid4()
    try:
        for migration in MIGRATIONS:
            await connection.execute(migration.read_text(encoding="utf-8"))
        await connection.execute(
            "INSERT INTO public.personal_labs (id,user_id) VALUES ($1,$2)",
            lab_id,
            user_id,
        )
        store = PostgresMvpPublicationStore(database_url)
        published: list[UUID] = []

        async def publish_once() -> None:
            publication = await store.publish(lab_id, "HTTPS://Widget.Example.TEST:443")
            published.append(publication.id)

        async with anyio.create_task_group() as tasks:
            for _ in range(10):
                tasks.start_soon(publish_once)

        current = await store.read(lab_id)
        assert current is not None
        assert len(set(published)) == 1
        assert current.state is PublicationState.ENABLED
        assert current.key_version == 1
        assert len(current.audit) == 1

        disabled = await store.disable(lab_id)
        fresh = await PostgresMvpPublicationStore(database_url).read(lab_id)
        assert disabled is not None and fresh == disabled
        assert fresh.state is PublicationState.DISABLED

        rotated_versions: list[int] = []

        async def rotate_once() -> None:
            rotated = await store.rotate(lab_id)
            assert rotated is not None
            rotated_versions.append(rotated.key_version)

        async with anyio.create_task_group() as tasks:
            tasks.start_soon(rotate_once)
            tasks.start_soon(rotate_once)
        assert sorted(rotated_versions) == [2, 3]

        before_fault = await store.read(lab_id)
        assert before_fault is not None
        await _install_revoke_fault(connection)
        with pytest.raises(PublicationStoreUnavailableError):
            await store.revoke(lab_id)
        after_fault = await store.read(lab_id)
        assert after_fault == before_fault
        await connection.execute(
            "DROP TRIGGER task6_revoke_fault ON "
            "public.personal_lab_widget_publication_audit"
        )
        await connection.execute("DROP FUNCTION private.task6_revoke_fault()")

        revoked = await store.revoke(lab_id)
        replay = await store.revoke(lab_id)
        assert revoked is not None and replay == revoked
        assert revoked.state is PublicationState.REVOKED
        assert revoked.key_version == 4
        assert tuple(event.event_type.value for event in revoked.audit) == (
            "published",
            "disabled",
            "key_rotated",
            "key_rotated",
            "key_rotated",
            "revoked",
        )
    finally:
        await connection.close(timeout=10)


async def _install_revoke_fault(connection: asyncpg.Connection) -> None:
    await connection.execute(
        "CREATE FUNCTION private.task6_revoke_fault() RETURNS trigger "
        "LANGUAGE plpgsql AS $$ BEGIN "
        "IF NEW.event_type='revoked' THEN RAISE EXCEPTION 'injected'; END IF; "
        "RETURN NEW; END $$"
    )
    await connection.execute(
        "CREATE TRIGGER task6_revoke_fault BEFORE INSERT ON "
        "public.personal_lab_widget_publication_audit FOR EACH ROW "
        "EXECUTE FUNCTION private.task6_revoke_fault()"
    )


def _database_url(admin_url: str, database_name: str) -> str:
    parsed = urlsplit(admin_url)
    return urlunsplit(
        (parsed.scheme, parsed.netloc, f"/{database_name}", parsed.query, "")
    )
