BEGIN;

DO $$
BEGIN
    CREATE TYPE public.account_role AS ENUM ('owner');
EXCEPTION WHEN duplicate_object THEN
    NULL;
END;
$$;

CREATE TABLE IF NOT EXISTS public.accounts (
    id uuid PRIMARY KEY,
    label text NOT NULL CHECK (char_length(btrim(label)) BETWEEN 1 AND 120),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.account_memberships (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id uuid NOT NULL REFERENCES public.accounts(id) ON DELETE CASCADE,
    user_id uuid NOT NULL,
    role public.account_role NOT NULL DEFAULT 'owner',
    status public.membership_status NOT NULL DEFAULT 'active',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    revoked_at timestamptz,
    CONSTRAINT account_memberships_account_user_key UNIQUE (account_id, user_id),
    CONSTRAINT account_memberships_revoke_state_check CHECK (
        (status = 'active' AND revoked_at IS NULL)
        OR (status = 'revoked' AND revoked_at IS NOT NULL)
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS account_memberships_one_active_owner_idx
    ON public.account_memberships (account_id)
    WHERE role = 'owner' AND status = 'active';

CREATE INDEX IF NOT EXISTS account_memberships_user_active_idx
    ON public.account_memberships (user_id, account_id)
    WHERE status = 'active';

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM public.workspaces AS workspace
        LEFT JOIN public.workspace_memberships AS membership
          ON membership.workspace_id = workspace.id
         AND membership.role = 'owner'
         AND membership.status = 'active'
        GROUP BY workspace.id
        HAVING count(membership.id) <> 1
    ) THEN
        RAISE EXCEPTION 'each workspace requires exactly one active owner'
            USING ERRCODE = '23514';
    END IF;
END;
$$;

CREATE TEMPORARY TABLE group1_account_backfill
ON COMMIT DROP
AS
SELECT DISTINCT
    membership.user_id AS owner_user_id,
    (
        substr(md5('rag-studio:account:v1:' || membership.user_id::text), 1, 8)
        || '-' || substr(md5('rag-studio:account:v1:' || membership.user_id::text), 9, 4)
        || '-4' || substr(md5('rag-studio:account:v1:' || membership.user_id::text), 14, 3)
        || '-8' || substr(md5('rag-studio:account:v1:' || membership.user_id::text), 18, 3)
        || '-' || substr(md5('rag-studio:account:v1:' || membership.user_id::text), 21, 12)
    )::uuid AS account_id
FROM public.workspace_memberships AS membership
WHERE membership.role = 'owner' AND membership.status = 'active';

INSERT INTO public.accounts (id, label)
SELECT
    backfill.account_id,
    'Account ' || upper(substr(md5(backfill.owner_user_id::text), 1, 8))
FROM group1_account_backfill AS backfill
ON CONFLICT (id) DO NOTHING;

INSERT INTO public.account_memberships (account_id, user_id)
SELECT backfill.account_id, backfill.owner_user_id
FROM group1_account_backfill AS backfill
ON CONFLICT (account_id, user_id) DO NOTHING;

ALTER TABLE public.workspaces
    ADD COLUMN IF NOT EXISTS account_id uuid;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM public.workspaces AS workspace
        JOIN public.workspace_memberships AS membership
          ON membership.workspace_id = workspace.id
         AND membership.role = 'owner'
         AND membership.status = 'active'
        JOIN group1_account_backfill AS backfill
          ON backfill.owner_user_id = membership.user_id
        WHERE workspace.account_id IS NOT NULL
          AND workspace.account_id <> backfill.account_id
    ) THEN
        RAISE EXCEPTION 'workspace account ownership is inconsistent'
            USING ERRCODE = '23514';
    END IF;
END;
$$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_catalog.pg_constraint
        WHERE conname = 'workspaces_account_id_fkey'
          AND conrelid = 'public.workspaces'::regclass
    ) THEN
        ALTER TABLE public.workspaces
            ADD CONSTRAINT workspaces_account_id_fkey
            FOREIGN KEY (account_id) REFERENCES public.accounts(id);
    END IF;
END;
$$;

UPDATE public.workspaces AS workspace
SET account_id = backfill.account_id
FROM public.workspace_memberships AS membership
JOIN group1_account_backfill AS backfill
  ON backfill.owner_user_id = membership.user_id
WHERE membership.workspace_id = workspace.id
  AND membership.role = 'owner'
  AND membership.status = 'active'
  AND workspace.account_id IS NULL;

SET CONSTRAINTS ALL IMMEDIATE;

ALTER TABLE public.workspaces
    ALTER COLUMN account_id SET NOT NULL;

