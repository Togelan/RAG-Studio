BEGIN;

CREATE TABLE IF NOT EXISTS public.personal_lab_billing_projections (
    personal_lab_id uuid PRIMARY KEY
        REFERENCES public.personal_labs(id) ON DELETE RESTRICT,
    stripe_customer_id text UNIQUE CHECK (
        stripe_customer_id IS NULL
        OR stripe_customer_id ~ '^cus_[A-Za-z0-9]{8,}$'
    ),
    stripe_subscription_id text UNIQUE CHECK (
        stripe_subscription_id IS NULL
        OR stripe_subscription_id ~ '^sub_[A-Za-z0-9]{8,}$'
    ),
    subscription_status text NOT NULL DEFAULT 'none'
        CHECK (subscription_status IN (
            'none', 'incomplete', 'active', 'past_due', 'canceled', 'unpaid'
        )),
    entitled boolean NOT NULL DEFAULT false,
    current_period_end timestamptz,
    last_event_created_at timestamptz,
    last_stripe_event_id text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT personal_lab_billing_entitlement_state_check CHECK (
        NOT entitled OR subscription_status = 'active'
    )
);
CREATE TABLE IF NOT EXISTS public.stripe_event_ledger (
    stripe_event_id text PRIMARY KEY
        CHECK (stripe_event_id ~ '^evt_[A-Za-z0-9]{8,}$'),
    personal_lab_id uuid NOT NULL
        REFERENCES public.personal_labs(id) ON DELETE RESTRICT,
    event_type text NOT NULL
        CHECK (event_type ~ '^[a-z][a-z0-9_.]{2,119}$'),
    stripe_created_at timestamptz NOT NULL,
    outcome text NOT NULL
        CHECK (outcome IN ('applied', 'stale', 'ignored')),
    recorded_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS stripe_event_ledger_personal_lab_time_idx
    ON public.stripe_event_ledger (
        personal_lab_id, stripe_created_at DESC, stripe_event_id
    );
CREATE TABLE IF NOT EXISTS public.personal_lab_widget_publications (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    personal_lab_id uuid NOT NULL UNIQUE
        REFERENCES public.personal_labs(id) ON DELETE RESTRICT,
    public_key uuid NOT NULL UNIQUE DEFAULT gen_random_uuid(),
    allowed_origin text NOT NULL,
    state text NOT NULL DEFAULT 'enabled'
        CHECK (state IN ('enabled', 'disabled', 'revoked')),
    key_version integer NOT NULL DEFAULT 1 CHECK (key_version >= 1),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    disabled_at timestamptz,
    rotated_at timestamptz,
    revoked_at timestamptz,
    CONSTRAINT personal_lab_widget_exact_origin_check CHECK (
        allowed_origin = lower(allowed_origin)
        AND allowed_origin !~ '[*?#[:space:]]'
        AND allowed_origin ~ '^https?://[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?(?::[1-9][0-9]{0,4})?$'
    ),
    CONSTRAINT personal_lab_widget_state_timestamps_check CHECK (
        (state = 'enabled' AND disabled_at IS NULL AND revoked_at IS NULL) OR
        (state = 'disabled' AND disabled_at IS NOT NULL AND revoked_at IS NULL) OR
        (state = 'revoked' AND revoked_at IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS personal_lab_widget_publications_state_idx
    ON public.personal_lab_widget_publications (state, public_key);

CREATE TABLE IF NOT EXISTS public.personal_lab_widget_publication_audit (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    publication_id uuid NOT NULL
        REFERENCES public.personal_lab_widget_publications(id) ON DELETE RESTRICT,
    event_type text NOT NULL
        CHECK (event_type IN ('published', 'enabled', 'disabled', 'key_rotated', 'revoked')),
    key_version integer NOT NULL CHECK (key_version >= 1),
    previous_public_key uuid,
    current_public_key uuid NOT NULL,
    recorded_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS personal_lab_widget_publication_audit_subject_idx ON
    public.personal_lab_widget_publication_audit (publication_id, recorded_at, id);

CREATE TABLE IF NOT EXISTS public.personal_lab_widget_monthly_quotas (
    publication_id uuid NOT NULL
        REFERENCES public.personal_lab_widget_publications(id) ON DELETE RESTRICT,
    month_start date NOT NULL,
    reserved_count integer NOT NULL DEFAULT 0 CHECK (reserved_count >= 0),
    committed_count integer NOT NULL DEFAULT 0 CHECK (committed_count >= 0),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (publication_id, month_start),
    CONSTRAINT personal_lab_widget_month_boundary_check CHECK (
        month_start = date_trunc('month', month_start)::date
    ),
    CONSTRAINT personal_lab_widget_monthly_cap_check CHECK (
        reserved_count + committed_count <= 500
    )
);
CREATE TABLE IF NOT EXISTS public.personal_lab_widget_quota_reservations (
    reservation_id uuid PRIMARY KEY,
    publication_id uuid NOT NULL,
    month_start date NOT NULL,
    state text NOT NULL DEFAULT 'reserved'
        CHECK (state IN ('reserved', 'committed', 'released')),
    created_at timestamptz NOT NULL DEFAULT now(),
    finalized_at timestamptz,
    FOREIGN KEY (publication_id, month_start) REFERENCES
        public.personal_lab_widget_monthly_quotas (publication_id, month_start)
        ON DELETE RESTRICT,
    CONSTRAINT personal_lab_widget_reservation_state_check CHECK (
        (state = 'reserved' AND finalized_at IS NULL)
        OR (state <> 'reserved' AND finalized_at IS NOT NULL)
    )
);
CREATE INDEX IF NOT EXISTS personal_lab_widget_reservations_subject_idx ON
    public.personal_lab_widget_quota_reservations (
        publication_id, month_start, state);
CREATE OR REPLACE FUNCTION private.prevent_mvp_audit_mutation()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, private
AS $$
BEGIN
    RAISE EXCEPTION 'retained MVP audit records are immutable'
        USING ERRCODE = '55000';
END;
$$;
DROP TRIGGER IF EXISTS stripe_event_ledger_immutable
    ON public.stripe_event_ledger;
CREATE TRIGGER stripe_event_ledger_immutable
BEFORE UPDATE OR DELETE ON public.stripe_event_ledger
FOR EACH ROW EXECUTE FUNCTION private.prevent_mvp_audit_mutation();
DROP TRIGGER IF EXISTS personal_lab_widget_publication_audit_immutable
    ON public.personal_lab_widget_publication_audit;
CREATE TRIGGER personal_lab_widget_publication_audit_immutable
BEFORE UPDATE OR DELETE ON public.personal_lab_widget_publication_audit
FOR EACH ROW EXECUTE FUNCTION private.prevent_mvp_audit_mutation();
DROP TRIGGER IF EXISTS personal_lab_widget_publication_no_delete
    ON public.personal_lab_widget_publications;
CREATE TRIGGER personal_lab_widget_publication_no_delete
BEFORE DELETE ON public.personal_lab_widget_publications
FOR EACH ROW EXECUTE FUNCTION private.prevent_mvp_audit_mutation();
CREATE OR REPLACE FUNCTION private.apply_personal_lab_billing_event(
    p_personal_lab_id uuid,
    p_stripe_event_id text,
    p_event_type text,
    p_stripe_customer_id text,
    p_stripe_subscription_id text,
    p_subscription_status text,
    p_entitled boolean,
    p_stripe_created_at timestamptz,
    p_current_period_end timestamptz DEFAULT NULL
)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, private
AS $$
DECLARE
    v_recorded boolean;
    v_outcome text;
BEGIN
    PERFORM pg_advisory_xact_lock(
        hashtextextended(p_personal_lab_id::text, 0)
    );
    SELECT NOT EXISTS (
        SELECT 1 FROM public.personal_lab_billing_projections
        WHERE personal_lab_id = p_personal_lab_id
          AND (last_event_created_at, COALESCE(last_stripe_event_id, ''))
              >= (p_stripe_created_at, p_stripe_event_id)
    ) INTO v_recorded;
    v_outcome := CASE WHEN v_recorded THEN 'applied' ELSE 'stale' END;

    INSERT INTO public.stripe_event_ledger (
        stripe_event_id, personal_lab_id, event_type, stripe_created_at, outcome
    ) VALUES (
        p_stripe_event_id, p_personal_lab_id, p_event_type,
        p_stripe_created_at, v_outcome
    ) ON CONFLICT (stripe_event_id) DO NOTHING;
    IF NOT FOUND THEN
        RETURN false;
    END IF;

    IF v_recorded THEN
        INSERT INTO public.personal_lab_billing_projections (
            personal_lab_id, stripe_customer_id, stripe_subscription_id,
            subscription_status, entitled, current_period_end,
            last_event_created_at, last_stripe_event_id) VALUES (
            p_personal_lab_id, p_stripe_customer_id, p_stripe_subscription_id,
            p_subscription_status, p_entitled, p_current_period_end,
            p_stripe_created_at, p_stripe_event_id
        )
        ON CONFLICT (personal_lab_id) DO UPDATE SET
            stripe_customer_id = EXCLUDED.stripe_customer_id,
            stripe_subscription_id = EXCLUDED.stripe_subscription_id,
            subscription_status = EXCLUDED.subscription_status,
            entitled = EXCLUDED.entitled,
            current_period_end = EXCLUDED.current_period_end,
            last_event_created_at = EXCLUDED.last_event_created_at,
            last_stripe_event_id = EXCLUDED.last_stripe_event_id,
            updated_at = now()
        WHERE public.personal_lab_billing_projections.last_event_created_at IS NULL
           OR (
                public.personal_lab_billing_projections.last_event_created_at,
                COALESCE(
                    public.personal_lab_billing_projections.last_stripe_event_id,
                    ''
                )
              ) < (
                EXCLUDED.last_event_created_at,
                EXCLUDED.last_stripe_event_id
              );
    END IF;
    RETURN true;
END;
$$;
CREATE OR REPLACE FUNCTION private.publish_personal_lab_widget(
    p_personal_lab_id uuid,
    p_allowed_origin text,
    p_public_key uuid DEFAULT gen_random_uuid()
)
RETURNS uuid
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, private
AS $$
DECLARE
    v_publication_id uuid;
BEGIN
    INSERT INTO public.personal_lab_widget_publications (
        personal_lab_id, allowed_origin, public_key) VALUES (
        p_personal_lab_id, p_allowed_origin, p_public_key
    ) RETURNING id INTO v_publication_id;

    INSERT INTO public.personal_lab_widget_publication_audit (
        publication_id, event_type, key_version, current_public_key)
    VALUES (v_publication_id, 'published', 1, p_public_key);
    RETURN v_publication_id;
END;
$$;
CREATE OR REPLACE FUNCTION private.set_personal_lab_widget_state(
    p_publication_id uuid,
    p_state text
)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, private
AS $$
DECLARE
    v_publication public.personal_lab_widget_publications%ROWTYPE;
BEGIN
    IF p_state NOT IN ('enabled', 'disabled', 'revoked') THEN
        RAISE EXCEPTION 'invalid publication state' USING ERRCODE = '22023';
    END IF;
    UPDATE public.personal_lab_widget_publications
    SET state = p_state,
        disabled_at = CASE WHEN p_state = 'disabled' THEN now() ELSE NULL END,
        revoked_at = CASE WHEN p_state = 'revoked' THEN now() ELSE NULL END,
        updated_at = now()
    WHERE id = p_publication_id AND state <> 'revoked'
    RETURNING * INTO v_publication;
    IF NOT FOUND THEN
        RETURN false;
    END IF;
    INSERT INTO public.personal_lab_widget_publication_audit (
        publication_id, event_type, key_version, current_public_key) VALUES (
        v_publication.id, p_state, v_publication.key_version,
        v_publication.public_key
    );
    RETURN true;
END;
$$;
CREATE OR REPLACE FUNCTION private.rotate_personal_lab_widget_key(
    p_publication_id uuid,
    p_public_key uuid DEFAULT gen_random_uuid()
)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, private
AS $$
DECLARE
    v_previous_key uuid;
    v_key_version integer;
BEGIN
    UPDATE public.personal_lab_widget_publications
    SET public_key = p_public_key,
        key_version = key_version + 1,
        rotated_at = now(),
        updated_at = now()
    WHERE id = p_publication_id AND state <> 'revoked'
    RETURNING public_key, key_version
    INTO v_previous_key, v_key_version;
    IF NOT FOUND THEN
        RETURN false;
    END IF;
    SELECT current_public_key
    INTO v_previous_key
    FROM public.personal_lab_widget_publication_audit
    WHERE publication_id = p_publication_id
    ORDER BY id DESC
    LIMIT 1;
    INSERT INTO public.personal_lab_widget_publication_audit (
        publication_id, event_type, key_version,
        previous_public_key, current_public_key) VALUES (
        p_publication_id, 'key_rotated', v_key_version,
        v_previous_key, p_public_key
    );
    RETURN true;
END;
$$;
CREATE OR REPLACE FUNCTION private.reserve_personal_lab_widget_message(
    p_publication_id uuid,
    p_reservation_id uuid
)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, private
AS $$
DECLARE
    v_month_start date :=
        date_trunc('month', CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::date;
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM public.personal_lab_widget_publications
        WHERE id = p_publication_id AND state = 'enabled'
    ) THEN
        RETURN false;
    END IF;
    INSERT INTO public.personal_lab_widget_monthly_quotas (
        publication_id, month_start) VALUES (p_publication_id, v_month_start)
    ON CONFLICT (publication_id, month_start) DO NOTHING;

    INSERT INTO public.personal_lab_widget_quota_reservations (
        reservation_id, publication_id, month_start)
    VALUES (p_reservation_id, p_publication_id, v_month_start)
    ON CONFLICT (reservation_id) DO NOTHING;
    IF NOT FOUND THEN
        RETURN EXISTS (
            SELECT 1 FROM public.personal_lab_widget_quota_reservations
            WHERE reservation_id = p_reservation_id
              AND publication_id = p_publication_id
              AND state = 'reserved'
        );
    END IF;

    UPDATE public.personal_lab_widget_monthly_quotas
    SET reserved_count = reserved_count + 1,
        updated_at = now()
    WHERE publication_id = p_publication_id
      AND month_start = v_month_start
      AND reserved_count + committed_count < 500;
    IF FOUND THEN
        RETURN true;
    END IF;
    UPDATE public.personal_lab_widget_quota_reservations
    SET state = 'released', finalized_at = now()
    WHERE reservation_id = p_reservation_id;
    RETURN false;
END;
$$;
CREATE OR REPLACE FUNCTION private.commit_personal_lab_widget_message(
    p_reservation_id uuid
)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, private
AS $$
DECLARE
    v_publication_id uuid;
    v_month_start date;
BEGIN
    UPDATE public.personal_lab_widget_quota_reservations
    SET state = 'committed', finalized_at = now()
    WHERE reservation_id = p_reservation_id AND state = 'reserved'
    RETURNING publication_id, month_start
    INTO v_publication_id, v_month_start;
    IF NOT FOUND THEN
        RETURN false;
    END IF;
    UPDATE public.personal_lab_widget_monthly_quotas
    SET reserved_count = reserved_count - 1,
        committed_count = committed_count + 1,
        updated_at = now()
    WHERE publication_id = v_publication_id AND month_start = v_month_start;
    RETURN true;
END;
$$;
CREATE OR REPLACE FUNCTION private.release_personal_lab_widget_message(
    p_reservation_id uuid
)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, private
AS $$
DECLARE
    v_publication_id uuid;
    v_month_start date;
BEGIN
    UPDATE public.personal_lab_widget_quota_reservations
    SET state = 'released', finalized_at = now()
    WHERE reservation_id = p_reservation_id AND state = 'reserved'
    RETURNING publication_id, month_start
    INTO v_publication_id, v_month_start;
    IF NOT FOUND THEN
        RETURN false;
    END IF;
    UPDATE public.personal_lab_widget_monthly_quotas
    SET reserved_count = reserved_count - 1,
        updated_at = now()
    WHERE publication_id = v_publication_id AND month_start = v_month_start;
    RETURN true;
END;
$$;
ALTER TABLE public.personal_lab_billing_projections ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.personal_lab_billing_projections FORCE ROW LEVEL SECURITY;
ALTER TABLE public.stripe_event_ledger ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.stripe_event_ledger FORCE ROW LEVEL SECURITY;
ALTER TABLE public.personal_lab_widget_publications ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.personal_lab_widget_publications FORCE ROW LEVEL SECURITY;
ALTER TABLE public.personal_lab_widget_publication_audit ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.personal_lab_widget_publication_audit FORCE ROW LEVEL SECURITY;
ALTER TABLE public.personal_lab_widget_monthly_quotas ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.personal_lab_widget_monthly_quotas FORCE ROW LEVEL SECURITY;
ALTER TABLE public.personal_lab_widget_quota_reservations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.personal_lab_widget_quota_reservations FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS personal_lab_billing_service_select ON
    public.personal_lab_billing_projections;
CREATE POLICY personal_lab_billing_service_select ON
    public.personal_lab_billing_projections FOR SELECT TO service_role USING (true);
DROP POLICY IF EXISTS stripe_event_ledger_service_select ON public.stripe_event_ledger;
CREATE POLICY stripe_event_ledger_service_select ON public.stripe_event_ledger
    FOR SELECT TO service_role USING (true);
DROP POLICY IF EXISTS personal_lab_widget_publications_service_select ON
    public.personal_lab_widget_publications;
CREATE POLICY personal_lab_widget_publications_service_select ON
    public.personal_lab_widget_publications FOR SELECT TO service_role USING (true);
DROP POLICY IF EXISTS personal_lab_widget_audit_service_select ON
    public.personal_lab_widget_publication_audit;
CREATE POLICY personal_lab_widget_audit_service_select ON
    public.personal_lab_widget_publication_audit FOR SELECT TO service_role USING (true);
DROP POLICY IF EXISTS personal_lab_widget_quotas_service_select ON
    public.personal_lab_widget_monthly_quotas;
CREATE POLICY personal_lab_widget_quotas_service_select ON
    public.personal_lab_widget_monthly_quotas FOR SELECT TO service_role USING (true);
DROP POLICY IF EXISTS personal_lab_widget_reservations_service_select ON
    public.personal_lab_widget_quota_reservations;
CREATE POLICY personal_lab_widget_reservations_service_select ON
    public.personal_lab_widget_quota_reservations FOR SELECT TO service_role USING (true);

REVOKE ALL ON TABLE public.personal_lab_billing_projections FROM
    PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON TABLE public.stripe_event_ledger FROM
    PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON TABLE public.personal_lab_widget_publications FROM
    PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON TABLE public.personal_lab_widget_publication_audit FROM
    PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON TABLE public.personal_lab_widget_monthly_quotas FROM
    PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON TABLE public.personal_lab_widget_quota_reservations FROM
    PUBLIC, anon, authenticated, service_role;
GRANT SELECT ON TABLE public.personal_lab_billing_projections,
    public.stripe_event_ledger,
    public.personal_lab_widget_publications,
    public.personal_lab_widget_publication_audit,
    public.personal_lab_widget_monthly_quotas,
    public.personal_lab_widget_quota_reservations TO service_role;

REVOKE ALL ON FUNCTION private.prevent_mvp_audit_mutation()
    FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION private.apply_personal_lab_billing_event(
    uuid, text, text, text, text, text, boolean, timestamptz, timestamptz
) FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION private.publish_personal_lab_widget(uuid, text, uuid)
    FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION private.set_personal_lab_widget_state(uuid, text)
    FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION private.rotate_personal_lab_widget_key(uuid, uuid)
    FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION private.reserve_personal_lab_widget_message(uuid, uuid)
    FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION private.commit_personal_lab_widget_message(uuid)
    FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION private.release_personal_lab_widget_message(uuid)
    FROM PUBLIC, anon, authenticated, service_role;

GRANT EXECUTE ON FUNCTION private.apply_personal_lab_billing_event(
    uuid, text, text, text, text, text, boolean, timestamptz, timestamptz
) TO service_role;
GRANT EXECUTE ON FUNCTION private.publish_personal_lab_widget(uuid, text, uuid)
    TO service_role;
GRANT EXECUTE ON FUNCTION private.set_personal_lab_widget_state(uuid, text)
    TO service_role;
GRANT EXECUTE ON FUNCTION private.rotate_personal_lab_widget_key(uuid, uuid)
    TO service_role;
GRANT EXECUTE ON FUNCTION private.reserve_personal_lab_widget_message(uuid, uuid)
    TO service_role;
GRANT EXECUTE ON FUNCTION private.commit_personal_lab_widget_message(uuid)
    TO service_role;
GRANT EXECUTE ON FUNCTION private.release_personal_lab_widget_message(uuid)
    TO service_role;

COMMIT;
