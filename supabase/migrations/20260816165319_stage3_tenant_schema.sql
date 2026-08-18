CREATE SCHEMA IF NOT EXISTS private;

REVOKE ALL ON SCHEMA private FROM PUBLIC;

DO $$
BEGIN
    CREATE TYPE public.workspace_role AS ENUM ('owner', 'admin', 'member');
EXCEPTION WHEN duplicate_object THEN
    NULL;
END;
$$;

DO $$
BEGIN
    CREATE TYPE public.workspace_status AS ENUM ('active', 'archived');
EXCEPTION WHEN duplicate_object THEN
    NULL;
END;
$$;

DO $$
BEGIN
    CREATE TYPE public.membership_status AS ENUM ('active', 'revoked');
EXCEPTION WHEN duplicate_object THEN
    NULL;
END;
$$;

DO $$
BEGIN
    CREATE TYPE public.invitation_status AS ENUM ('pending', 'accepted', 'revoked', 'expired');
EXCEPTION WHEN duplicate_object THEN
    NULL;
END;
$$;

DO $$
BEGIN
    CREATE TYPE public.collection_provisioning_state AS ENUM (
        'pending', 'provisioning', 'ready', 'failed', 'archived'
    );
EXCEPTION WHEN duplicate_object THEN
    NULL;
END;
$$;

CREATE TABLE IF NOT EXISTS public.workspaces (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name text NOT NULL CHECK (char_length(btrim(name)) BETWEEN 1 AND 120),
    status public.workspace_status NOT NULL DEFAULT 'active',
    created_by uuid NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    archived_at timestamptz,
    archived_by uuid,
    CONSTRAINT workspaces_archive_state_check CHECK (
        (status = 'active' AND archived_at IS NULL AND archived_by IS NULL)
        OR (status = 'archived' AND archived_at IS NOT NULL AND archived_by IS NOT NULL)
    )
);

CREATE TABLE IF NOT EXISTS public.workspace_memberships (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id uuid NOT NULL REFERENCES public.workspaces(id) ON DELETE CASCADE,
    user_id uuid NOT NULL,
    role public.workspace_role NOT NULL,
    status public.membership_status NOT NULL DEFAULT 'active',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    revoked_at timestamptz,
    CONSTRAINT workspace_memberships_workspace_user_key UNIQUE (workspace_id, user_id),
    CONSTRAINT workspace_memberships_revoke_state_check CHECK (
        (status = 'active' AND revoked_at IS NULL)
        OR (status = 'revoked' AND revoked_at IS NOT NULL)
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS workspace_memberships_one_active_owner_idx
    ON public.workspace_memberships (workspace_id)
    WHERE role = 'owner' AND status = 'active';

CREATE INDEX IF NOT EXISTS workspace_memberships_user_active_idx
    ON public.workspace_memberships (user_id, workspace_id)
    WHERE status = 'active';

CREATE TABLE IF NOT EXISTS public.workspace_invitations (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id uuid NOT NULL REFERENCES public.workspaces(id) ON DELETE CASCADE,
    email text NOT NULL,
    role public.workspace_role NOT NULL,
    token_hash text NOT NULL UNIQUE,
    status public.invitation_status NOT NULL DEFAULT 'pending',
    expires_at timestamptz NOT NULL,
    created_by uuid NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    accepted_at timestamptz,
    accepted_by uuid,
    revoked_at timestamptz,
    revoked_by uuid,
    CONSTRAINT workspace_invitations_email_normalized_check CHECK (
        email = lower(btrim(email)) AND email LIKE '%@%'
    ),
    CONSTRAINT workspace_invitations_role_check CHECK (role <> 'owner'),
    CONSTRAINT workspace_invitations_token_hash_check CHECK (token_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT workspace_invitations_expiry_check CHECK (expires_at > created_at),
    CONSTRAINT workspace_invitations_state_check CHECK (
        (status = 'pending' AND accepted_at IS NULL AND accepted_by IS NULL
            AND revoked_at IS NULL AND revoked_by IS NULL)
        OR (status = 'accepted' AND accepted_at IS NOT NULL AND accepted_by IS NOT NULL
            AND revoked_at IS NULL AND revoked_by IS NULL)
        OR (status = 'revoked' AND accepted_at IS NULL AND accepted_by IS NULL
            AND revoked_at IS NOT NULL AND revoked_by IS NOT NULL)
        OR (status = 'expired' AND accepted_at IS NULL AND accepted_by IS NULL
            AND revoked_at IS NULL AND revoked_by IS NULL)
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS workspace_invitations_one_pending_email_idx
    ON public.workspace_invitations (workspace_id, email)
    WHERE status = 'pending';

CREATE INDEX IF NOT EXISTS workspace_invitations_token_pending_idx
    ON public.workspace_invitations (token_hash)
    WHERE status = 'pending';

CREATE TABLE IF NOT EXISTS public.workspace_collection_registry (
    workspace_id uuid PRIMARY KEY REFERENCES public.workspaces(id) ON DELETE CASCADE,
    collection_name text NOT NULL UNIQUE,
    state public.collection_provisioning_state NOT NULL DEFAULT 'pending',
    attempt_count integer NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    last_error_code text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT workspace_collection_registry_name_check CHECK (
        collection_name ~ '^ws_[0-9a-f]{32}$'
    ),
    CONSTRAINT workspace_collection_registry_error_check CHECK (
        last_error_code IS NULL OR last_error_code ~ '^[a-z0-9_]{1,64}$'
    ),
    CONSTRAINT workspace_collection_registry_state_check CHECK (
        (state = 'failed' AND last_error_code IS NOT NULL)
        OR (state <> 'failed' AND last_error_code IS NULL)
    )
);

CREATE TABLE IF NOT EXISTS public.workspace_audit_events (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    workspace_id uuid NOT NULL REFERENCES public.workspaces(id) ON DELETE CASCADE,
    actor_user_id uuid,
    event_type text NOT NULL CHECK (event_type ~ '^[a-z][a-z0-9_.]{2,63}$'),
    subject_id uuid,
    details jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(details) = 'object'),
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS workspace_audit_events_workspace_created_idx
    ON public.workspace_audit_events (workspace_id, created_at DESC);

ALTER TABLE public.workspaces ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.workspace_memberships ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.workspace_invitations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.workspace_collection_registry ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.workspace_audit_events ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.workspaces FORCE ROW LEVEL SECURITY;
ALTER TABLE public.workspace_memberships FORCE ROW LEVEL SECURITY;
ALTER TABLE public.workspace_invitations FORCE ROW LEVEL SECURITY;
ALTER TABLE public.workspace_collection_registry FORCE ROW LEVEL SECURITY;
ALTER TABLE public.workspace_audit_events FORCE ROW LEVEL SECURITY;

REVOKE ALL ON TABLE public.workspaces FROM anon, authenticated, service_role;
REVOKE ALL ON TABLE public.workspace_memberships FROM anon, authenticated, service_role;
REVOKE ALL ON TABLE public.workspace_invitations FROM anon, authenticated, service_role;
REVOKE ALL ON TABLE public.workspace_collection_registry FROM anon, authenticated, service_role;
REVOKE ALL ON TABLE public.workspace_audit_events FROM anon, authenticated, service_role;

GRANT USAGE ON SCHEMA public TO authenticated;
GRANT SELECT ON TABLE public.workspaces TO authenticated;
GRANT SELECT ON TABLE public.workspace_memberships TO authenticated;
GRANT SELECT ON TABLE public.workspace_invitations TO authenticated;
GRANT SELECT ON TABLE public.workspace_audit_events TO authenticated;