CREATE TABLE IF NOT EXISTS private.bff_sessions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL,
    email_ciphertext bytea NOT NULL CHECK (octet_length(email_ciphertext) > 0),
    session_handle_hmac text NOT NULL UNIQUE
        CHECK (session_handle_hmac ~ '^[0-9a-f]{64}$'),
    access_token_ciphertext bytea NOT NULL
        CHECK (octet_length(access_token_ciphertext) > 0),
    refresh_token_ciphertext bytea NOT NULL
        CHECK (octet_length(refresh_token_ciphertext) > 0),
    encryption_key_id text NOT NULL
        CHECK (encryption_key_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'),
    access_token_expires_at timestamptz NOT NULL,
    refresh_token_expires_at timestamptz NOT NULL,
    active_account_id uuid REFERENCES public.accounts(id) ON DELETE SET NULL,
    active_workspace_id uuid REFERENCES public.workspaces(id) ON DELETE SET NULL,
    last_used_at timestamptz NOT NULL DEFAULT now(),
    rotation_version bigint NOT NULL DEFAULT 1 CHECK (rotation_version >= 1),
    rotated_at timestamptz,
    refresh_lease_id uuid,
    refresh_lease_expires_at timestamptz,
    revoked_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT bff_sessions_expiry_order_check CHECK (
        refresh_token_expires_at > access_token_expires_at
    ),
    CONSTRAINT bff_sessions_revocation_time_check CHECK (
        revoked_at IS NULL OR revoked_at >= created_at
    ),
    CONSTRAINT bff_sessions_selection_check CHECK (
        active_workspace_id IS NULL OR active_account_id IS NOT NULL
    ),
    CONSTRAINT bff_sessions_refresh_lease_pair_check CHECK (
        (refresh_lease_id IS NULL AND refresh_lease_expires_at IS NULL)
        OR (refresh_lease_id IS NOT NULL AND refresh_lease_expires_at IS NOT NULL)
    ),
    CONSTRAINT bff_sessions_refresh_lease_expiry_check CHECK (
        refresh_lease_expires_at IS NULL OR refresh_lease_expires_at > created_at
    )
);

CREATE INDEX IF NOT EXISTS bff_sessions_user_active_idx
    ON private.bff_sessions (user_id, refresh_token_expires_at)
    WHERE revoked_at IS NULL;

CREATE INDEX IF NOT EXISTS bff_sessions_refresh_expiry_idx
    ON private.bff_sessions (refresh_token_expires_at)
    WHERE revoked_at IS NULL;

CREATE INDEX IF NOT EXISTS bff_sessions_refresh_lease_expiry_idx
    ON private.bff_sessions (refresh_lease_expires_at)
    WHERE refresh_lease_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS bff_sessions_active_selection_idx
    ON private.bff_sessions (
        user_id, active_account_id, active_workspace_id
    ) WHERE revoked_at IS NULL;

CREATE OR REPLACE FUNCTION private.enforce_single_active_account_owner()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
DECLARE
    target_account_id uuid;
    owner_count integer;
BEGIN
    IF TG_TABLE_NAME = 'accounts' THEN
        target_account_id := COALESCE(NEW.id, OLD.id);
    ELSE
        target_account_id := COALESCE(NEW.account_id, OLD.account_id);
    END IF;
    IF EXISTS (SELECT 1 FROM public.accounts WHERE id = target_account_id) THEN
        SELECT count(*)
          INTO owner_count
          FROM public.account_memberships AS membership
         WHERE membership.account_id = target_account_id
           AND membership.role = 'owner'
           AND membership.status = 'active';
        IF owner_count <> 1 THEN
            RAISE EXCEPTION 'account requires exactly one active owner'
                USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NULL;
END;
$$;

CREATE OR REPLACE FUNCTION private.protect_account_membership_identity()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $$
BEGIN
    IF NEW.account_id <> OLD.account_id
       OR NEW.user_id <> OLD.user_id
       OR NEW.role <> OLD.role THEN
        RAISE EXCEPTION 'account membership identity is immutable'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION private.has_active_account_ownership(
    target_account_id uuid
)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
    SELECT EXISTS (
        SELECT 1
        FROM public.account_memberships AS membership
        WHERE membership.account_id = target_account_id
          AND membership.user_id = (SELECT auth.uid())
          AND membership.role = 'owner'
          AND membership.status = 'active'
    )
$$;

CREATE OR REPLACE FUNCTION private.workspace_account_label(
    target_workspace_id uuid
)
RETURNS TABLE (account_id uuid, account_label text)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
    SELECT account.id, account.label
    FROM public.workspaces AS workspace
    JOIN public.accounts AS account ON account.id = workspace.account_id
    WHERE workspace.id = target_workspace_id
      AND workspace.status = 'active'
      AND EXISTS (
          SELECT 1
          FROM public.workspace_memberships AS membership
          WHERE membership.workspace_id = workspace.id
            AND membership.user_id = (SELECT auth.uid())
            AND membership.status = 'active'
      )
$$;

