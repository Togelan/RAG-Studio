\set ON_ERROR_STOP 1
SET ROLE service_role;
SELECT private.accept_workspace_invitation(
    repeat('a', 64),
    '00000000-0000-4000-8000-000000000205',
    'concurrent@example.test'
) AS membership_id;
RESET ROLE;
