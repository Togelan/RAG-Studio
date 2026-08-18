DROP POLICY IF EXISTS workspaces_active_member_select ON public.workspaces;
CREATE POLICY workspaces_active_member_select ON public.workspaces
FOR SELECT TO authenticated
USING (private.has_active_membership(id));

DROP POLICY IF EXISTS memberships_active_workspace_select ON public.workspace_memberships;
CREATE POLICY memberships_active_workspace_select ON public.workspace_memberships
FOR SELECT TO authenticated
USING (private.has_active_membership(workspace_id));

DROP POLICY IF EXISTS invitations_admin_select ON public.workspace_invitations;
CREATE POLICY invitations_admin_select ON public.workspace_invitations
FOR SELECT TO authenticated
USING (
    private.has_active_membership(
        workspace_id, ARRAY['owner', 'admin']::public.workspace_role[]
    )
);

DROP POLICY IF EXISTS audit_admin_select ON public.workspace_audit_events;
CREATE POLICY audit_admin_select ON public.workspace_audit_events
FOR SELECT TO authenticated
USING (
    private.has_active_membership(
        workspace_id, ARRAY['owner', 'admin']::public.workspace_role[]
    )
);

GRANT USAGE ON SCHEMA private TO authenticated, service_role;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA private FROM PUBLIC, anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION private.has_active_membership(uuid, public.workspace_role[])
    TO authenticated;
GRANT EXECUTE ON FUNCTION private.create_workspace_invitation(
    uuid, text, public.workspace_role, text, timestamptz, uuid
) TO service_role;
GRANT EXECUTE ON FUNCTION private.revoke_workspace_invitation(uuid, uuid, uuid)
    TO service_role;
GRANT EXECUTE ON FUNCTION private.accept_workspace_invitation(text, uuid, text)
    TO service_role;
GRANT EXECUTE ON FUNCTION private.transfer_workspace_ownership(uuid, uuid, uuid)
    TO service_role;
GRANT EXECUTE ON FUNCTION private.archive_workspace(uuid, uuid) TO service_role;
GRANT EXECUTE ON FUNCTION private.claim_workspace_collection(uuid) TO service_role;
GRANT EXECUTE ON FUNCTION private.complete_workspace_collection(uuid, boolean, text)
    TO service_role;
