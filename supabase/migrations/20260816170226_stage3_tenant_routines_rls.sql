CREATE OR REPLACE FUNCTION private.has_active_membership(
    target_workspace_id uuid,
    allowed_roles public.workspace_role[] DEFAULT NULL
)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
    SELECT EXISTS (
        SELECT 1
        FROM public.workspace_memberships AS membership
        JOIN public.workspaces AS workspace
          ON workspace.id = membership.workspace_id
        WHERE membership.workspace_id = target_workspace_id
          AND membership.user_id = (SELECT auth.uid())
          AND membership.status = 'active'
          AND workspace.status = 'active'
          AND (allowed_roles IS NULL OR membership.role = ANY (allowed_roles))
    )
$$;

CREATE OR REPLACE FUNCTION private.actor_has_role(
    target_workspace_id uuid,
    actor_user_id uuid,
    allowed_roles public.workspace_role[]
)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
    SELECT EXISTS (
        SELECT 1
        FROM public.workspace_memberships AS membership
        JOIN public.workspaces AS workspace
          ON workspace.id = membership.workspace_id
        WHERE membership.workspace_id = target_workspace_id
          AND membership.user_id = actor_user_id
          AND membership.status = 'active'
          AND workspace.status = 'active'
          AND membership.role = ANY (allowed_roles)
    )
$$;

CREATE OR REPLACE FUNCTION private.set_updated_at()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION private.seed_workspace_collection()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
BEGIN
    INSERT INTO public.workspace_collection_registry (workspace_id, collection_name)
    VALUES (NEW.id, 'ws_' || md5('rag-studio:workspace:v1:' || NEW.id::text))
    ON CONFLICT (workspace_id) DO NOTHING;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION private.enforce_single_active_owner()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
DECLARE
    target_workspace_id uuid;
    active_workspace boolean;
    owner_count integer;
BEGIN
    IF TG_TABLE_NAME = 'workspaces' THEN
        target_workspace_id := COALESCE(NEW.id, OLD.id);
    ELSE
        target_workspace_id := COALESCE(NEW.workspace_id, OLD.workspace_id);
    END IF;

    SELECT workspace.status = 'active'
      INTO active_workspace
      FROM public.workspaces AS workspace
     WHERE workspace.id = target_workspace_id;

    IF COALESCE(active_workspace, false) THEN
        SELECT count(*)
          INTO owner_count
          FROM public.workspace_memberships AS membership
         WHERE membership.workspace_id = target_workspace_id
           AND membership.role = 'owner'
           AND membership.status = 'active';
        IF owner_count <> 1 THEN
            RAISE EXCEPTION 'active workspace requires exactly one owner'
                USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NULL;
END;
$$;

CREATE OR REPLACE FUNCTION private.protect_membership_identity_and_owner_target()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $$
BEGIN
    IF NEW.workspace_id <> OLD.workspace_id OR NEW.user_id <> OLD.user_id THEN
        RAISE EXCEPTION 'membership identity is immutable' USING ERRCODE = '23514';
    END IF;
    IF NEW.role = 'owner' AND OLD.role <> 'owner' THEN
        IF OLD.role <> 'admin' OR OLD.status <> 'active' OR NEW.status <> 'active' THEN
            RAISE EXCEPTION 'ownership target must be an active admin'
                USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION private.apply_workspace_archive()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
BEGIN
    IF OLD.status = 'active' AND NEW.status = 'archived' THEN
        UPDATE public.workspace_collection_registry
           SET state = 'archived', last_error_code = NULL
         WHERE workspace_id = NEW.id;
        INSERT INTO public.workspace_audit_events (
            workspace_id, actor_user_id, event_type, subject_id
        ) VALUES (NEW.id, NEW.archived_by, 'workspace.archived', NEW.id);
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS workspaces_set_updated_at ON public.workspaces;
CREATE TRIGGER workspaces_set_updated_at
BEFORE UPDATE ON public.workspaces
FOR EACH ROW EXECUTE FUNCTION private.set_updated_at();

DROP TRIGGER IF EXISTS workspace_memberships_set_updated_at ON public.workspace_memberships;
CREATE TRIGGER workspace_memberships_set_updated_at
BEFORE UPDATE ON public.workspace_memberships
FOR EACH ROW EXECUTE FUNCTION private.set_updated_at();

