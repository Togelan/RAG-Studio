BEGIN;

CREATE TABLE IF NOT EXISTS public.personal_labs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL UNIQUE,
    created_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE public.personal_labs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.personal_labs FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS personal_labs_service_access ON public.personal_labs;
CREATE POLICY personal_labs_service_access ON public.personal_labs
FOR ALL TO service_role
USING (true)
WITH CHECK (true);

REVOKE ALL ON TABLE public.personal_labs
    FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT, INSERT, UPDATE ON TABLE public.personal_labs TO service_role;

COMMIT;