CREATE OR REPLACE FUNCTION private.validate_bff_session_selection()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
BEGIN
    IF NEW.active_workspace_id IS NOT NULL AND NOT EXISTS (
        SELECT 1
        FROM public.workspaces AS workspace
        WHERE workspace.id = NEW.active_workspace_id
          AND workspace.account_id = NEW.active_account_id
    ) THEN
        RAISE EXCEPTION 'session selection is inconsistent'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS accounts_set_updated_at ON public.accounts;
CREATE TRIGGER accounts_set_updated_at
BEFORE UPDATE ON public.accounts
FOR EACH ROW EXECUTE FUNCTION private.set_updated_at();

DROP TRIGGER IF EXISTS account_memberships_set_updated_at
    ON public.account_memberships;
CREATE TRIGGER account_memberships_set_updated_at
BEFORE UPDATE ON public.account_memberships
FOR EACH ROW EXECUTE FUNCTION private.set_updated_at();

DROP TRIGGER IF EXISTS bff_sessions_set_updated_at ON private.bff_sessions;
CREATE TRIGGER bff_sessions_set_updated_at
BEFORE UPDATE ON private.bff_sessions
FOR EACH ROW EXECUTE FUNCTION private.set_updated_at();

DROP TRIGGER IF EXISTS bff_sessions_validate_selection ON private.bff_sessions;
CREATE TRIGGER bff_sessions_validate_selection
BEFORE INSERT OR UPDATE OF active_account_id, active_workspace_id
ON private.bff_sessions
FOR EACH ROW EXECUTE FUNCTION private.validate_bff_session_selection();

DROP TRIGGER IF EXISTS accounts_require_owner ON public.accounts;
CREATE CONSTRAINT TRIGGER accounts_require_owner
AFTER INSERT OR UPDATE ON public.accounts
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION private.enforce_single_active_account_owner();

DROP TRIGGER IF EXISTS account_memberships_require_owner
    ON public.account_memberships;
CREATE CONSTRAINT TRIGGER account_memberships_require_owner
AFTER INSERT OR UPDATE OR DELETE ON public.account_memberships
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION private.enforce_single_active_account_owner();

DROP TRIGGER IF EXISTS account_memberships_protect_identity
    ON public.account_memberships;
CREATE TRIGGER account_memberships_protect_identity
BEFORE UPDATE ON public.account_memberships
FOR EACH ROW EXECUTE FUNCTION private.protect_account_membership_identity();

ALTER TABLE public.accounts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.account_memberships ENABLE ROW LEVEL SECURITY;
ALTER TABLE private.bff_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.accounts FORCE ROW LEVEL SECURITY;
ALTER TABLE public.account_memberships FORCE ROW LEVEL SECURITY;
ALTER TABLE private.bff_sessions FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS accounts_owner_select ON public.accounts;
CREATE POLICY accounts_owner_select ON public.accounts
FOR SELECT TO authenticated
USING (private.has_active_account_ownership(id));

DROP POLICY IF EXISTS account_memberships_owner_select
    ON public.account_memberships;
CREATE POLICY account_memberships_owner_select ON public.account_memberships
FOR SELECT TO authenticated
USING (private.has_active_account_ownership(account_id));

DROP POLICY IF EXISTS bff_sessions_service_access ON private.bff_sessions;
CREATE POLICY bff_sessions_service_access ON private.bff_sessions
FOR ALL TO service_role
USING (true)
WITH CHECK (true);

CREATE OR REPLACE VIEW public.account_owner_projection
WITH (security_invoker = true)
AS
SELECT id, label, created_at, updated_at
FROM public.accounts;

CREATE OR REPLACE VIEW public.workspace_account_labels
WITH (security_invoker = true)
AS
SELECT
    workspace.id AS workspace_id,
    label.account_id,
    label.account_label
FROM public.workspaces AS workspace
CROSS JOIN LATERAL private.workspace_account_label(workspace.id) AS label;

REVOKE ALL ON TABLE public.accounts
    FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON TABLE public.account_memberships
    FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON TABLE public.account_owner_projection
    FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON TABLE public.workspace_account_labels
    FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON TABLE private.bff_sessions
    FROM PUBLIC, anon, authenticated, service_role;

GRANT SELECT ON TABLE public.accounts TO authenticated;
GRANT SELECT ON TABLE public.account_memberships TO authenticated;
GRANT SELECT ON TABLE public.account_owner_projection TO authenticated;
GRANT SELECT ON TABLE public.workspace_account_labels TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE private.bff_sessions TO service_role;

REVOKE ALL ON FUNCTION private.enforce_single_active_account_owner()
    FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION private.protect_account_membership_identity()
    FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION private.has_active_account_ownership(uuid)
    FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION private.workspace_account_label(uuid)
    FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION private.validate_bff_session_selection()
    FROM PUBLIC, anon, authenticated, service_role;

GRANT EXECUTE ON FUNCTION private.has_active_account_ownership(uuid)
    TO authenticated;
GRANT EXECUTE ON FUNCTION private.workspace_account_label(uuid)
    TO authenticated;

COMMIT;