DROP TRIGGER IF EXISTS workspace_collection_registry_set_updated_at
    ON public.workspace_collection_registry;
CREATE TRIGGER workspace_collection_registry_set_updated_at
BEFORE UPDATE ON public.workspace_collection_registry
FOR EACH ROW EXECUTE FUNCTION private.set_updated_at();

DROP TRIGGER IF EXISTS workspaces_seed_collection ON public.workspaces;
CREATE TRIGGER workspaces_seed_collection
AFTER INSERT ON public.workspaces
FOR EACH ROW EXECUTE FUNCTION private.seed_workspace_collection();

DROP TRIGGER IF EXISTS workspace_memberships_protect_identity
    ON public.workspace_memberships;
CREATE TRIGGER workspace_memberships_protect_identity
BEFORE UPDATE ON public.workspace_memberships
FOR EACH ROW EXECUTE FUNCTION private.protect_membership_identity_and_owner_target();

DROP TRIGGER IF EXISTS workspaces_apply_archive ON public.workspaces;
CREATE TRIGGER workspaces_apply_archive
AFTER UPDATE OF status ON public.workspaces
FOR EACH ROW EXECUTE FUNCTION private.apply_workspace_archive();

DROP TRIGGER IF EXISTS workspaces_require_owner ON public.workspaces;
CREATE CONSTRAINT TRIGGER workspaces_require_owner
AFTER INSERT OR UPDATE ON public.workspaces
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION private.enforce_single_active_owner();

DROP TRIGGER IF EXISTS workspace_memberships_require_owner
    ON public.workspace_memberships;
CREATE CONSTRAINT TRIGGER workspace_memberships_require_owner
AFTER INSERT OR UPDATE OR DELETE ON public.workspace_memberships
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION private.enforce_single_active_owner();

CREATE OR REPLACE FUNCTION private.create_workspace_invitation(
    target_workspace_id uuid,
    invited_email text,
    invited_role public.workspace_role,
    supplied_token_hash text,
    invitation_expires_at timestamptz,
    actor_user_id uuid
)
RETURNS uuid
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
DECLARE
    normalized_email text := lower(btrim(invited_email));
    existing_invitation public.workspace_invitations%ROWTYPE;
    invitation_id uuid;
BEGIN
    IF NOT private.actor_has_role(
        target_workspace_id, actor_user_id, ARRAY['owner', 'admin']::public.workspace_role[]
    ) THEN
        RAISE EXCEPTION 'invitation not authorized' USING ERRCODE = '28000';
    END IF;
    IF invited_role = 'owner' OR invitation_expires_at <= now()
       OR supplied_token_hash !~ '^[0-9a-f]{64}$' THEN
        RAISE EXCEPTION 'invalid invitation' USING ERRCODE = '23514';
    END IF;

    SELECT * INTO existing_invitation
      FROM public.workspace_invitations
     WHERE token_hash = supplied_token_hash;
    IF FOUND THEN
        IF existing_invitation.workspace_id = target_workspace_id
           AND existing_invitation.email = normalized_email
           AND existing_invitation.role = invited_role
           AND existing_invitation.expires_at = invitation_expires_at
           AND existing_invitation.created_by = actor_user_id THEN
            RETURN existing_invitation.id;
        END IF;
        RAISE EXCEPTION 'invitation token collision' USING ERRCODE = '23505';
    END IF;

    INSERT INTO public.workspace_invitations (
        workspace_id, email, role, token_hash, expires_at, created_by
    ) VALUES (
        target_workspace_id, normalized_email, invited_role, supplied_token_hash,
        invitation_expires_at, actor_user_id
    ) RETURNING id INTO invitation_id;
    INSERT INTO public.workspace_audit_events (
        workspace_id, actor_user_id, event_type, subject_id
    ) VALUES (target_workspace_id, actor_user_id, 'invitation.created', invitation_id);
    RETURN invitation_id;
END;
$$;

CREATE OR REPLACE FUNCTION private.revoke_workspace_invitation(
    target_invitation_id uuid,
    target_workspace_id uuid,
    actor_user_id uuid
)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
DECLARE
    invitation public.workspace_invitations%ROWTYPE;
