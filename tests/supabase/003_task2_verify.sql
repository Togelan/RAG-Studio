\set ON_ERROR_STOP 1

SELECT task2_test.assert_true(
    (SELECT count(*) = 1
       FROM public.workspace_memberships
      WHERE workspace_id = '00000000-0000-4000-8000-000000000101'
        AND user_id = '00000000-0000-4000-8000-000000000205'
        AND role = 'admin'
        AND status = 'active'),
    'concurrent invitation acceptance created exactly one active membership'
);
SELECT task2_test.assert_true(
    (SELECT status = 'accepted'
            AND accepted_by = '00000000-0000-4000-8000-000000000205'
            AND accepted_at IS NOT NULL
       FROM public.workspace_invitations
      WHERE token_hash = repeat('a', 64)),
    'accepted invitation is one-use and records its recipient'
);

DO $$
BEGIN
    BEGIN
        PERFORM private.accept_workspace_invitation(
            repeat('a', 64),
            '00000000-0000-4000-8000-000000000206',
            'attacker@example.test'
        );
        RAISE EXCEPTION 'TASK2_ASSERTION_FAILED: token replay by another user succeeded';
    EXCEPTION WHEN invalid_authorization_specification THEN
        NULL;
    END;
END;
$$;

DO $$
BEGIN
    BEGIN
        PERFORM private.create_workspace_invitation(
            '00000000-0000-4000-8000-000000000101',
            'owner@example.test',
            'owner',
            repeat('b', 64),
            now() + interval '1 hour',
            '00000000-0000-4000-8000-000000000201'
        );
        RAISE EXCEPTION 'TASK2_ASSERTION_FAILED: invitation granted owner';
    EXCEPTION WHEN check_violation THEN
        NULL;
    END;
END;
$$;

INSERT INTO public.workspace_invitations (
    workspace_id, email, role, token_hash, created_at, expires_at, created_by
) VALUES (
    '00000000-0000-4000-8000-000000000101',
    'expired@example.test',
    'member',
    repeat('c', 64),
    now() - interval '2 hours',
    now() - interval '1 minute',
    '00000000-0000-4000-8000-000000000201'
);

DO $$
BEGIN
    BEGIN
        PERFORM private.accept_workspace_invitation(
            repeat('c', 64),
            '00000000-0000-4000-8000-000000000208',
            'expired@example.test'
        );
        RAISE EXCEPTION 'TASK2_ASSERTION_FAILED: expired invitation succeeded';
    EXCEPTION WHEN invalid_authorization_specification THEN
        NULL;
    END;
END;
$$;

SELECT private.create_workspace_invitation(
    '00000000-0000-4000-8000-000000000101',
    'revoked@example.test',
    'member',
    repeat('d', 64),
    now() + interval '1 hour',
    '00000000-0000-4000-8000-000000000201'
);
SELECT private.revoke_workspace_invitation(
    (SELECT id FROM public.workspace_invitations WHERE token_hash = repeat('d', 64)),
    '00000000-0000-4000-8000-000000000101',
    '00000000-0000-4000-8000-000000000201'
);

DO $$
BEGIN
    BEGIN
        PERFORM private.accept_workspace_invitation(
            repeat('d', 64),
            '00000000-0000-4000-8000-000000000209',
            'revoked@example.test'
        );
        RAISE EXCEPTION 'TASK2_ASSERTION_FAILED: revoked invitation succeeded';
    EXCEPTION WHEN invalid_authorization_specification THEN
        NULL;
    END;
END;
$$;

SELECT private.transfer_workspace_ownership(
    '00000000-0000-4000-8000-000000000101',
    '00000000-0000-4000-8000-000000000201',
    '00000000-0000-4000-8000-000000000203'
);
SELECT task2_test.assert_true(
    (SELECT role = 'admin'
       FROM public.workspace_memberships
      WHERE workspace_id = '00000000-0000-4000-8000-000000000101'
        AND user_id = '00000000-0000-4000-8000-000000000201'),
    'former owner was demoted to admin'
);
SELECT task2_test.assert_true(
    (SELECT role = 'owner'
       FROM public.workspace_memberships
      WHERE workspace_id = '00000000-0000-4000-8000-000000000101'
        AND user_id = '00000000-0000-4000-8000-000000000203'),
    'existing active admin became sole owner'
);

DO $$
BEGIN
    BEGIN
        PERFORM private.transfer_workspace_ownership(
            '00000000-0000-4000-8000-000000000101',
            '00000000-0000-4000-8000-000000000203',
            '00000000-0000-4000-8000-000000000204'
        );
        RAISE EXCEPTION 'TASK2_ASSERTION_FAILED: member became owner';
    EXCEPTION WHEN check_violation THEN
        NULL;
    END;
END;
$$;

SELECT private.claim_workspace_collection(
    '00000000-0000-4000-8000-000000000101'
);
SELECT private.complete_workspace_collection(
    '00000000-0000-4000-8000-000000000101', false, 'qdrant_unavailable'
);
SELECT private.claim_workspace_collection(
    '00000000-0000-4000-8000-000000000101'
);
SELECT private.complete_workspace_collection(
    '00000000-0000-4000-8000-000000000101', true, NULL
);
SELECT task2_test.assert_true(
    (SELECT state = 'ready' AND attempt_count = 2 AND last_error_code IS NULL
       FROM public.workspace_collection_registry
      WHERE workspace_id = '00000000-0000-4000-8000-000000000101'),
    'collection provisioning failure is retry-safe'
);

DO $$
DECLARE
    alpha_collection text;
BEGIN
    SELECT collection_name INTO alpha_collection
      FROM public.workspace_collection_registry
     WHERE workspace_id = '00000000-0000-4000-8000-000000000101';
    BEGIN
        UPDATE public.workspace_collection_registry
           SET collection_name = alpha_collection
         WHERE workspace_id = '00000000-0000-4000-8000-000000000102';
        RAISE EXCEPTION 'TASK2_ASSERTION_FAILED: collection collision succeeded';
    EXCEPTION WHEN unique_violation THEN
        NULL;
    END;
END;
$$;

SELECT private.archive_workspace(
    '00000000-0000-4000-8000-000000000101',
    '00000000-0000-4000-8000-000000000203'
);

BEGIN;
SET LOCAL ROLE authenticated;
SELECT set_config('request.jwt.claim.sub', '00000000-0000-4000-8000-000000000201', true);
SELECT task2_test.assert_true(
    (SELECT count(*) = 0 FROM public.workspaces),
    'archive immediately denies an already-issued owner JWT'
);
SELECT task2_test.assert_true(
    (SELECT count(*) = 0 FROM public.workspace_memberships),
    'archive immediately hides all membership rows'
);
ROLLBACK;

SELECT task2_test.assert_true(
    (SELECT state = 'archived'
       FROM public.workspace_collection_registry
      WHERE workspace_id = '00000000-0000-4000-8000-000000000101'),
    'archive marks collection registry unavailable'
);
SELECT task2_test.assert_true(
    (SELECT count(*) >= 3
       FROM public.workspace_audit_events
      WHERE workspace_id = '00000000-0000-4000-8000-000000000101'
        AND event_type IN ('invitation.accepted', 'ownership.transferred', 'workspace.archived')),
    'security-sensitive lifecycle changes are audited'
);

\echo TASK2_VERIFY_OK
