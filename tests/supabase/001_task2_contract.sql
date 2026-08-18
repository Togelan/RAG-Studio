\set ON_ERROR_STOP 1

CREATE SCHEMA IF NOT EXISTS task2_test;

CREATE OR REPLACE FUNCTION task2_test.assert_true(value boolean, message text)
RETURNS void
LANGUAGE plpgsql
AS $$
BEGIN
    IF value IS DISTINCT FROM true THEN
        RAISE EXCEPTION 'TASK2_ASSERTION_FAILED: %', message;
    END IF;
END;
$$;

CREATE OR REPLACE FUNCTION task2_test.cross_workspace_invite_is_denied()
RETURNS boolean
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = pg_catalog, public
AS $$
BEGIN
    INSERT INTO public.workspace_invitations (
        workspace_id,
        email,
        role,
        token_hash,
        expires_at,
        created_by
    ) VALUES (
        '00000000-0000-4000-8000-000000000102',
        'tamper@example.test',
        'member',
        repeat('9', 64),
        now() + interval '1 hour',
        '00000000-0000-4000-8000-000000000201'
    );
    RETURN false;
EXCEPTION
    WHEN insufficient_privilege OR check_violation OR foreign_key_violation THEN
        RETURN true;
END;
$$;

GRANT USAGE ON SCHEMA task2_test TO authenticated;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA task2_test TO authenticated;

TRUNCATE TABLE
    public.workspace_audit_events,
    public.workspace_invitations,
    public.workspace_collection_registry,
    public.workspace_memberships,
    public.workspaces
CASCADE;

BEGIN;
INSERT INTO public.workspaces (id, name, created_by) VALUES
    ('00000000-0000-4000-8000-000000000101', 'Alpha', '00000000-0000-4000-8000-000000000201'),
    ('00000000-0000-4000-8000-000000000102', 'Beta', '00000000-0000-4000-8000-000000000202');
INSERT INTO public.workspace_memberships (workspace_id, user_id, role) VALUES
    ('00000000-0000-4000-8000-000000000101', '00000000-0000-4000-8000-000000000201', 'owner'),
    ('00000000-0000-4000-8000-000000000101', '00000000-0000-4000-8000-000000000203', 'admin'),
    ('00000000-0000-4000-8000-000000000101', '00000000-0000-4000-8000-000000000204', 'member'),
    ('00000000-0000-4000-8000-000000000102', '00000000-0000-4000-8000-000000000202', 'owner');
COMMIT;

SELECT task2_test.assert_true(
    (SELECT count(*) = 2 FROM public.workspaces),
    'two workspaces were created'
);
SELECT task2_test.assert_true(
    (SELECT count(*) = 2 AND count(DISTINCT collection_name) = 2
       FROM public.workspace_collection_registry),
    'each workspace has a distinct collection registry row'
);

DO $$
BEGIN
    BEGIN
        INSERT INTO public.workspace_memberships (workspace_id, user_id, role)
        VALUES (
            '00000000-0000-4000-8000-000000000101',
            '00000000-0000-4000-8000-000000000207',
            'owner'
        );
        RAISE EXCEPTION 'TASK2_ASSERTION_FAILED: second active owner was accepted';
    EXCEPTION WHEN unique_violation THEN
        NULL;
    END;
END;
$$;

DO $$
BEGIN
    BEGIN
        UPDATE public.workspace_memberships
           SET status = 'revoked', revoked_at = now()
         WHERE workspace_id = '00000000-0000-4000-8000-000000000102'
           AND user_id = '00000000-0000-4000-8000-000000000202';
        SET CONSTRAINTS ALL IMMEDIATE;
        RAISE EXCEPTION 'TASK2_ASSERTION_FAILED: sole owner revocation was accepted';
    EXCEPTION WHEN check_violation THEN
        NULL;
    END;
END;
$$;

DO $$
BEGIN
    BEGIN
        INSERT INTO public.workspace_memberships (workspace_id, user_id, role)
        VALUES (
            '00000000-0000-4000-8000-000000000101',
            '00000000-0000-4000-8000-000000000203',
            'member'
        );
        RAISE EXCEPTION 'TASK2_ASSERTION_FAILED: duplicate membership was accepted';
    EXCEPTION WHEN unique_violation THEN
        NULL;
    END;
END;
$$;

BEGIN;
SET LOCAL ROLE authenticated;
SELECT set_config('request.jwt.claim.sub', '00000000-0000-4000-8000-000000000201', true);
SELECT task2_test.assert_true(
    (SELECT count(*) = 1 FROM public.workspaces),
    'owner JWT sees only its active workspace'
);
SELECT task2_test.assert_true(
    (SELECT bool_and(workspace_id = '00000000-0000-4000-8000-000000000101')
       FROM public.workspace_memberships),
    'owner JWT sees no cross-workspace memberships'
);
SELECT task2_test.assert_true(
    task2_test.cross_workspace_invite_is_denied(),
    'workspace UUID/body tampering is denied without a partial invitation'
);
ROLLBACK;

BEGIN;
SET LOCAL ROLE authenticated;
SELECT set_config('request.jwt.claim.sub', '00000000-0000-4000-8000-000000000202', true);
SELECT task2_test.assert_true(
    (SELECT count(*) = 1 FROM public.workspaces),
    'second JWT sees only its own workspace'
);
SELECT task2_test.assert_true(
    NOT has_table_privilege('authenticated', 'public.workspace_collection_registry', 'SELECT'),
    'raw collection names are not exposed to authenticated users'
);
SELECT task2_test.assert_true(
    NOT has_function_privilege(
        'authenticated',
        'private.accept_workspace_invitation(text,uuid,text)',
        'EXECUTE'
    ),
    'authenticated clients cannot call the service-only acceptance function'
);
ROLLBACK;

SET ROLE service_role;
SELECT private.create_workspace_invitation(
    '00000000-0000-4000-8000-000000000101',
    'concurrent@example.test',
    'admin',
    repeat('a', 64),
    now() + interval '1 hour',
    '00000000-0000-4000-8000-000000000201'
);
RESET ROLE;

\echo TASK2_SETUP_OK