BEGIN
    IF NOT private.actor_has_role(
        target_workspace_id, actor_user_id, ARRAY['owner', 'admin']::public.workspace_role[]
    ) THEN
        RAISE EXCEPTION 'invitation revocation not authorized' USING ERRCODE = '28000';
    END IF;
    SELECT * INTO invitation
      FROM public.workspace_invitations
     WHERE id = target_invitation_id AND workspace_id = target_workspace_id
     FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'invitation unavailable' USING ERRCODE = '28000';
    END IF;
    IF invitation.status = 'revoked' AND invitation.revoked_by = actor_user_id THEN
        RETURN;
    END IF;
    IF invitation.status <> 'pending' THEN
        RAISE EXCEPTION 'invitation unavailable' USING ERRCODE = '28000';
    END IF;
    UPDATE public.workspace_invitations
       SET status = 'revoked', revoked_at = now(), revoked_by = actor_user_id
     WHERE id = target_invitation_id;
    INSERT INTO public.workspace_audit_events (
        workspace_id, actor_user_id, event_type, subject_id
    ) VALUES (target_workspace_id, actor_user_id, 'invitation.revoked', target_invitation_id);
END;
$$;

CREATE OR REPLACE FUNCTION private.accept_workspace_invitation(
    supplied_token_hash text,
    accepting_user_id uuid,
    accepting_email text
)
RETURNS uuid
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
DECLARE
    invitation public.workspace_invitations%ROWTYPE;
    membership public.workspace_memberships%ROWTYPE;
    membership_id uuid;
BEGIN
    SELECT * INTO invitation
      FROM public.workspace_invitations
     WHERE token_hash = supplied_token_hash
     FOR UPDATE;
    IF NOT FOUND OR invitation.email <> lower(btrim(accepting_email)) THEN
        RAISE EXCEPTION 'invitation unavailable' USING ERRCODE = '28000';
    END IF;
    IF invitation.status = 'accepted' THEN
        IF invitation.accepted_by <> accepting_user_id THEN
            RAISE EXCEPTION 'invitation unavailable' USING ERRCODE = '28000';
        END IF;
        SELECT id INTO membership_id
          FROM public.workspace_memberships
         WHERE workspace_id = invitation.workspace_id AND user_id = accepting_user_id;
        RETURN membership_id;
    END IF;
    IF invitation.status <> 'pending' OR invitation.expires_at <= now()
       OR NOT EXISTS (
           SELECT 1 FROM public.workspaces
            WHERE id = invitation.workspace_id AND status = 'active'
       ) THEN
        RAISE EXCEPTION 'invitation unavailable' USING ERRCODE = '28000';
    END IF;

    SELECT * INTO membership
      FROM public.workspace_memberships
     WHERE workspace_id = invitation.workspace_id AND user_id = accepting_user_id
     FOR UPDATE;
    IF FOUND THEN
        IF membership.status <> 'active' OR membership.role <> invitation.role THEN
            RAISE EXCEPTION 'membership conflict' USING ERRCODE = '23505';
        END IF;
        membership_id := membership.id;
    ELSE
        INSERT INTO public.workspace_memberships (workspace_id, user_id, role)
        VALUES (invitation.workspace_id, accepting_user_id, invitation.role)
        RETURNING id INTO membership_id;
    END IF;
    UPDATE public.workspace_invitations
       SET status = 'accepted', accepted_at = now(), accepted_by = accepting_user_id
     WHERE id = invitation.id;
    INSERT INTO public.workspace_audit_events (
        workspace_id, actor_user_id, event_type, subject_id
    ) VALUES (
        invitation.workspace_id, accepting_user_id, 'invitation.accepted', invitation.id
    );
    RETURN membership_id;
END;
$$;

