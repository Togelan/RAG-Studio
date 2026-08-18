DO $$
BEGIN
    CREATE TYPE public.chatbot_status AS ENUM ('enabled', 'disabled', 'archived');
EXCEPTION WHEN duplicate_object THEN
    NULL;
END;
$$;

CREATE TABLE IF NOT EXISTS public.workspace_chatbots (
    id uuid PRIMARY KEY,
    workspace_id uuid NOT NULL REFERENCES public.workspaces(id) ON DELETE CASCADE,
    idempotency_key_hash text NOT NULL,
    name_en text NOT NULL CHECK (char_length(btrim(name_en)) BETWEEN 1 AND 120),
    name_ru text NOT NULL CHECK (char_length(btrim(name_ru)) BETWEEN 1 AND 120),
    instructions_en text NOT NULL DEFAULT ''
        CHECK (char_length(instructions_en) <= 8000),
    instructions_ru text NOT NULL DEFAULT ''
        CHECK (char_length(instructions_ru) <= 8000),
    provider text NOT NULL
        CHECK (provider ~ '^[a-z][a-z0-9_-]{0,39}$'),
    model_name text NOT NULL
        CHECK (
            char_length(model_name) BETWEEN 1 AND 120
            AND model_name ~ '^[A-Za-z0-9][A-Za-z0-9._:/-]*$'
        ),
    source_scope text NOT NULL DEFAULT 'workspace_all'
        CHECK (source_scope = 'workspace_all'),
    status public.chatbot_status NOT NULL DEFAULT 'enabled',
    version integer NOT NULL DEFAULT 1 CHECK (version >= 1),
    created_by uuid NOT NULL,
    updated_by uuid NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    archived_at timestamptz,
    archived_by uuid,
    CONSTRAINT workspace_chatbots_idempotency_hash_check CHECK (
        idempotency_key_hash ~ '^[0-9a-f]{64}$'
    ),
    CONSTRAINT workspace_chatbots_archive_state_check CHECK (
        (status = 'archived' AND archived_at IS NOT NULL AND archived_by IS NOT NULL)
        OR (status <> 'archived' AND archived_at IS NULL AND archived_by IS NULL)
    ),
    CONSTRAINT workspace_chatbots_workspace_idempotency_key
        UNIQUE (workspace_id, idempotency_key_hash)
);

CREATE INDEX IF NOT EXISTS workspace_chatbots_workspace_status_idx
    ON public.workspace_chatbots (workspace_id, status, created_at, id);

DROP TRIGGER IF EXISTS workspace_chatbots_set_updated_at
    ON public.workspace_chatbots;
CREATE TRIGGER workspace_chatbots_set_updated_at
BEFORE UPDATE ON public.workspace_chatbots
FOR EACH ROW EXECUTE FUNCTION private.set_updated_at();

ALTER TABLE public.workspace_chatbots ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.workspace_chatbots FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS workspace_chatbots_active_member_select
    ON public.workspace_chatbots;
CREATE POLICY workspace_chatbots_active_member_select
ON public.workspace_chatbots
FOR SELECT TO authenticated
USING (private.has_active_membership(workspace_id));

REVOKE ALL ON TABLE public.workspace_chatbots
    FROM anon, authenticated, service_role;
GRANT SELECT ON TABLE public.workspace_chatbots TO authenticated;