CREATE OR REPLACE FUNCTION private.transfer_workspace_ownership(
    target_workspace_id uuid,
    current_owner_user_id uuid,
    target_admin_user_id uuid
)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
BEGIN
    PERFORM 1 FROM public.workspaces
     WHERE id = target_workspace_id AND status = 'active' FOR UPDATE;
    IF NOT FOUND OR NOT private.actor_has_role(
        target_workspace_id, current_owner_user_id, ARRAY['owner']::public.workspace_role[]
    ) OR NOT private.actor_has_role(
        target_workspace_id, target_admin_user_id, ARRAY['admin']::public.workspace_role[]
    ) THEN
        RAISE EXCEPTION 'ownership transfer not authorized' USING ERRCODE = '23514';
    END IF;
    UPDATE public.workspace_memberships
       SET role = 'admin'
     WHERE workspace_id = target_workspace_id AND user_id = current_owner_user_id;
    UPDATE public.workspace_memberships
       SET role = 'owner'
     WHERE workspace_id = target_workspace_id AND user_id = target_admin_user_id;
    INSERT INTO public.workspace_audit_events (
        workspace_id, actor_user_id, event_type, subject_id,
        details
    ) VALUES (
        target_workspace_id, current_owner_user_id, 'ownership.transferred',
        target_admin_user_id, jsonb_build_object('previous_owner_id', current_owner_user_id)
    );
END;
$$;

CREATE OR REPLACE FUNCTION private.archive_workspace(
    target_workspace_id uuid,
    actor_user_id uuid
)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
DECLARE
    workspace public.workspaces%ROWTYPE;
BEGIN
    SELECT * INTO workspace FROM public.workspaces
     WHERE id = target_workspace_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'workspace unavailable' USING ERRCODE = '28000';
    END IF;
    IF workspace.status = 'archived' AND workspace.archived_by = actor_user_id THEN
        RETURN;
    END IF;
    IF NOT private.actor_has_role(
        target_workspace_id, actor_user_id, ARRAY['owner']::public.workspace_role[]
    ) THEN
        RAISE EXCEPTION 'workspace archive not authorized' USING ERRCODE = '28000';
    END IF;
    UPDATE public.workspaces
       SET status = 'archived', archived_at = now(), archived_by = actor_user_id
     WHERE id = target_workspace_id;
END;
$$;

CREATE OR REPLACE FUNCTION private.claim_workspace_collection(target_workspace_id uuid)
RETURNS text
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
DECLARE
    registry public.workspace_collection_registry%ROWTYPE;
BEGIN
    SELECT collection.* INTO registry
      FROM public.workspace_collection_registry AS collection
      JOIN public.workspaces AS workspace ON workspace.id = collection.workspace_id
     WHERE collection.workspace_id = target_workspace_id AND workspace.status = 'active'
     FOR UPDATE OF collection;
    IF NOT FOUND OR registry.state = 'archived' THEN
        RAISE EXCEPTION 'collection unavailable' USING ERRCODE = '28000';
    END IF;
    IF registry.state <> 'ready' THEN
        UPDATE public.workspace_collection_registry
           SET state = 'provisioning', attempt_count = attempt_count + 1,
               last_error_code = NULL
         WHERE workspace_id = target_workspace_id;
    END IF;
    RETURN registry.collection_name;
END;
$$;

CREATE OR REPLACE FUNCTION private.complete_workspace_collection(
    target_workspace_id uuid,
    succeeded boolean,
    sanitized_error_code text
)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
BEGIN
    IF succeeded AND sanitized_error_code IS NOT NULL THEN
        RAISE EXCEPTION 'successful provisioning cannot include an error code'
            USING ERRCODE = '23514';
    END IF;
    IF NOT succeeded AND (
        sanitized_error_code IS NULL OR sanitized_error_code !~ '^[a-z0-9_]{1,64}$'
    ) THEN
        RAISE EXCEPTION 'failed provisioning requires a sanitized error code'
            USING ERRCODE = '23514';
    END IF;
    UPDATE public.workspace_collection_registry
       SET state = CASE
               WHEN succeeded THEN 'ready'::public.collection_provisioning_state
               ELSE 'failed'::public.collection_provisioning_state
           END,
           last_error_code = CASE WHEN succeeded THEN NULL ELSE sanitized_error_code END
     WHERE workspace_id = target_workspace_id AND state = 'provisioning';
    IF NOT FOUND THEN
        RAISE EXCEPTION 'collection provisioning state conflict' USING ERRCODE = '55000';
    END IF;
END;
$$;
