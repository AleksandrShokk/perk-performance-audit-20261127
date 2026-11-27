--
-- PostgreSQL database dump
--

\restrict N70bUuB0T8aRg79WKgjd27WcE2hK0mZ2mWLZhvzgyvcp6khABIlSygcXHMbsIHS

-- Dumped from database version 17.11
-- Dumped by pg_dump version 17.11

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: perk_accept_invite(text); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.perk_accept_invite(digest text) RETURNS uuid
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'public', 'pg_temp'
    AS $$
DECLARE invite workspace_invites%ROWTYPE; actor uuid := perk_actor(); address text;
BEGIN
 IF actor IS NULL THEN RETURN NULL; END IF;
 SELECT email INTO address FROM users WHERE id=actor AND is_active
 AND email_verified_at IS NOT NULL AND phone IS NOT NULL AND phone_verified_at IS NOT NULL;
 IF address IS NULL THEN RETURN NULL; END IF;
 SELECT * INTO invite FROM workspace_invites WHERE token_digest=digest
 AND accepted_at IS NULL AND expires_at>now() FOR UPDATE;
 IF NOT FOUND OR invite.email<>address THEN RETURN NULL; END IF;
 IF NOT EXISTS (SELECT 1 FROM memberships WHERE workspace_id=invite.workspace_id
 AND user_id=invite.invited_by AND role IN ('owner','admin')) THEN RETURN NULL; END IF;
 -- Accepting an old invite must never overwrite an existing member's rights.
 INSERT INTO memberships(user_id,workspace_id,role,permissions,store_ids)
 VALUES(actor,invite.workspace_id,invite.role,invite.permissions,invite.store_ids)
 ON CONFLICT(user_id,workspace_id) DO NOTHING;
 UPDATE workspace_invites SET accepted_at=now(),accepted_by=actor WHERE id=invite.id;
 RETURN invite.workspace_id;
END $$;


--
-- Name: perk_actor(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.perk_actor() RETURNS uuid
    LANGUAGE sql STABLE
    AS $$
  SELECT NULLIF(current_setting('perk.user_id', true), '')::uuid
$$;


--
-- Name: perk_cleanup_expired(integer); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.perk_cleanup_expired(batch integer DEFAULT 5000) RETURNS integer
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'public', 'pg_temp'
    AS $$
DECLARE removed integer := 0; n integer; size integer := LEAST(GREATEST(batch, 1), 20000);
BEGIN
  DELETE FROM otp_challenges WHERE ctid IN (SELECT ctid FROM otp_challenges
    WHERE expires_at < now() - interval '1 day' LIMIT size);
  GET DIAGNOSTICS n = ROW_COUNT; removed := removed + n;
  DELETE FROM access_tokens WHERE ctid IN (SELECT ctid FROM access_tokens
    WHERE expires_at < now() - interval '1 day' LIMIT size);
  GET DIAGNOSTICS n = ROW_COUNT; removed := removed + n;
  -- Refresh tokens stay with their session for replay detection, then cascade.
  DELETE FROM auth_sessions WHERE ctid IN (SELECT ctid FROM auth_sessions
    WHERE expires_at < now() - interval '30 days' LIMIT size);
  GET DIAGNOSTICS n = ROW_COUNT; removed := removed + n;
  DELETE FROM auth_sessions WHERE ctid IN (SELECT ctid FROM auth_sessions
    WHERE revoked_at < now() - interval '30 days' LIMIT size);
  GET DIAGNOSTICS n = ROW_COUNT; removed := removed + n;
  DELETE FROM cost_imports WHERE ctid IN (SELECT ctid FROM cost_imports
    WHERE expires_at < now() - interval '1 day' LIMIT size);
  GET DIAGNOSTICS n = ROW_COUNT; removed := removed + n;
  DELETE FROM notifications WHERE ctid IN (SELECT ctid FROM notifications
    WHERE created_at < now() - interval '90 days' LIMIT size);
  GET DIAGNOSTICS n = ROW_COUNT; removed := removed + n;
  DELETE FROM insight_snapshots WHERE ctid IN (SELECT ctid FROM insight_snapshots
    WHERE computed_at < now() - interval '30 days' LIMIT size);
  GET DIAGNOSTICS n = ROW_COUNT; removed := removed + n;
  DELETE FROM inventory_snapshots WHERE ctid IN (SELECT ctid FROM inventory_snapshots
    WHERE day < current_date - 800 LIMIT size);
  GET DIAGNOSTICS n = ROW_COUNT; removed := removed + n;
  
    DELETE FROM import_issues WHERE ctid IN (SELECT ctid FROM import_issues
      WHERE created_at<now()-interval '90 days' LIMIT size);
    GET DIAGNOSTICS n=ROW_COUNT; removed:=removed+n;
    DELETE FROM wb_staged_records WHERE ctid IN (SELECT s.ctid FROM wb_staged_records s
      JOIN sync_runs r ON r.id=s.run_id WHERE r.status IN ('succeeded','failed')
      AND r.finished_at<now()-interval '7 days' LIMIT size);
    GET DIAGNOSTICS n=ROW_COUNT; removed:=removed+n;
    DELETE FROM sync_runs WHERE ctid IN (SELECT r.ctid FROM sync_runs r
      WHERE status='failed' AND finished_at<now()-interval '90 days'
      AND NOT EXISTS(SELECT 1 FROM wb_daily_metrics m WHERE m.dataset=r.id::text) LIMIT size);
    GET DIAGNOSTICS n=ROW_COUNT; removed:=removed+n;
     RETURN removed;
END $$;


--
-- Name: perk_created_workspace(uuid); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.perk_created_workspace(ws uuid) RETURNS boolean
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path TO 'public', 'pg_temp'
    AS $$
  SELECT EXISTS (SELECT 1 FROM workspaces WHERE id = ws AND owner_user_id = perk_actor())
$$;


--
-- Name: perk_invite_details(text); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.perk_invite_details(digest text) RETURNS jsonb
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path TO 'public', 'pg_temp'
    AS $$
 SELECT jsonb_build_object('email',i.email,'role',i.role,'workspace_name',w.name,
 'permissions',i.permissions,'store_ids',i.store_ids,'expires_at',i.expires_at)
 FROM workspace_invites i JOIN workspaces w ON w.id=i.workspace_id
 WHERE i.token_digest=digest AND i.accepted_at IS NULL AND i.expires_at>now()
 AND EXISTS (SELECT 1 FROM memberships m WHERE m.workspace_id=i.workspace_id
 AND m.user_id=i.invited_by AND m.role IN ('owner','admin'))
$$;


--
-- Name: perk_is_creator(uuid, uuid); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.perk_is_creator(ws uuid, subject uuid) RETURNS boolean
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path TO 'public', 'pg_temp'
    AS $$
  SELECT EXISTS (SELECT 1 FROM workspaces WHERE id = ws AND owner_user_id = subject)
$$;


--
-- Name: perk_is_member(uuid, text); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.perk_is_member(ws uuid, required text DEFAULT NULL::text) RETURNS boolean
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path TO 'public', 'pg_temp'
    AS $$
 SELECT EXISTS (SELECT 1 FROM memberships WHERE workspace_id=ws AND user_id=perk_actor()
 AND (required IS NULL OR role=required OR (required='owner' AND role='admin')))
$$;


--
-- Name: perk_lock_store(uuid, uuid, text); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.perk_lock_store(ws uuid, sid uuid, p text) RETURNS boolean
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'public', 'pg_temp'
    AS $$
BEGIN
 IF NOT perk_store_access(ws,sid) OR NOT perk_permission(ws,p) THEN RETURN false; END IF;
 PERFORM 1 FROM stores WHERE workspace_id=ws AND id=sid AND is_active FOR KEY SHARE;
 RETURN FOUND;
END $$;


--
-- Name: perk_notification_users(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.perk_notification_users() RETURNS SETOF uuid
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path TO 'public', 'pg_temp'
    AS $$
      SELECT DISTINCT u.id FROM users u
        JOIN memberships m ON m.user_id=u.id
        JOIN stores s ON s.workspace_id=m.workspace_id
      WHERE u.is_active AND u.email_verified_at IS NOT NULL
        AND s.is_active AND s.marketplace IN ('wildberries','ozon')
      LIMIT 1000
    $$;


--
-- Name: perk_ozon_request_history(uuid, uuid, text, date, date, boolean); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.perk_ozon_request_history(ws uuid, sid uuid, src text, start date, finish date, reprice boolean DEFAULT false) RETURNS void
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'public', 'pg_temp'
    AS $$
    BEGIN
      IF NOT perk_store_access(ws,sid) OR src NOT IN ('sales','finance','traffic') OR
        NOT perk_permission(ws,CASE WHEN src='finance' THEN 'finance.read' ELSE 'analytics.read' END)
        OR start>finish OR finish>current_date OR start<current_date-1099 THEN RETURN; END IF;
      UPDATE ozon_analytics_sync SET
        history_from=LEAST(COALESCE(history_from,start),start),
        cursor=CASE WHEN cursor IS NOT NULL THEN cursor
          WHEN reprice AND status NOT IN ('pending','queued','running') THEN finish
          WHEN history_from IS NULL OR start<history_from THEN COALESCE(history_from-1,current_date-1)
          ELSE cursor END,
        status=CASE WHEN cursor IS NULL AND status NOT IN ('queued','running') THEN 'pending' ELSE status END,
        next_attempt_at=CASE WHEN cursor IS NULL AND status NOT IN ('queued','running') THEN now() ELSE next_attempt_at END,
        error_code=CASE WHEN reprice AND status NOT IN ('pending','queued','running') THEN NULL ELSE error_code END
      WHERE workspace_id=ws AND store_id=sid AND source=src AND
        (history_from IS NULL OR start<history_from OR reprice AND cursor IS NULL AND status NOT IN ('pending','queued','running'));
    END $$;


--
-- Name: perk_permission(uuid, text); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.perk_permission(ws uuid, p text) RETURNS boolean
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path TO 'public', 'pg_temp'
    AS $$
 SELECT EXISTS (SELECT 1 FROM memberships WHERE workspace_id=ws AND user_id=perk_actor()
 AND (role IN ('owner','admin') OR COALESCE(permissions,
 CASE role WHEN 'manager' THEN '["analytics.read","inventory.read"]'::jsonb
 WHEN 'accountant' THEN '["analytics.read","finance.read","profit.read",
 "costs.write","expenses.write","taxes.write","reports.export"]'::jsonb
 WHEN 'viewer' THEN '["analytics.read","inventory.read","finance.read","profit.read"]'::jsonb
 ELSE '[]'::jsonb END) ? p))
$$;


--
-- Name: perk_queue_actors(text); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.perk_queue_actors(queue text) RETURNS SETOF uuid
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path TO 'public', 'pg_temp'
    AS $$
      SELECT DISTINCT q.actor FROM (
        SELECT requested_by AS actor,workspace_id,store_id FROM sync_runs
          WHERE queue IN ('sync','warm') AND (queue='warm' OR
            (status IN ('queued','running') AND next_attempt_at<=now()))
        UNION ALL SELECT requested_by,workspace_id,store_id FROM ozon_analytics_sync
          WHERE queue='ozon_analytics' AND next_attempt_at<=now()
        UNION ALL SELECT requested_by,workspace_id,store_id FROM ozon_catalog_sync
          WHERE queue='ozon_catalog' AND next_attempt_at<=now()
        UNION ALL SELECT requested_by,workspace_id,store_id FROM supply_destination_sync
          WHERE queue='destinations' AND next_attempt_at<=now()
      ) q JOIN memberships m ON m.user_id=q.actor AND m.workspace_id=q.workspace_id
        JOIN users u ON u.id=q.actor
        JOIN stores s ON s.id=q.store_id AND s.workspace_id=q.workspace_id
      WHERE m.role IN ('owner','admin') AND u.is_active AND u.email_verified_at IS NOT NULL
        AND s.is_active AND s.connection_status='connected' LIMIT 1000
    $$;


--
-- Name: perk_reject_ozon_job(uuid, uuid, text, uuid, uuid); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.perk_reject_ozon_job(ws uuid, sid uuid, src text, actor uuid, run uuid) RETURNS void
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'public', 'pg_temp'
    AS $$
    BEGIN
      IF EXISTS(SELECT 1 FROM memberships m JOIN users u ON u.id=m.user_id
        JOIN stores s ON s.workspace_id=m.workspace_id
        WHERE m.user_id=actor AND m.workspace_id=ws AND s.id=sid
          AND m.role IN ('owner','admin') AND u.is_active AND u.email_verified_at IS NOT NULL
          AND s.is_active AND s.connection_status='connected') THEN RETURN; END IF;
      IF src='catalog' THEN
        UPDATE ozon_catalog_sync SET status='error',error_code='access_revoked',
          next_attempt_at=now()+interval '6 hours'
          WHERE workspace_id=ws AND store_id=sid AND run_id=run AND requested_by=actor;
      ELSE
        UPDATE ozon_analytics_sync SET status='error',error_code='access_revoked',
          next_attempt_at=now()+interval '6 hours'
          WHERE workspace_id=ws AND store_id=sid AND source=src AND run_id=run AND requested_by=actor;
      END IF;
    END $$;


--
-- Name: perk_request_funnel_history(uuid, uuid, date); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.perk_request_funnel_history(ws uuid, sid uuid, requested date) RETURNS boolean
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'public', 'pg_temp'
    AS $$
    DECLARE today date := (now() AT TIME ZONE 'Europe/Moscow')::date;
            oldest date := GREATEST(requested,today-359);
    BEGIN
      IF NOT perk_store_access(ws,sid) OR NOT perk_permission(ws,'analytics.read')
        OR requested IS NULL OR requested>=today THEN RETURN false; END IF;
      UPDATE sync_schedules SET
        backfill_to=GREATEST(backfill_to,COALESCE(history_from,today-7)-1),
        history_from=LEAST(COALESCE(history_from,oldest),oldest),
        next_attempt_at=LEAST(next_attempt_at,now())
      WHERE workspace_id=ws AND store_id=sid AND source='funnel' AND enabled
        AND (history_from IS NULL OR history_from>oldest);
      RETURN FOUND;
    END $$;


--
-- Name: perk_store_access(uuid, uuid); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.perk_store_access(ws uuid, sid uuid) RETURNS boolean
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path TO 'public', 'pg_temp'
    AS $$
 SELECT EXISTS (SELECT 1 FROM memberships WHERE workspace_id=ws AND user_id=perk_actor()
 AND (role IN ('owner','admin') OR store_ids IS NULL OR store_ids @> jsonb_build_array(sid::text)))
$$;


--
-- Name: perk_sync_actor(uuid, text); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.perk_sync_actor(run uuid, task text) RETURNS uuid
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'public', 'pg_temp'
    AS $$
    DECLARE job sync_runs%ROWTYPE;
    BEGIN
      SELECT * INTO job FROM sync_runs WHERE id=run AND task_id=task AND status IN ('queued','running');
      IF NOT FOUND THEN RETURN NULL; END IF;
      IF NOT EXISTS (SELECT 1 FROM memberships m JOIN users u ON u.id=m.user_id
          WHERE m.workspace_id=job.workspace_id AND m.user_id=job.requested_by
          AND m.role IN ('owner','admin') AND u.is_active AND u.email_verified_at IS NOT NULL) THEN
        UPDATE sync_runs SET status='failed',error_code='sync_permission_revoked',finished_at=now(),task_id=NULL WHERE id=run;
        DELETE FROM wb_staged_records WHERE run_id=run;
        DELETE FROM wb_daily_metrics WHERE dataset=run::text;
        RETURN NULL;
      END IF;
      RETURN job.requested_by;
    END $$;


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: access_tokens; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.access_tokens (
    session_id uuid NOT NULL,
    token_digest character varying(64) NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: alembic_version; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.alembic_version (
    version_num character varying(32) NOT NULL
);


--
-- Name: audit_events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.audit_events (
    user_id uuid,
    workspace_id uuid,
    action character varying(64) NOT NULL,
    target_id uuid,
    success boolean NOT NULL,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);

ALTER TABLE ONLY public.audit_events FORCE ROW LEVEL SECURITY;


--
-- Name: auth_sessions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.auth_sessions (
    user_id uuid NOT NULL,
    client character varying(16) NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    revoked_at timestamp with time zone,
    mfa_verified_at timestamp with time zone,
    csrf_digest character varying(64) NOT NULL,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    step_up_at timestamp with time zone,
    strong_step_up_at timestamp with time zone
);


--
-- Name: catalog_import_previews; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.catalog_import_previews (
    workspace_id uuid NOT NULL,
    id uuid NOT NULL,
    store_id uuid NOT NULL,
    created_by uuid NOT NULL,
    kind character varying(20) NOT NULL,
    ciphertext text NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    consumed_at timestamp with time zone
);

ALTER TABLE ONLY public.catalog_import_previews FORCE ROW LEVEL SECURITY;


--
-- Name: catalog_overrides; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.catalog_overrides (
    workspace_id uuid NOT NULL,
    store_id uuid NOT NULL,
    nm_id character varying(32) NOT NULL,
    model_key character varying(96) NOT NULL,
    ciphertext text NOT NULL,
    created_by uuid NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);

ALTER TABLE ONLY public.catalog_overrides FORCE ROW LEVEL SECURITY;


--
-- Name: catalog_product_matches; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.catalog_product_matches (
    workspace_id uuid NOT NULL,
    id uuid NOT NULL,
    left_store_id uuid NOT NULL,
    right_store_id uuid NOT NULL,
    left_variant_id uuid NOT NULL,
    right_variant_id uuid NOT NULL,
    ciphertext text NOT NULL,
    created_by uuid NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);

ALTER TABLE ONLY public.catalog_product_matches FORCE ROW LEVEL SECURITY;


--
-- Name: cost_imports; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.cost_imports (
    workspace_id uuid NOT NULL,
    store_id uuid NOT NULL,
    id uuid NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    ciphertext text NOT NULL,
    created_by uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);

ALTER TABLE ONLY public.cost_imports FORCE ROW LEVEL SECURITY;


--
-- Name: external_expenses; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.external_expenses (
    workspace_id uuid NOT NULL,
    store_id uuid NOT NULL,
    id uuid NOT NULL,
    expense_date date NOT NULL,
    currency character varying(3) NOT NULL,
    deleted_at timestamp with time zone,
    ciphertext text NOT NULL,
    created_by uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);

ALTER TABLE ONLY public.external_expenses FORCE ROW LEVEL SECURITY;


--
-- Name: finance_days; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.finance_days (
    workspace_id uuid NOT NULL,
    store_id uuid NOT NULL,
    day date NOT NULL,
    currency character varying(16) NOT NULL,
    ciphertext text NOT NULL
);

ALTER TABLE ONLY public.finance_days FORCE ROW LEVEL SECURITY;


--
-- Name: finance_projections; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.finance_projections (
    workspace_id uuid NOT NULL,
    store_id uuid NOT NULL,
    source_run_id uuid NOT NULL,
    format_version integer NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    legacy_date_from date,
    legacy_date_to date
);

ALTER TABLE ONLY public.finance_projections FORCE ROW LEVEL SECURITY;


--
-- Name: import_issues; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.import_issues (
    id uuid NOT NULL,
    workspace_id uuid NOT NULL,
    store_id uuid NOT NULL,
    source character varying(32) NOT NULL,
    record_key character varying(64) NOT NULL,
    reason character varying(64) NOT NULL,
    ciphertext text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);

ALTER TABLE ONLY public.import_issues FORCE ROW LEVEL SECURITY;


--
-- Name: insight_snapshots; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.insight_snapshots (
    workspace_id uuid NOT NULL,
    store_id uuid NOT NULL,
    kind character varying(32) NOT NULL,
    params_key character varying(64) NOT NULL,
    revision character varying(64) NOT NULL,
    computed_at timestamp with time zone NOT NULL,
    ciphertext text NOT NULL
);

ALTER TABLE ONLY public.insight_snapshots FORCE ROW LEVEL SECURITY;


--
-- Name: inventory_settings; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.inventory_settings (
    workspace_id uuid NOT NULL,
    fbs_mode character varying(16) NOT NULL,
    updated_by uuid NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_inventory_settings_fbs_mode CHECK (((fbs_mode)::text = ANY (ARRAY[('separate'::character varying)::text, ('shared'::character varying)::text])))
);

ALTER TABLE ONLY public.inventory_settings FORCE ROW LEVEL SECURITY;


--
-- Name: inventory_snapshots; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.inventory_snapshots (
    workspace_id uuid NOT NULL,
    store_id uuid NOT NULL,
    day date NOT NULL,
    nm_id character varying(32) NOT NULL,
    ciphertext text NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    channel character varying(3) DEFAULT 'fbo'::character varying NOT NULL,
    CONSTRAINT ck_inventory_snapshots_channel CHECK (((channel)::text = ANY (ARRAY[('fbo'::character varying)::text, ('fbs'::character varying)::text])))
);

ALTER TABLE ONLY public.inventory_snapshots FORCE ROW LEVEL SECURITY;


--
-- Name: marketplace_catalog_snapshots; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.marketplace_catalog_snapshots (
    workspace_id uuid NOT NULL,
    store_id uuid NOT NULL,
    ciphertext text NOT NULL,
    updated_at timestamp with time zone NOT NULL
);

ALTER TABLE ONLY public.marketplace_catalog_snapshots FORCE ROW LEVEL SECURITY;


--
-- Name: marketplace_finance_days; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.marketplace_finance_days (
    workspace_id uuid NOT NULL,
    store_id uuid NOT NULL,
    day date NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    ciphertext text NOT NULL
);

ALTER TABLE ONLY public.marketplace_finance_days FORCE ROW LEVEL SECURITY;


--
-- Name: marketplace_realizations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.marketplace_realizations (
    workspace_id uuid NOT NULL,
    store_id uuid NOT NULL,
    day date NOT NULL,
    posting_key character varying(64) NOT NULL,
    sku character varying(32) NOT NULL,
    ciphertext text NOT NULL
);

ALTER TABLE ONLY public.marketplace_realizations FORCE ROW LEVEL SECURITY;


--
-- Name: marketplace_sales_days; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.marketplace_sales_days (
    workspace_id uuid NOT NULL,
    store_id uuid NOT NULL,
    day date NOT NULL,
    ciphertext text NOT NULL,
    updated_at timestamp with time zone NOT NULL
);

ALTER TABLE ONLY public.marketplace_sales_days FORCE ROW LEVEL SECURITY;


--
-- Name: marketplace_stock_cover; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.marketplace_stock_cover (
    workspace_id uuid NOT NULL,
    store_id uuid NOT NULL,
    ciphertext text NOT NULL,
    updated_at timestamp with time zone NOT NULL
);

ALTER TABLE ONLY public.marketplace_stock_cover FORCE ROW LEVEL SECURITY;


--
-- Name: marketplace_supply_snapshots; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.marketplace_supply_snapshots (
    workspace_id uuid NOT NULL,
    store_id uuid NOT NULL,
    ciphertext text NOT NULL,
    updated_at timestamp with time zone NOT NULL
);

ALTER TABLE ONLY public.marketplace_supply_snapshots FORCE ROW LEVEL SECURITY;


--
-- Name: marketplace_traffic_days; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.marketplace_traffic_days (
    workspace_id uuid NOT NULL,
    store_id uuid NOT NULL,
    day date NOT NULL,
    ciphertext text NOT NULL,
    updated_at timestamp with time zone NOT NULL
);

ALTER TABLE ONLY public.marketplace_traffic_days FORCE ROW LEVEL SECURITY;


--
-- Name: marketplace_variant_costs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.marketplace_variant_costs (
    workspace_id uuid NOT NULL,
    store_id uuid NOT NULL,
    variant_id uuid NOT NULL,
    currency character varying(3) NOT NULL,
    effective_from date NOT NULL,
    ciphertext text NOT NULL,
    created_by uuid NOT NULL,
    created_at timestamp with time zone NOT NULL
);

ALTER TABLE ONLY public.marketplace_variant_costs FORCE ROW LEVEL SECURITY;


--
-- Name: memberships; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.memberships (
    user_id uuid NOT NULL,
    workspace_id uuid NOT NULL,
    role character varying(16) NOT NULL,
    permissions jsonb,
    store_ids jsonb,
    CONSTRAINT ck_memberships_permissions_array CHECK (((permissions IS NULL) OR (jsonb_typeof(permissions) = 'array'::text))),
    CONSTRAINT ck_memberships_role CHECK (((role)::text = ANY (ARRAY[('owner'::character varying)::text, ('admin'::character varying)::text, ('manager'::character varying)::text, ('accountant'::character varying)::text, ('viewer'::character varying)::text]))),
    CONSTRAINT ck_memberships_stores_array CHECK (((store_ids IS NULL) OR (jsonb_typeof(store_ids) = 'array'::text)))
);

ALTER TABLE ONLY public.memberships FORCE ROW LEVEL SECURITY;


--
-- Name: notification_settings; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.notification_settings (
    user_id uuid NOT NULL,
    telegram_chat_ciphertext text,
    telegram_linked_at timestamp with time zone,
    digest_enabled boolean DEFAULT true NOT NULL,
    digest_hour integer DEFAULT 9 NOT NULL,
    alerts_enabled boolean DEFAULT true NOT NULL,
    telegram_enabled boolean DEFAULT true NOT NULL,
    push_enabled boolean DEFAULT true NOT NULL,
    last_digest_on date,
    categories jsonb DEFAULT '{}'::jsonb NOT NULL,
    timezone character varying(64) DEFAULT 'Europe/Moscow'::character varying NOT NULL,
    digest_mode character varying(16) DEFAULT 'morning'::character varying NOT NULL,
    quiet_start integer DEFAULT 22 NOT NULL,
    quiet_end integer DEFAULT 9 NOT NULL,
    show_details boolean DEFAULT false NOT NULL
);


--
-- Name: notifications; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.notifications (
    user_id uuid NOT NULL,
    workspace_id uuid,
    store_id uuid,
    kind character varying(32) NOT NULL,
    severity character varying(16) NOT NULL,
    dedupe_key character varying(64) NOT NULL,
    ciphertext text NOT NULL,
    read_at timestamp with time zone,
    delivered_at timestamp with time zone,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    required_permissions jsonb DEFAULT '[]'::jsonb NOT NULL,
    source_store_ids jsonb DEFAULT '[]'::jsonb NOT NULL,
    incident_key character varying(64),
    acknowledged_at timestamp with time zone,
    resolved_at timestamp with time zone,
    delivery_state jsonb DEFAULT '{}'::jsonb NOT NULL
);

ALTER TABLE ONLY public.notifications FORCE ROW LEVEL SECURITY;


--
-- Name: otp_challenges; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.otp_challenges (
    user_id uuid,
    session_id uuid,
    purpose character varying(32) NOT NULL,
    channel character varying(16) NOT NULL,
    destination_digest character varying(64) NOT NULL,
    code_digest character varying(64) NOT NULL,
    payload_ciphertext text,
    attempts integer DEFAULT 0 NOT NULL,
    sent_count integer DEFAULT 1 NOT NULL,
    last_sent_at timestamp with time zone NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    consumed_at timestamp with time zone,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_otp_challenges_channel CHECK (((channel)::text = ANY (ARRAY[('email'::character varying)::text, ('telegram'::character varying)::text, ('sms'::character varying)::text]))),
    CONSTRAINT ck_otp_challenges_counters CHECK (((attempts >= 0) AND (sent_count >= 1))),
    CONSTRAINT ck_otp_challenges_purpose CHECK (((purpose)::text = ANY ((ARRAY['register'::character varying, 'login'::character varying, 'step_up'::character varying, 'phone_verify'::character varying, 'phone_change'::character varying, 'password_reset'::character varying])::text[])))
);


--
-- Name: ozon_analytics_sync; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ozon_analytics_sync (
    workspace_id uuid NOT NULL,
    store_id uuid NOT NULL,
    source character varying(16) NOT NULL,
    requested_by uuid NOT NULL,
    status character varying(16) DEFAULT 'pending'::character varying NOT NULL,
    run_id uuid,
    next_attempt_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone,
    records_processed integer DEFAULT 0 NOT NULL,
    error_code character varying(64),
    history_from date,
    cursor date,
    date_from date,
    date_to date,
    mode character varying(16) DEFAULT 'history'::character varying NOT NULL,
    CONSTRAINT ck_ozon_analytics_sync_source CHECK (((source)::text = ANY (ARRAY[('sales'::character varying)::text, ('stock_cover'::character varying)::text, ('finance'::character varying)::text, ('traffic'::character varying)::text, ('supplies'::character varying)::text]))),
    CONSTRAINT ck_ozon_analytics_sync_status CHECK (((status)::text = ANY (ARRAY[('pending'::character varying)::text, ('queued'::character varying)::text, ('running'::character varying)::text, ('ready'::character varying)::text, ('error'::character varying)::text])))
);

ALTER TABLE ONLY public.ozon_analytics_sync FORCE ROW LEVEL SECURITY;


--
-- Name: ozon_catalog_sync; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ozon_catalog_sync (
    workspace_id uuid NOT NULL,
    store_id uuid NOT NULL,
    requested_by uuid NOT NULL,
    status character varying(16) DEFAULT 'pending'::character varying NOT NULL,
    run_id uuid,
    next_attempt_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone,
    records_processed integer DEFAULT 0 NOT NULL,
    error_code character varying(64),
    CONSTRAINT ck_ozon_catalog_sync_status CHECK (((status)::text = ANY (ARRAY[('pending'::character varying)::text, ('queued'::character varying)::text, ('running'::character varying)::text, ('ready'::character varying)::text, ('error'::character varying)::text])))
);

ALTER TABLE ONLY public.ozon_catalog_sync FORCE ROW LEVEL SECURITY;


--
-- Name: product_costs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.product_costs (
    workspace_id uuid NOT NULL,
    store_id uuid NOT NULL,
    nm_id character varying(32) NOT NULL,
    barcode character varying(100) NOT NULL,
    currency character varying(3) NOT NULL,
    effective_from date NOT NULL,
    ciphertext text NOT NULL,
    created_by uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);

ALTER TABLE ONLY public.product_costs FORCE ROW LEVEL SECURITY;


--
-- Name: push_devices; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.push_devices (
    user_id uuid NOT NULL,
    token_digest character varying(64) NOT NULL,
    token_ciphertext text NOT NULL,
    platform character varying(16) NOT NULL,
    last_seen_at timestamp with time zone NOT NULL,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    session_id uuid,
    session_started_at timestamp with time zone
);


--
-- Name: recovery_codes; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.recovery_codes (
    user_id uuid NOT NULL,
    code_digest character varying(64) NOT NULL,
    used_at timestamp with time zone,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: refresh_tokens; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.refresh_tokens (
    session_id uuid NOT NULL,
    token_digest character varying(64) NOT NULL,
    used_at timestamp with time zone,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: store_credentials; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.store_credentials (
    workspace_id uuid NOT NULL,
    store_id uuid NOT NULL,
    ciphertext text NOT NULL,
    scopes character varying(500) NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);

ALTER TABLE ONLY public.store_credentials FORCE ROW LEVEL SECURITY;


--
-- Name: store_events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.store_events (
    workspace_id uuid NOT NULL,
    store_id uuid NOT NULL,
    id uuid NOT NULL,
    day date NOT NULL,
    kind character varying(32) NOT NULL,
    nm_id character varying(32),
    ciphertext text NOT NULL,
    created_by uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);

ALTER TABLE ONLY public.store_events FORCE ROW LEVEL SECURITY;


--
-- Name: store_goals; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.store_goals (
    workspace_id uuid NOT NULL,
    store_id uuid NOT NULL,
    month date NOT NULL,
    metric character varying(16) NOT NULL,
    ciphertext text NOT NULL,
    created_by uuid NOT NULL,
    updated_at timestamp with time zone NOT NULL
);

ALTER TABLE ONLY public.store_goals FORCE ROW LEVEL SECURITY;


--
-- Name: stores; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.stores (
    workspace_id uuid NOT NULL,
    name character varying(200) NOT NULL,
    marketplace character varying(32) NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    external_seller_id character varying(100),
    connection_status character varying(32) DEFAULT 'not_connected'::character varying NOT NULL,
    last_checked_at timestamp with time zone,
    CONSTRAINT ck_stores_marketplace CHECK (((marketplace)::text = ANY (ARRAY[('wildberries'::character varying)::text, ('ozon'::character varying)::text])))
);

ALTER TABLE ONLY public.stores FORCE ROW LEVEL SECURITY;


--
-- Name: supply_destination_snapshots; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.supply_destination_snapshots (
    workspace_id uuid NOT NULL,
    store_id uuid NOT NULL,
    product_key character varying(24) NOT NULL,
    ciphertext text NOT NULL,
    updated_at timestamp with time zone NOT NULL
);

ALTER TABLE ONLY public.supply_destination_snapshots FORCE ROW LEVEL SECURITY;


--
-- Name: supply_destination_sync; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.supply_destination_sync (
    workspace_id uuid NOT NULL,
    store_id uuid NOT NULL,
    product_key character varying(24) NOT NULL,
    requested_by uuid NOT NULL,
    status character varying(16) NOT NULL,
    run_id uuid,
    date_from date NOT NULL,
    date_to date NOT NULL,
    next_attempt_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone,
    error_code character varying(64),
    CONSTRAINT ck_supply_destination_sync_status CHECK (((status)::text = ANY (ARRAY[('pending'::character varying)::text, ('queued'::character varying)::text, ('running'::character varying)::text, ('ready'::character varying)::text, ('error'::character varying)::text])))
);

ALTER TABLE ONLY public.supply_destination_sync FORCE ROW LEVEL SECURITY;


--
-- Name: supply_packaging; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.supply_packaging (
    workspace_id uuid NOT NULL,
    store_id uuid NOT NULL,
    product_key character varying(100) NOT NULL,
    box_multiple integer NOT NULL,
    updated_by uuid NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_supply_packaging_box_multiple CHECK (((box_multiple >= 1) AND (box_multiple <= 10000)))
);

ALTER TABLE ONLY public.supply_packaging FORCE ROW LEVEL SECURITY;


--
-- Name: supply_plans; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.supply_plans (
    workspace_id uuid NOT NULL,
    id uuid NOT NULL,
    store_id uuid NOT NULL,
    revision integer NOT NULL,
    ciphertext text NOT NULL,
    created_by uuid NOT NULL,
    updated_by uuid NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_supply_plans_plan_revision CHECK ((revision >= 1))
);

ALTER TABLE ONLY public.supply_plans FORCE ROW LEVEL SECURITY;


--
-- Name: sync_runs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.sync_runs (
    workspace_id uuid NOT NULL,
    store_id uuid NOT NULL,
    source character varying(64) NOT NULL,
    status character varying(16) DEFAULT 'queued'::character varying NOT NULL,
    task_id character varying(255),
    records_processed integer DEFAULT 0 NOT NULL,
    started_at timestamp with time zone,
    finished_at timestamp with time zone,
    error_code character varying(64),
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    requested_by uuid,
    date_from date,
    date_to date,
    cursor json DEFAULT '{}'::json NOT NULL,
    pages_processed integer DEFAULT 0 NOT NULL,
    attempts integer DEFAULT 0 NOT NULL,
    next_attempt_at timestamp with time zone DEFAULT now() NOT NULL,
    sync_mode character varying(16) DEFAULT 'manual'::character varying NOT NULL,
    preview_updated_at timestamp with time zone,
    CONSTRAINT ck_sync_runs_records_nonnegative CHECK ((records_processed >= 0)),
    CONSTRAINT ck_sync_runs_status CHECK (((status)::text = ANY (ARRAY[('queued'::character varying)::text, ('running'::character varying)::text, ('succeeded'::character varying)::text, ('failed'::character varying)::text])))
);

ALTER TABLE ONLY public.sync_runs FORCE ROW LEVEL SECURITY;


--
-- Name: sync_schedules; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.sync_schedules (
    workspace_id uuid NOT NULL,
    store_id uuid NOT NULL,
    source character varying(16) NOT NULL,
    requested_by uuid NOT NULL,
    enabled boolean DEFAULT false NOT NULL,
    recent_days integer DEFAULT 7 NOT NULL,
    recent_completed boolean DEFAULT false NOT NULL,
    history_from date,
    backfill_to date,
    history_turn boolean DEFAULT false NOT NULL,
    backfill_chunk_days integer DEFAULT 31 NOT NULL,
    sales_cursor character varying(64),
    next_refresh_at timestamp with time zone NOT NULL,
    next_attempt_at timestamp with time zone NOT NULL,
    last_completed_at timestamp with time zone,
    reconcile_at timestamp with time zone NOT NULL,
    error_code character varying(64),
    CONSTRAINT ck_sync_schedules_recent_days CHECK (((recent_days >= 7) AND (recent_days <= 30))),
    CONSTRAINT ck_sync_schedules_source CHECK (((source)::text = ANY (ARRAY[('catalog'::character varying)::text, ('sales'::character varying)::text, ('stocks'::character varying)::text, ('finance'::character varying)::text, ('orders'::character varying)::text, ('funnel'::character varying)::text, ('returns'::character varying)::text, ('balance'::character varying)::text, ('prices'::character varying)::text, ('fbs'::character varying)::text, ('stock_history'::character varying)::text, ('supply_demand'::character varying)::text, ('supplies'::character varying)::text, ('fbs_demand'::character varying)::text])))
);

ALTER TABLE ONLY public.sync_schedules FORCE ROW LEVEL SECURITY;


--
-- Name: tax_settings; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.tax_settings (
    workspace_id uuid NOT NULL,
    store_id uuid NOT NULL,
    effective_from date NOT NULL,
    regime character varying(32) NOT NULL,
    rate numeric(5,2) NOT NULL,
    vat_rate numeric(5,2) NOT NULL,
    income_base character varying(16) NOT NULL,
    created_by uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_tax_settings_income_base CHECK (((income_base)::text = ANY (ARRAY[('revenue'::character varying)::text, ('payout'::character varying)::text]))),
    CONSTRAINT ck_tax_settings_rates CHECK (((rate >= (0)::numeric) AND (rate <= (100)::numeric) AND (vat_rate >= (0)::numeric) AND (vat_rate <= (100)::numeric))),
    CONSTRAINT ck_tax_settings_regime CHECK (((regime)::text = ANY (ARRAY[('none'::character varying)::text, ('usn_income'::character varying)::text, ('usn_income_expense'::character varying)::text, ('profit'::character varying)::text])))
);

ALTER TABLE ONLY public.tax_settings FORCE ROW LEVEL SECURITY;


--
-- Name: users; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.users (
    email character varying(320) NOT NULL,
    password_hash character varying(255) NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    totp_ciphertext text,
    totp_pending_ciphertext text,
    totp_pending_until timestamp with time zone,
    totp_last_step integer,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    email_verified_at timestamp with time zone,
    phone character varying(16),
    phone_verified_at timestamp with time zone,
    phone_channel character varying(16),
    CONSTRAINT ck_users_phone_channel CHECK (((phone_channel)::text = ANY (ARRAY[('telegram'::character varying)::text, ('sms'::character varying)::text])))
);


--
-- Name: wb_daily_metrics; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.wb_daily_metrics (
    workspace_id uuid NOT NULL,
    store_id uuid NOT NULL,
    source character varying(16) NOT NULL,
    dataset character varying(36) NOT NULL,
    day date NOT NULL,
    nm_id character varying(32) NOT NULL,
    currency character varying(16) NOT NULL,
    ciphertext text NOT NULL,
    CONSTRAINT ck_wb_daily_metrics_source CHECK (((source)::text = ANY (ARRAY[('sales'::character varying)::text, ('finance'::character varying)::text, ('orders'::character varying)::text, ('funnel'::character varying)::text])))
);

ALTER TABLE ONLY public.wb_daily_metrics FORCE ROW LEVEL SECURITY;


--
-- Name: wb_metric_versions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.wb_metric_versions (
    workspace_id uuid NOT NULL,
    store_id uuid NOT NULL,
    version uuid NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    warmed_version uuid,
    format_version integer DEFAULT 1 NOT NULL
);

ALTER TABLE ONLY public.wb_metric_versions FORCE ROW LEVEL SECURITY;


--
-- Name: wb_records; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.wb_records (
    workspace_id uuid NOT NULL,
    store_id uuid NOT NULL,
    source character varying(16) NOT NULL,
    record_key character varying(128) NOT NULL,
    ciphertext text NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_wb_records_source CHECK (((source)::text = ANY (ARRAY[('catalog'::character varying)::text, ('sales'::character varying)::text, ('stocks'::character varying)::text, ('finance'::character varying)::text, ('orders'::character varying)::text, ('funnel'::character varying)::text, ('returns'::character varying)::text, ('balance'::character varying)::text, ('prices'::character varying)::text, ('fbs'::character varying)::text, ('stock_history'::character varying)::text, ('supply_demand'::character varying)::text, ('supplies'::character varying)::text, ('fbs_demand'::character varying)::text])))
);

ALTER TABLE ONLY public.wb_records FORCE ROW LEVEL SECURITY;


--
-- Name: wb_staged_records; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.wb_staged_records (
    workspace_id uuid NOT NULL,
    store_id uuid NOT NULL,
    run_id uuid NOT NULL,
    record_key character varying(128) NOT NULL,
    ciphertext text NOT NULL
);

ALTER TABLE ONLY public.wb_staged_records FORCE ROW LEVEL SECURITY;


--
-- Name: workspace_invites; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.workspace_invites (
    workspace_id uuid NOT NULL,
    email character varying(320) NOT NULL,
    role character varying(16) NOT NULL,
    token_digest character varying(64) NOT NULL,
    invited_by uuid NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    accepted_at timestamp with time zone,
    accepted_by uuid,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    permissions jsonb,
    store_ids jsonb,
    CONSTRAINT ck_workspace_invites_permissions_array CHECK (((permissions IS NULL) OR (jsonb_typeof(permissions) = 'array'::text))),
    CONSTRAINT ck_workspace_invites_role CHECK (((role)::text = ANY (ARRAY[('owner'::character varying)::text, ('admin'::character varying)::text, ('manager'::character varying)::text, ('accountant'::character varying)::text, ('viewer'::character varying)::text]))),
    CONSTRAINT ck_workspace_invites_stores_array CHECK (((store_ids IS NULL) OR (jsonb_typeof(store_ids) = 'array'::text)))
);

ALTER TABLE ONLY public.workspace_invites FORCE ROW LEVEL SECURITY;


--
-- Name: workspaces; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.workspaces (
    name character varying(200) NOT NULL,
    timezone character varying(64) DEFAULT 'Europe/Moscow'::character varying NOT NULL,
    currency character varying(3) DEFAULT 'RUB'::character varying NOT NULL,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    owner_user_id uuid
);

ALTER TABLE ONLY public.workspaces FORCE ROW LEVEL SECURITY;


--
-- Name: alembic_version alembic_version_pkc; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alembic_version
    ADD CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num);


--
-- Name: access_tokens pk_access_tokens; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.access_tokens
    ADD CONSTRAINT pk_access_tokens PRIMARY KEY (id);


--
-- Name: audit_events pk_audit_events; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_events
    ADD CONSTRAINT pk_audit_events PRIMARY KEY (id);


--
-- Name: auth_sessions pk_auth_sessions; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_sessions
    ADD CONSTRAINT pk_auth_sessions PRIMARY KEY (id);


--
-- Name: catalog_import_previews pk_catalog_import_previews; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.catalog_import_previews
    ADD CONSTRAINT pk_catalog_import_previews PRIMARY KEY (workspace_id, id);


--
-- Name: catalog_overrides pk_catalog_overrides; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.catalog_overrides
    ADD CONSTRAINT pk_catalog_overrides PRIMARY KEY (workspace_id, store_id, nm_id);


--
-- Name: catalog_product_matches pk_catalog_product_matches; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.catalog_product_matches
    ADD CONSTRAINT pk_catalog_product_matches PRIMARY KEY (workspace_id, id);


--
-- Name: cost_imports pk_cost_imports; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cost_imports
    ADD CONSTRAINT pk_cost_imports PRIMARY KEY (workspace_id, store_id, id);


--
-- Name: external_expenses pk_external_expenses; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.external_expenses
    ADD CONSTRAINT pk_external_expenses PRIMARY KEY (workspace_id, store_id, id);


--
-- Name: finance_days pk_finance_days; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_days
    ADD CONSTRAINT pk_finance_days PRIMARY KEY (workspace_id, store_id, day, currency);


--
-- Name: finance_projections pk_finance_projections; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_projections
    ADD CONSTRAINT pk_finance_projections PRIMARY KEY (workspace_id, store_id);


--
-- Name: import_issues pk_import_issues; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.import_issues
    ADD CONSTRAINT pk_import_issues PRIMARY KEY (id);


--
-- Name: insight_snapshots pk_insight_snapshots; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.insight_snapshots
    ADD CONSTRAINT pk_insight_snapshots PRIMARY KEY (workspace_id, store_id, kind, params_key);


--
-- Name: inventory_settings pk_inventory_settings; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.inventory_settings
    ADD CONSTRAINT pk_inventory_settings PRIMARY KEY (workspace_id);


--
-- Name: inventory_snapshots pk_inventory_snapshots; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.inventory_snapshots
    ADD CONSTRAINT pk_inventory_snapshots PRIMARY KEY (workspace_id, store_id, day, nm_id, channel);


--
-- Name: marketplace_catalog_snapshots pk_marketplace_catalog_snapshots; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.marketplace_catalog_snapshots
    ADD CONSTRAINT pk_marketplace_catalog_snapshots PRIMARY KEY (workspace_id, store_id);


--
-- Name: marketplace_finance_days pk_marketplace_finance_days; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.marketplace_finance_days
    ADD CONSTRAINT pk_marketplace_finance_days PRIMARY KEY (workspace_id, store_id, day);


--
-- Name: marketplace_realizations pk_marketplace_realizations; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.marketplace_realizations
    ADD CONSTRAINT pk_marketplace_realizations PRIMARY KEY (workspace_id, store_id, day, posting_key, sku);


--
-- Name: marketplace_sales_days pk_marketplace_sales_days; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.marketplace_sales_days
    ADD CONSTRAINT pk_marketplace_sales_days PRIMARY KEY (workspace_id, store_id, day);


--
-- Name: marketplace_stock_cover pk_marketplace_stock_cover; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.marketplace_stock_cover
    ADD CONSTRAINT pk_marketplace_stock_cover PRIMARY KEY (workspace_id, store_id);


--
-- Name: marketplace_supply_snapshots pk_marketplace_supply_snapshots; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.marketplace_supply_snapshots
    ADD CONSTRAINT pk_marketplace_supply_snapshots PRIMARY KEY (workspace_id, store_id);


--
-- Name: marketplace_traffic_days pk_marketplace_traffic_days; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.marketplace_traffic_days
    ADD CONSTRAINT pk_marketplace_traffic_days PRIMARY KEY (workspace_id, store_id, day);


--
-- Name: marketplace_variant_costs pk_marketplace_variant_costs; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.marketplace_variant_costs
    ADD CONSTRAINT pk_marketplace_variant_costs PRIMARY KEY (workspace_id, store_id, variant_id, currency, effective_from);


--
-- Name: memberships pk_memberships; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.memberships
    ADD CONSTRAINT pk_memberships PRIMARY KEY (user_id, workspace_id);


--
-- Name: notification_settings pk_notification_settings; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notification_settings
    ADD CONSTRAINT pk_notification_settings PRIMARY KEY (user_id);


--
-- Name: notifications pk_notifications; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notifications
    ADD CONSTRAINT pk_notifications PRIMARY KEY (id);


--
-- Name: otp_challenges pk_otp_challenges; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.otp_challenges
    ADD CONSTRAINT pk_otp_challenges PRIMARY KEY (id);


--
-- Name: ozon_analytics_sync pk_ozon_analytics_sync; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ozon_analytics_sync
    ADD CONSTRAINT pk_ozon_analytics_sync PRIMARY KEY (workspace_id, store_id, source);


--
-- Name: ozon_catalog_sync pk_ozon_catalog_sync; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ozon_catalog_sync
    ADD CONSTRAINT pk_ozon_catalog_sync PRIMARY KEY (workspace_id, store_id);


--
-- Name: product_costs pk_product_costs; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.product_costs
    ADD CONSTRAINT pk_product_costs PRIMARY KEY (workspace_id, store_id, nm_id, barcode, currency, effective_from);


--
-- Name: push_devices pk_push_devices; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.push_devices
    ADD CONSTRAINT pk_push_devices PRIMARY KEY (id);


--
-- Name: recovery_codes pk_recovery_codes; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.recovery_codes
    ADD CONSTRAINT pk_recovery_codes PRIMARY KEY (id);


--
-- Name: refresh_tokens pk_refresh_tokens; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.refresh_tokens
    ADD CONSTRAINT pk_refresh_tokens PRIMARY KEY (id);


--
-- Name: store_credentials pk_store_credentials; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_credentials
    ADD CONSTRAINT pk_store_credentials PRIMARY KEY (id);


--
-- Name: store_events pk_store_events; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_events
    ADD CONSTRAINT pk_store_events PRIMARY KEY (workspace_id, store_id, id);


--
-- Name: store_goals pk_store_goals; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_goals
    ADD CONSTRAINT pk_store_goals PRIMARY KEY (workspace_id, store_id, month, metric);


--
-- Name: stores pk_stores; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.stores
    ADD CONSTRAINT pk_stores PRIMARY KEY (id);


--
-- Name: supply_destination_snapshots pk_supply_destination_snapshots; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.supply_destination_snapshots
    ADD CONSTRAINT pk_supply_destination_snapshots PRIMARY KEY (workspace_id, store_id, product_key);


--
-- Name: supply_destination_sync pk_supply_destination_sync; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.supply_destination_sync
    ADD CONSTRAINT pk_supply_destination_sync PRIMARY KEY (workspace_id, store_id, product_key);


--
-- Name: supply_packaging pk_supply_packaging; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.supply_packaging
    ADD CONSTRAINT pk_supply_packaging PRIMARY KEY (workspace_id, store_id, product_key);


--
-- Name: supply_plans pk_supply_plans; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.supply_plans
    ADD CONSTRAINT pk_supply_plans PRIMARY KEY (workspace_id, id);


--
-- Name: sync_runs pk_sync_runs; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sync_runs
    ADD CONSTRAINT pk_sync_runs PRIMARY KEY (id);


--
-- Name: sync_schedules pk_sync_schedules; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sync_schedules
    ADD CONSTRAINT pk_sync_schedules PRIMARY KEY (workspace_id, store_id, source);


--
-- Name: tax_settings pk_tax_settings; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tax_settings
    ADD CONSTRAINT pk_tax_settings PRIMARY KEY (workspace_id, store_id, effective_from);


--
-- Name: users pk_users; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT pk_users PRIMARY KEY (id);


--
-- Name: wb_daily_metrics pk_wb_daily_metrics; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.wb_daily_metrics
    ADD CONSTRAINT pk_wb_daily_metrics PRIMARY KEY (workspace_id, store_id, source, dataset, day, nm_id, currency);


--
-- Name: wb_metric_versions pk_wb_metric_versions; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.wb_metric_versions
    ADD CONSTRAINT pk_wb_metric_versions PRIMARY KEY (workspace_id, store_id);


--
-- Name: wb_records pk_wb_records; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.wb_records
    ADD CONSTRAINT pk_wb_records PRIMARY KEY (workspace_id, store_id, source, record_key);


--
-- Name: wb_staged_records pk_wb_staged_records; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.wb_staged_records
    ADD CONSTRAINT pk_wb_staged_records PRIMARY KEY (run_id, record_key);


--
-- Name: workspace_invites pk_workspace_invites; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspace_invites
    ADD CONSTRAINT pk_workspace_invites PRIMARY KEY (id);


--
-- Name: workspaces pk_workspaces; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspaces
    ADD CONSTRAINT pk_workspaces PRIMARY KEY (id);


--
-- Name: access_tokens uq_access_tokens_token_digest; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.access_tokens
    ADD CONSTRAINT uq_access_tokens_token_digest UNIQUE (token_digest);


--
-- Name: catalog_product_matches uq_catalog_match_left; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.catalog_product_matches
    ADD CONSTRAINT uq_catalog_match_left UNIQUE (workspace_id, left_store_id, left_variant_id, right_store_id);


--
-- Name: catalog_product_matches uq_catalog_match_right; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.catalog_product_matches
    ADD CONSTRAINT uq_catalog_match_right UNIQUE (workspace_id, right_store_id, right_variant_id, left_store_id);


--
-- Name: import_issues uq_import_issues_workspace_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.import_issues
    ADD CONSTRAINT uq_import_issues_workspace_id UNIQUE (workspace_id, store_id, source, record_key);


--
-- Name: notifications uq_notifications_user_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notifications
    ADD CONSTRAINT uq_notifications_user_id UNIQUE (user_id, dedupe_key);


--
-- Name: push_devices uq_push_devices_token_digest; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.push_devices
    ADD CONSTRAINT uq_push_devices_token_digest UNIQUE (token_digest);


--
-- Name: recovery_codes uq_recovery_codes_user_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.recovery_codes
    ADD CONSTRAINT uq_recovery_codes_user_id UNIQUE (user_id, code_digest);


--
-- Name: refresh_tokens uq_refresh_tokens_token_digest; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.refresh_tokens
    ADD CONSTRAINT uq_refresh_tokens_token_digest UNIQUE (token_digest);


--
-- Name: store_credentials uq_store_credentials_store_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_credentials
    ADD CONSTRAINT uq_store_credentials_store_id UNIQUE (store_id);


--
-- Name: stores uq_stores_workspace_id_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.stores
    ADD CONSTRAINT uq_stores_workspace_id_id UNIQUE (workspace_id, id);


--
-- Name: stores uq_stores_workspace_marketplace_seller; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.stores
    ADD CONSTRAINT uq_stores_workspace_marketplace_seller UNIQUE (workspace_id, marketplace, external_seller_id);


--
-- Name: sync_runs uq_sync_runs_task_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sync_runs
    ADD CONSTRAINT uq_sync_runs_task_id UNIQUE (task_id);


--
-- Name: sync_runs uq_sync_runs_tenant_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sync_runs
    ADD CONSTRAINT uq_sync_runs_tenant_id UNIQUE (workspace_id, store_id, id);


--
-- Name: users uq_users_email; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT uq_users_email UNIQUE (email);


--
-- Name: users uq_users_phone; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT uq_users_phone UNIQUE (phone);


--
-- Name: workspace_invites uq_workspace_invites_token_digest; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspace_invites
    ADD CONSTRAINT uq_workspace_invites_token_digest UNIQUE (token_digest);


--
-- Name: ix_access_tokens_expires_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_access_tokens_expires_at ON public.access_tokens USING btree (expires_at);


--
-- Name: ix_access_tokens_session_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_access_tokens_session_id ON public.access_tokens USING btree (session_id);


--
-- Name: ix_audit_events_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_audit_events_user_id ON public.audit_events USING btree (user_id);


--
-- Name: ix_audit_events_workspace_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_audit_events_workspace_id ON public.audit_events USING btree (workspace_id);


--
-- Name: ix_auth_sessions_expires_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_auth_sessions_expires_at ON public.auth_sessions USING btree (expires_at);


--
-- Name: ix_auth_sessions_revoked_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_auth_sessions_revoked_at ON public.auth_sessions USING btree (revoked_at);


--
-- Name: ix_auth_sessions_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_auth_sessions_user_id ON public.auth_sessions USING btree (user_id);


--
-- Name: ix_cost_imports_expires_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_cost_imports_expires_at ON public.cost_imports USING btree (expires_at);


--
-- Name: ix_insight_snapshots_computed_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_insight_snapshots_computed_at ON public.insight_snapshots USING btree (computed_at);


--
-- Name: ix_inventory_snapshots_day; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_inventory_snapshots_day ON public.inventory_snapshots USING btree (day);


--
-- Name: ix_marketplace_realizations_posting; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_marketplace_realizations_posting ON public.marketplace_realizations USING btree (workspace_id, store_id, posting_key);


--
-- Name: ix_notifications_active_incident; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_notifications_active_incident ON public.notifications USING btree (user_id, incident_key, resolved_at);


--
-- Name: ix_notifications_created_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_notifications_created_at ON public.notifications USING btree (created_at);


--
-- Name: ix_notifications_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_notifications_user_id ON public.notifications USING btree (user_id);


--
-- Name: ix_otp_challenges_destination_digest; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_otp_challenges_destination_digest ON public.otp_challenges USING btree (destination_digest);


--
-- Name: ix_otp_challenges_expires_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_otp_challenges_expires_at ON public.otp_challenges USING btree (expires_at);


--
-- Name: ix_otp_challenges_session_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_otp_challenges_session_id ON public.otp_challenges USING btree (session_id);


--
-- Name: ix_otp_challenges_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_otp_challenges_user_id ON public.otp_challenges USING btree (user_id);


--
-- Name: ix_ozon_analytics_due; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_ozon_analytics_due ON public.ozon_analytics_sync USING btree (next_attempt_at);


--
-- Name: ix_ozon_catalog_due; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_ozon_catalog_due ON public.ozon_catalog_sync USING btree (next_attempt_at);


--
-- Name: ix_push_devices_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_push_devices_user_id ON public.push_devices USING btree (user_id);


--
-- Name: ix_recovery_codes_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_recovery_codes_user_id ON public.recovery_codes USING btree (user_id);


--
-- Name: ix_refresh_tokens_session_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_refresh_tokens_session_id ON public.refresh_tokens USING btree (session_id);


--
-- Name: ix_store_events_day; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_store_events_day ON public.store_events USING btree (day);


--
-- Name: ix_stores_workspace_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_stores_workspace_id ON public.stores USING btree (workspace_id);


--
-- Name: ix_supply_destination_due; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_supply_destination_due ON public.supply_destination_sync USING btree (next_attempt_at);


--
-- Name: ix_supply_plans_store_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_supply_plans_store_id ON public.supply_plans USING btree (store_id);


--
-- Name: ix_supply_plans_workspace_updated; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_supply_plans_workspace_updated ON public.supply_plans USING btree (workspace_id, updated_at, id);


--
-- Name: ix_sync_runs_workspace_store_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_sync_runs_workspace_store_created ON public.sync_runs USING btree (workspace_id, store_id, created_at);


--
-- Name: ix_workspace_invites_workspace_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_workspace_invites_workspace_id ON public.workspace_invites USING btree (workspace_id);


--
-- Name: ix_workspaces_owner_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_workspaces_owner_user_id ON public.workspaces USING btree (owner_user_id);


--
-- Name: uq_sync_runs_active_funnel_summary; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_sync_runs_active_funnel_summary ON public.sync_runs USING btree (workspace_id, store_id, date_from, date_to) WHERE (((source)::text = 'funnel_summary'::text) AND ((status)::text = ANY (ARRAY[('queued'::character varying)::text, ('running'::character varying)::text])));


--
-- Name: uq_sync_runs_active_source; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_sync_runs_active_source ON public.sync_runs USING btree (workspace_id, store_id, source) WHERE (((status)::text = ANY (ARRAY[('queued'::character varying)::text, ('running'::character varying)::text])) AND ((source)::text = ANY (ARRAY[('catalog'::character varying)::text, ('sales'::character varying)::text, ('stocks'::character varying)::text, ('finance'::character varying)::text, ('orders'::character varying)::text, ('funnel'::character varying)::text, ('returns'::character varying)::text, ('balance'::character varying)::text, ('prices'::character varying)::text, ('fbs'::character varying)::text, ('stock_history'::character varying)::text, ('supply_demand'::character varying)::text, ('supplies'::character varying)::text, ('fbs_demand'::character varying)::text])));


--
-- Name: access_tokens fk_access_tokens_session_id_auth_sessions; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.access_tokens
    ADD CONSTRAINT fk_access_tokens_session_id_auth_sessions FOREIGN KEY (session_id) REFERENCES public.auth_sessions(id) ON DELETE CASCADE;


--
-- Name: auth_sessions fk_auth_sessions_user_id_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_sessions
    ADD CONSTRAINT fk_auth_sessions_user_id_users FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: catalog_import_previews fk_catalog_import_previews_created_by_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.catalog_import_previews
    ADD CONSTRAINT fk_catalog_import_previews_created_by_users FOREIGN KEY (created_by) REFERENCES public.users(id);


--
-- Name: catalog_import_previews fk_catalog_import_previews_workspace_id_stores; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.catalog_import_previews
    ADD CONSTRAINT fk_catalog_import_previews_workspace_id_stores FOREIGN KEY (workspace_id, store_id) REFERENCES public.stores(workspace_id, id) ON DELETE CASCADE;


--
-- Name: catalog_product_matches fk_catalog_matches_left_store; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.catalog_product_matches
    ADD CONSTRAINT fk_catalog_matches_left_store FOREIGN KEY (workspace_id, left_store_id) REFERENCES public.stores(workspace_id, id) ON DELETE CASCADE;


--
-- Name: catalog_product_matches fk_catalog_matches_right_store; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.catalog_product_matches
    ADD CONSTRAINT fk_catalog_matches_right_store FOREIGN KEY (workspace_id, right_store_id) REFERENCES public.stores(workspace_id, id) ON DELETE CASCADE;


--
-- Name: catalog_overrides fk_catalog_overrides_created_by_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.catalog_overrides
    ADD CONSTRAINT fk_catalog_overrides_created_by_users FOREIGN KEY (created_by) REFERENCES public.users(id);


--
-- Name: catalog_overrides fk_catalog_overrides_workspace_id_stores; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.catalog_overrides
    ADD CONSTRAINT fk_catalog_overrides_workspace_id_stores FOREIGN KEY (workspace_id, store_id) REFERENCES public.stores(workspace_id, id) ON DELETE CASCADE;


--
-- Name: catalog_product_matches fk_catalog_product_matches_created_by_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.catalog_product_matches
    ADD CONSTRAINT fk_catalog_product_matches_created_by_users FOREIGN KEY (created_by) REFERENCES public.users(id);


--
-- Name: cost_imports fk_cost_imports_created_by_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cost_imports
    ADD CONSTRAINT fk_cost_imports_created_by_users FOREIGN KEY (created_by) REFERENCES public.users(id);


--
-- Name: cost_imports fk_cost_imports_workspace_id_stores; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cost_imports
    ADD CONSTRAINT fk_cost_imports_workspace_id_stores FOREIGN KEY (workspace_id, store_id) REFERENCES public.stores(workspace_id, id) ON DELETE CASCADE;


--
-- Name: external_expenses fk_external_expenses_created_by_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.external_expenses
    ADD CONSTRAINT fk_external_expenses_created_by_users FOREIGN KEY (created_by) REFERENCES public.users(id);


--
-- Name: external_expenses fk_external_expenses_workspace_id_stores; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.external_expenses
    ADD CONSTRAINT fk_external_expenses_workspace_id_stores FOREIGN KEY (workspace_id, store_id) REFERENCES public.stores(workspace_id, id) ON DELETE CASCADE;


--
-- Name: finance_days fk_finance_days_workspace_id_stores; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_days
    ADD CONSTRAINT fk_finance_days_workspace_id_stores FOREIGN KEY (workspace_id, store_id) REFERENCES public.stores(workspace_id, id) ON DELETE CASCADE;


--
-- Name: finance_projections fk_finance_projections_workspace_id_stores; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_projections
    ADD CONSTRAINT fk_finance_projections_workspace_id_stores FOREIGN KEY (workspace_id, store_id) REFERENCES public.stores(workspace_id, id) ON DELETE CASCADE;


--
-- Name: import_issues fk_import_issues_workspace_id_stores; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.import_issues
    ADD CONSTRAINT fk_import_issues_workspace_id_stores FOREIGN KEY (workspace_id, store_id) REFERENCES public.stores(workspace_id, id) ON DELETE CASCADE;


--
-- Name: insight_snapshots fk_insight_snapshots_workspace_id_stores; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.insight_snapshots
    ADD CONSTRAINT fk_insight_snapshots_workspace_id_stores FOREIGN KEY (workspace_id, store_id) REFERENCES public.stores(workspace_id, id) ON DELETE CASCADE;


--
-- Name: inventory_settings fk_inventory_settings_updated_by_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.inventory_settings
    ADD CONSTRAINT fk_inventory_settings_updated_by_users FOREIGN KEY (updated_by) REFERENCES public.users(id);


--
-- Name: inventory_settings fk_inventory_settings_workspace_id_workspaces; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.inventory_settings
    ADD CONSTRAINT fk_inventory_settings_workspace_id_workspaces FOREIGN KEY (workspace_id) REFERENCES public.workspaces(id) ON DELETE CASCADE;


--
-- Name: inventory_snapshots fk_inventory_snapshots_workspace_id_stores; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.inventory_snapshots
    ADD CONSTRAINT fk_inventory_snapshots_workspace_id_stores FOREIGN KEY (workspace_id, store_id) REFERENCES public.stores(workspace_id, id) ON DELETE CASCADE;


--
-- Name: marketplace_catalog_snapshots fk_marketplace_catalog_snapshots_workspace_id_stores; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.marketplace_catalog_snapshots
    ADD CONSTRAINT fk_marketplace_catalog_snapshots_workspace_id_stores FOREIGN KEY (workspace_id, store_id) REFERENCES public.stores(workspace_id, id) ON DELETE CASCADE;


--
-- Name: marketplace_finance_days fk_marketplace_finance_days_workspace_id_stores; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.marketplace_finance_days
    ADD CONSTRAINT fk_marketplace_finance_days_workspace_id_stores FOREIGN KEY (workspace_id, store_id) REFERENCES public.stores(workspace_id, id) ON DELETE CASCADE;


--
-- Name: marketplace_realizations fk_marketplace_realizations_workspace_id_stores; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.marketplace_realizations
    ADD CONSTRAINT fk_marketplace_realizations_workspace_id_stores FOREIGN KEY (workspace_id, store_id) REFERENCES public.stores(workspace_id, id) ON DELETE CASCADE;


--
-- Name: marketplace_sales_days fk_marketplace_sales_days_workspace_id_stores; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.marketplace_sales_days
    ADD CONSTRAINT fk_marketplace_sales_days_workspace_id_stores FOREIGN KEY (workspace_id, store_id) REFERENCES public.stores(workspace_id, id) ON DELETE CASCADE;


--
-- Name: marketplace_stock_cover fk_marketplace_stock_cover_workspace_id_stores; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.marketplace_stock_cover
    ADD CONSTRAINT fk_marketplace_stock_cover_workspace_id_stores FOREIGN KEY (workspace_id, store_id) REFERENCES public.stores(workspace_id, id) ON DELETE CASCADE;


--
-- Name: marketplace_supply_snapshots fk_marketplace_supply_snapshots_workspace_id_stores; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.marketplace_supply_snapshots
    ADD CONSTRAINT fk_marketplace_supply_snapshots_workspace_id_stores FOREIGN KEY (workspace_id, store_id) REFERENCES public.stores(workspace_id, id) ON DELETE CASCADE;


--
-- Name: marketplace_traffic_days fk_marketplace_traffic_days_workspace_id_stores; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.marketplace_traffic_days
    ADD CONSTRAINT fk_marketplace_traffic_days_workspace_id_stores FOREIGN KEY (workspace_id, store_id) REFERENCES public.stores(workspace_id, id) ON DELETE CASCADE;


--
-- Name: marketplace_variant_costs fk_marketplace_variant_costs_created_by_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.marketplace_variant_costs
    ADD CONSTRAINT fk_marketplace_variant_costs_created_by_users FOREIGN KEY (created_by) REFERENCES public.users(id);


--
-- Name: marketplace_variant_costs fk_marketplace_variant_costs_workspace_id_stores; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.marketplace_variant_costs
    ADD CONSTRAINT fk_marketplace_variant_costs_workspace_id_stores FOREIGN KEY (workspace_id, store_id) REFERENCES public.stores(workspace_id, id) ON DELETE CASCADE;


--
-- Name: memberships fk_memberships_user_id_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.memberships
    ADD CONSTRAINT fk_memberships_user_id_users FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: memberships fk_memberships_workspace_id_workspaces; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.memberships
    ADD CONSTRAINT fk_memberships_workspace_id_workspaces FOREIGN KEY (workspace_id) REFERENCES public.workspaces(id) ON DELETE CASCADE;


--
-- Name: notification_settings fk_notification_settings_user_id_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notification_settings
    ADD CONSTRAINT fk_notification_settings_user_id_users FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: notifications fk_notifications_store_id_stores; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notifications
    ADD CONSTRAINT fk_notifications_store_id_stores FOREIGN KEY (store_id) REFERENCES public.stores(id) ON DELETE CASCADE;


--
-- Name: notifications fk_notifications_user_id_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notifications
    ADD CONSTRAINT fk_notifications_user_id_users FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: notifications fk_notifications_workspace_id_workspaces; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notifications
    ADD CONSTRAINT fk_notifications_workspace_id_workspaces FOREIGN KEY (workspace_id) REFERENCES public.workspaces(id) ON DELETE CASCADE;


--
-- Name: otp_challenges fk_otp_challenges_session_id_auth_sessions; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.otp_challenges
    ADD CONSTRAINT fk_otp_challenges_session_id_auth_sessions FOREIGN KEY (session_id) REFERENCES public.auth_sessions(id) ON DELETE CASCADE;


--
-- Name: otp_challenges fk_otp_challenges_user_id_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.otp_challenges
    ADD CONSTRAINT fk_otp_challenges_user_id_users FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: ozon_analytics_sync fk_ozon_analytics_sync_requested_by_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ozon_analytics_sync
    ADD CONSTRAINT fk_ozon_analytics_sync_requested_by_users FOREIGN KEY (requested_by) REFERENCES public.users(id);


--
-- Name: ozon_analytics_sync fk_ozon_analytics_sync_workspace_id_stores; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ozon_analytics_sync
    ADD CONSTRAINT fk_ozon_analytics_sync_workspace_id_stores FOREIGN KEY (workspace_id, store_id) REFERENCES public.stores(workspace_id, id) ON DELETE CASCADE;


--
-- Name: ozon_catalog_sync fk_ozon_catalog_sync_requested_by_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ozon_catalog_sync
    ADD CONSTRAINT fk_ozon_catalog_sync_requested_by_users FOREIGN KEY (requested_by) REFERENCES public.users(id);


--
-- Name: ozon_catalog_sync fk_ozon_catalog_sync_workspace_id_stores; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ozon_catalog_sync
    ADD CONSTRAINT fk_ozon_catalog_sync_workspace_id_stores FOREIGN KEY (workspace_id, store_id) REFERENCES public.stores(workspace_id, id) ON DELETE CASCADE;


--
-- Name: product_costs fk_product_costs_created_by_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.product_costs
    ADD CONSTRAINT fk_product_costs_created_by_users FOREIGN KEY (created_by) REFERENCES public.users(id);


--
-- Name: product_costs fk_product_costs_workspace_id_stores; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.product_costs
    ADD CONSTRAINT fk_product_costs_workspace_id_stores FOREIGN KEY (workspace_id, store_id) REFERENCES public.stores(workspace_id, id) ON DELETE CASCADE;


--
-- Name: push_devices fk_push_devices_session_id_auth_sessions; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.push_devices
    ADD CONSTRAINT fk_push_devices_session_id_auth_sessions FOREIGN KEY (session_id) REFERENCES public.auth_sessions(id) ON DELETE CASCADE;


--
-- Name: push_devices fk_push_devices_user_id_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.push_devices
    ADD CONSTRAINT fk_push_devices_user_id_users FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: recovery_codes fk_recovery_codes_user_id_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.recovery_codes
    ADD CONSTRAINT fk_recovery_codes_user_id_users FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: refresh_tokens fk_refresh_tokens_session_id_auth_sessions; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.refresh_tokens
    ADD CONSTRAINT fk_refresh_tokens_session_id_auth_sessions FOREIGN KEY (session_id) REFERENCES public.auth_sessions(id) ON DELETE CASCADE;


--
-- Name: store_credentials fk_store_credentials_workspace_id_stores; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_credentials
    ADD CONSTRAINT fk_store_credentials_workspace_id_stores FOREIGN KEY (workspace_id, store_id) REFERENCES public.stores(workspace_id, id) ON DELETE CASCADE;


--
-- Name: store_events fk_store_events_created_by_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_events
    ADD CONSTRAINT fk_store_events_created_by_users FOREIGN KEY (created_by) REFERENCES public.users(id);


--
-- Name: store_events fk_store_events_workspace_id_stores; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_events
    ADD CONSTRAINT fk_store_events_workspace_id_stores FOREIGN KEY (workspace_id, store_id) REFERENCES public.stores(workspace_id, id) ON DELETE CASCADE;


--
-- Name: store_goals fk_store_goals_created_by_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_goals
    ADD CONSTRAINT fk_store_goals_created_by_users FOREIGN KEY (created_by) REFERENCES public.users(id);


--
-- Name: store_goals fk_store_goals_workspace_id_stores; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_goals
    ADD CONSTRAINT fk_store_goals_workspace_id_stores FOREIGN KEY (workspace_id, store_id) REFERENCES public.stores(workspace_id, id) ON DELETE CASCADE;


--
-- Name: stores fk_stores_workspace_id_workspaces; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.stores
    ADD CONSTRAINT fk_stores_workspace_id_workspaces FOREIGN KEY (workspace_id) REFERENCES public.workspaces(id) ON DELETE CASCADE;


--
-- Name: supply_destination_snapshots fk_supply_destination_snapshots_workspace_id_stores; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.supply_destination_snapshots
    ADD CONSTRAINT fk_supply_destination_snapshots_workspace_id_stores FOREIGN KEY (workspace_id, store_id) REFERENCES public.stores(workspace_id, id) ON DELETE CASCADE;


--
-- Name: supply_destination_sync fk_supply_destination_sync_requested_by_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.supply_destination_sync
    ADD CONSTRAINT fk_supply_destination_sync_requested_by_users FOREIGN KEY (requested_by) REFERENCES public.users(id);


--
-- Name: supply_destination_sync fk_supply_destination_sync_workspace_id_stores; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.supply_destination_sync
    ADD CONSTRAINT fk_supply_destination_sync_workspace_id_stores FOREIGN KEY (workspace_id, store_id) REFERENCES public.stores(workspace_id, id) ON DELETE CASCADE;


--
-- Name: supply_packaging fk_supply_packaging_updated_by_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.supply_packaging
    ADD CONSTRAINT fk_supply_packaging_updated_by_users FOREIGN KEY (updated_by) REFERENCES public.users(id);


--
-- Name: supply_packaging fk_supply_packaging_workspace_id_stores; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.supply_packaging
    ADD CONSTRAINT fk_supply_packaging_workspace_id_stores FOREIGN KEY (workspace_id, store_id) REFERENCES public.stores(workspace_id, id) ON DELETE CASCADE;


--
-- Name: supply_plans fk_supply_plans_created_by_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.supply_plans
    ADD CONSTRAINT fk_supply_plans_created_by_users FOREIGN KEY (created_by) REFERENCES public.users(id);


--
-- Name: supply_plans fk_supply_plans_updated_by_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.supply_plans
    ADD CONSTRAINT fk_supply_plans_updated_by_users FOREIGN KEY (updated_by) REFERENCES public.users(id);


--
-- Name: supply_plans fk_supply_plans_workspace_id_stores; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.supply_plans
    ADD CONSTRAINT fk_supply_plans_workspace_id_stores FOREIGN KEY (workspace_id, store_id) REFERENCES public.stores(workspace_id, id) ON DELETE CASCADE;


--
-- Name: sync_runs fk_sync_runs_requested_by_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sync_runs
    ADD CONSTRAINT fk_sync_runs_requested_by_users FOREIGN KEY (requested_by) REFERENCES public.users(id);


--
-- Name: sync_runs fk_sync_runs_workspace_store; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sync_runs
    ADD CONSTRAINT fk_sync_runs_workspace_store FOREIGN KEY (workspace_id, store_id) REFERENCES public.stores(workspace_id, id) ON DELETE CASCADE;


--
-- Name: sync_schedules fk_sync_schedules_requested_by_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sync_schedules
    ADD CONSTRAINT fk_sync_schedules_requested_by_users FOREIGN KEY (requested_by) REFERENCES public.users(id);


--
-- Name: sync_schedules fk_sync_schedules_workspace_id_stores; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sync_schedules
    ADD CONSTRAINT fk_sync_schedules_workspace_id_stores FOREIGN KEY (workspace_id, store_id) REFERENCES public.stores(workspace_id, id) ON DELETE CASCADE;


--
-- Name: tax_settings fk_tax_settings_created_by_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tax_settings
    ADD CONSTRAINT fk_tax_settings_created_by_users FOREIGN KEY (created_by) REFERENCES public.users(id);


--
-- Name: tax_settings fk_tax_settings_workspace_id_stores; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tax_settings
    ADD CONSTRAINT fk_tax_settings_workspace_id_stores FOREIGN KEY (workspace_id, store_id) REFERENCES public.stores(workspace_id, id) ON DELETE CASCADE;


--
-- Name: wb_daily_metrics fk_wb_daily_metrics_workspace_id_stores; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.wb_daily_metrics
    ADD CONSTRAINT fk_wb_daily_metrics_workspace_id_stores FOREIGN KEY (workspace_id, store_id) REFERENCES public.stores(workspace_id, id) ON DELETE CASCADE;


--
-- Name: wb_metric_versions fk_wb_metric_versions_workspace_id_stores; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.wb_metric_versions
    ADD CONSTRAINT fk_wb_metric_versions_workspace_id_stores FOREIGN KEY (workspace_id, store_id) REFERENCES public.stores(workspace_id, id) ON DELETE CASCADE;


--
-- Name: wb_records fk_wb_records_workspace_id_stores; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.wb_records
    ADD CONSTRAINT fk_wb_records_workspace_id_stores FOREIGN KEY (workspace_id, store_id) REFERENCES public.stores(workspace_id, id) ON DELETE CASCADE;


--
-- Name: wb_staged_records fk_wb_staged_records_workspace_id_sync_runs; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.wb_staged_records
    ADD CONSTRAINT fk_wb_staged_records_workspace_id_sync_runs FOREIGN KEY (workspace_id, store_id, run_id) REFERENCES public.sync_runs(workspace_id, store_id, id) ON DELETE CASCADE;


--
-- Name: workspace_invites fk_workspace_invites_accepted_by_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspace_invites
    ADD CONSTRAINT fk_workspace_invites_accepted_by_users FOREIGN KEY (accepted_by) REFERENCES public.users(id);


--
-- Name: workspace_invites fk_workspace_invites_invited_by_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspace_invites
    ADD CONSTRAINT fk_workspace_invites_invited_by_users FOREIGN KEY (invited_by) REFERENCES public.users(id);


--
-- Name: workspace_invites fk_workspace_invites_workspace_id_workspaces; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspace_invites
    ADD CONSTRAINT fk_workspace_invites_workspace_id_workspaces FOREIGN KEY (workspace_id) REFERENCES public.workspaces(id) ON DELETE CASCADE;


--
-- Name: workspaces fk_workspaces_owner_user_id_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspaces
    ADD CONSTRAINT fk_workspaces_owner_user_id_users FOREIGN KEY (owner_user_id) REFERENCES public.users(id);


--
-- Name: audit_events; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.audit_events ENABLE ROW LEVEL SECURITY;

--
-- Name: catalog_import_previews; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.catalog_import_previews ENABLE ROW LEVEL SECURITY;

--
-- Name: catalog_overrides; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.catalog_overrides ENABLE ROW LEVEL SECURITY;

--
-- Name: catalog_product_matches; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.catalog_product_matches ENABLE ROW LEVEL SECURITY;

--
-- Name: cost_imports; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.cost_imports ENABLE ROW LEVEL SECURITY;

--
-- Name: external_expenses; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.external_expenses ENABLE ROW LEVEL SECURITY;

--
-- Name: finance_days; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.finance_days ENABLE ROW LEVEL SECURITY;

--
-- Name: finance_projections; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.finance_projections ENABLE ROW LEVEL SECURITY;

--
-- Name: import_issues; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.import_issues ENABLE ROW LEVEL SECURITY;

--
-- Name: insight_snapshots; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.insight_snapshots ENABLE ROW LEVEL SECURITY;

--
-- Name: inventory_settings; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.inventory_settings ENABLE ROW LEVEL SECURITY;

--
-- Name: inventory_snapshots; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.inventory_snapshots ENABLE ROW LEVEL SECURITY;

--
-- Name: marketplace_catalog_snapshots; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.marketplace_catalog_snapshots ENABLE ROW LEVEL SECURITY;

--
-- Name: marketplace_finance_days; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.marketplace_finance_days ENABLE ROW LEVEL SECURITY;

--
-- Name: marketplace_realizations; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.marketplace_realizations ENABLE ROW LEVEL SECURITY;

--
-- Name: marketplace_sales_days; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.marketplace_sales_days ENABLE ROW LEVEL SECURITY;

--
-- Name: marketplace_stock_cover; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.marketplace_stock_cover ENABLE ROW LEVEL SECURITY;

--
-- Name: marketplace_supply_snapshots; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.marketplace_supply_snapshots ENABLE ROW LEVEL SECURITY;

--
-- Name: marketplace_traffic_days; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.marketplace_traffic_days ENABLE ROW LEVEL SECURITY;

--
-- Name: marketplace_variant_costs; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.marketplace_variant_costs ENABLE ROW LEVEL SECURITY;

--
-- Name: memberships; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.memberships ENABLE ROW LEVEL SECURITY;

--
-- Name: notifications; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.notifications ENABLE ROW LEVEL SECURITY;

--
-- Name: notifications own_notification; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY own_notification ON public.notifications USING ((user_id = public.perk_actor())) WITH CHECK ((user_id = public.perk_actor()));


--
-- Name: ozon_analytics_sync; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.ozon_analytics_sync ENABLE ROW LEVEL SECURITY;

--
-- Name: ozon_catalog_sync; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.ozon_catalog_sync ENABLE ROW LEVEL SECURITY;

--
-- Name: product_costs; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.product_costs ENABLE ROW LEVEL SECURITY;

--
-- Name: import_issues scoped_issue; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY scoped_issue ON public.import_issues USING ((public.perk_store_access(workspace_id, store_id) AND public.perk_is_member(workspace_id, 'owner'::text))) WITH CHECK ((public.perk_store_access(workspace_id, store_id) AND public.perk_is_member(workspace_id, 'owner'::text)));


--
-- Name: store_credentials; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.store_credentials ENABLE ROW LEVEL SECURITY;

--
-- Name: store_events; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.store_events ENABLE ROW LEVEL SECURITY;

--
-- Name: store_goals; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.store_goals ENABLE ROW LEVEL SECURITY;

--
-- Name: stores; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.stores ENABLE ROW LEVEL SECURITY;

--
-- Name: supply_destination_snapshots; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.supply_destination_snapshots ENABLE ROW LEVEL SECURITY;

--
-- Name: supply_destination_sync; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.supply_destination_sync ENABLE ROW LEVEL SECURITY;

--
-- Name: supply_packaging; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.supply_packaging ENABLE ROW LEVEL SECURITY;

--
-- Name: supply_plans; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.supply_plans ENABLE ROW LEVEL SECURITY;

--
-- Name: sync_runs; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.sync_runs ENABLE ROW LEVEL SECURITY;

--
-- Name: sync_schedules; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.sync_schedules ENABLE ROW LEVEL SECURITY;

--
-- Name: tax_settings; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.tax_settings ENABLE ROW LEVEL SECURITY;

--
-- Name: audit_events tenant_delete; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_delete ON public.audit_events FOR DELETE USING (false);


--
-- Name: catalog_import_previews tenant_delete; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_delete ON public.catalog_import_previews FOR DELETE USING ((public.perk_store_access(workspace_id, store_id) AND (created_by = public.perk_actor()) AND public.perk_is_member(workspace_id, 'owner'::text)));


--
-- Name: catalog_overrides tenant_delete; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_delete ON public.catalog_overrides FOR DELETE USING ((public.perk_store_access(workspace_id, store_id) AND public.perk_is_member(workspace_id, 'owner'::text)));


--
-- Name: catalog_product_matches tenant_delete; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_delete ON public.catalog_product_matches FOR DELETE USING ((public.perk_store_access(workspace_id, left_store_id) AND public.perk_store_access(workspace_id, right_store_id) AND public.perk_is_member(workspace_id, 'owner'::text)));


--
-- Name: cost_imports tenant_delete; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_delete ON public.cost_imports FOR DELETE USING ((public.perk_store_access(workspace_id, store_id) AND public.perk_permission(workspace_id, 'costs.write'::text)));


--
-- Name: finance_days tenant_delete; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_delete ON public.finance_days FOR DELETE USING ((public.perk_store_access(workspace_id, store_id) AND public.perk_is_member(workspace_id, 'owner'::text)));


--
-- Name: finance_projections tenant_delete; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_delete ON public.finance_projections FOR DELETE USING ((public.perk_store_access(workspace_id, store_id) AND public.perk_is_member(workspace_id, 'owner'::text)));


--
-- Name: insight_snapshots tenant_delete; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_delete ON public.insight_snapshots FOR DELETE USING (public.perk_store_access(workspace_id, store_id));


--
-- Name: inventory_snapshots tenant_delete; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_delete ON public.inventory_snapshots FOR DELETE USING ((public.perk_store_access(workspace_id, store_id) AND public.perk_is_member(workspace_id, 'owner'::text)));


--
-- Name: marketplace_finance_days tenant_delete; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_delete ON public.marketplace_finance_days FOR DELETE USING ((public.perk_store_access(workspace_id, store_id) AND public.perk_is_member(workspace_id, 'owner'::text)));


--
-- Name: marketplace_realizations tenant_delete; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_delete ON public.marketplace_realizations FOR DELETE USING ((public.perk_store_access(workspace_id, store_id) AND public.perk_is_member(workspace_id, 'owner'::text)));


--
-- Name: marketplace_supply_snapshots tenant_delete; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_delete ON public.marketplace_supply_snapshots FOR DELETE USING ((public.perk_store_access(workspace_id, store_id) AND public.perk_is_member(workspace_id, 'owner'::text)));


--
-- Name: marketplace_traffic_days tenant_delete; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_delete ON public.marketplace_traffic_days FOR DELETE USING ((public.perk_store_access(workspace_id, store_id) AND public.perk_is_member(workspace_id, 'owner'::text)));


--
-- Name: memberships tenant_delete; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_delete ON public.memberships FOR DELETE USING (((public.perk_is_member(workspace_id, 'owner'::text) OR (user_id = public.perk_actor())) AND (NOT public.perk_is_creator(workspace_id, user_id))));


--
-- Name: store_credentials tenant_delete; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_delete ON public.store_credentials FOR DELETE USING ((public.perk_store_access(workspace_id, store_id) AND public.perk_is_member(workspace_id, 'owner'::text)));


--
-- Name: store_events tenant_delete; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_delete ON public.store_events FOR DELETE USING ((public.perk_store_access(workspace_id, store_id) AND public.perk_is_member(workspace_id, 'owner'::text)));


--
-- Name: store_goals tenant_delete; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_delete ON public.store_goals FOR DELETE USING ((public.perk_store_access(workspace_id, store_id) AND public.perk_is_member(workspace_id, 'owner'::text)));


--
-- Name: stores tenant_delete; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_delete ON public.stores FOR DELETE USING (public.perk_is_member(workspace_id, 'owner'::text));


--
-- Name: supply_packaging tenant_delete; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_delete ON public.supply_packaging FOR DELETE USING ((public.perk_store_access(workspace_id, store_id) AND public.perk_is_member(workspace_id, 'owner'::text)));


--
-- Name: supply_plans tenant_delete; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_delete ON public.supply_plans FOR DELETE USING ((public.perk_store_access(workspace_id, store_id) AND public.perk_is_member(workspace_id, 'owner'::text)));


--
-- Name: sync_schedules tenant_delete; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_delete ON public.sync_schedules FOR DELETE USING ((public.perk_store_access(workspace_id, store_id) AND public.perk_is_member(workspace_id, 'owner'::text)));


--
-- Name: tax_settings tenant_delete; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_delete ON public.tax_settings FOR DELETE USING ((public.perk_store_access(workspace_id, store_id) AND public.perk_permission(workspace_id, 'taxes.write'::text)));


--
-- Name: wb_daily_metrics tenant_delete; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_delete ON public.wb_daily_metrics FOR DELETE USING ((public.perk_store_access(workspace_id, store_id) AND public.perk_is_member(workspace_id, 'owner'::text)));


--
-- Name: wb_metric_versions tenant_delete; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_delete ON public.wb_metric_versions FOR DELETE USING ((public.perk_store_access(workspace_id, store_id) AND public.perk_is_member(workspace_id, 'owner'::text)));


--
-- Name: wb_records tenant_delete; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_delete ON public.wb_records FOR DELETE USING ((public.perk_store_access(workspace_id, store_id) AND public.perk_is_member(workspace_id, 'owner'::text)));


--
-- Name: wb_staged_records tenant_delete; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_delete ON public.wb_staged_records FOR DELETE USING ((public.perk_store_access(workspace_id, store_id) AND public.perk_is_member(workspace_id, 'owner'::text)));


--
-- Name: workspace_invites tenant_delete; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_delete ON public.workspace_invites FOR DELETE USING (public.perk_is_member(workspace_id, 'owner'::text));


--
-- Name: workspaces tenant_delete; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_delete ON public.workspaces FOR DELETE USING (public.perk_is_member(id, 'owner'::text));


--
-- Name: audit_events tenant_insert; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_insert ON public.audit_events FOR INSERT WITH CHECK (((workspace_id IS NULL) OR (user_id = public.perk_actor())));


--
-- Name: catalog_import_previews tenant_insert; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_insert ON public.catalog_import_previews FOR INSERT WITH CHECK ((public.perk_store_access(workspace_id, store_id) AND (created_by = public.perk_actor()) AND public.perk_is_member(workspace_id, 'owner'::text)));


--
-- Name: catalog_overrides tenant_insert; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_insert ON public.catalog_overrides FOR INSERT WITH CHECK ((public.perk_store_access(workspace_id, store_id) AND public.perk_is_member(workspace_id, 'owner'::text)));


--
-- Name: catalog_product_matches tenant_insert; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_insert ON public.catalog_product_matches FOR INSERT WITH CHECK ((public.perk_store_access(workspace_id, left_store_id) AND public.perk_store_access(workspace_id, right_store_id) AND public.perk_is_member(workspace_id, 'owner'::text)));


--
-- Name: cost_imports tenant_insert; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_insert ON public.cost_imports FOR INSERT WITH CHECK ((public.perk_store_access(workspace_id, store_id) AND public.perk_permission(workspace_id, 'costs.write'::text)));


--
-- Name: external_expenses tenant_insert; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_insert ON public.external_expenses FOR INSERT WITH CHECK ((public.perk_store_access(workspace_id, store_id) AND public.perk_permission(workspace_id, 'expenses.write'::text)));


--
-- Name: finance_days tenant_insert; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_insert ON public.finance_days FOR INSERT WITH CHECK ((public.perk_store_access(workspace_id, store_id) AND public.perk_is_member(workspace_id, 'owner'::text)));


--
-- Name: finance_projections tenant_insert; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_insert ON public.finance_projections FOR INSERT WITH CHECK ((public.perk_store_access(workspace_id, store_id) AND public.perk_is_member(workspace_id, 'owner'::text)));


--
-- Name: insight_snapshots tenant_insert; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_insert ON public.insight_snapshots FOR INSERT WITH CHECK (public.perk_store_access(workspace_id, store_id));


--
-- Name: inventory_settings tenant_insert; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_insert ON public.inventory_settings FOR INSERT WITH CHECK (public.perk_is_member(workspace_id, 'owner'::text));


--
-- Name: inventory_snapshots tenant_insert; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_insert ON public.inventory_snapshots FOR INSERT WITH CHECK ((public.perk_store_access(workspace_id, store_id) AND public.perk_is_member(workspace_id, 'owner'::text)));


--
-- Name: marketplace_catalog_snapshots tenant_insert; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_insert ON public.marketplace_catalog_snapshots FOR INSERT WITH CHECK ((public.perk_store_access(workspace_id, store_id) AND public.perk_is_member(workspace_id, 'owner'::text)));


--
-- Name: marketplace_finance_days tenant_insert; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_insert ON public.marketplace_finance_days FOR INSERT WITH CHECK ((public.perk_store_access(workspace_id, store_id) AND public.perk_is_member(workspace_id, 'owner'::text)));


--
-- Name: marketplace_realizations tenant_insert; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_insert ON public.marketplace_realizations FOR INSERT WITH CHECK ((public.perk_store_access(workspace_id, store_id) AND public.perk_is_member(workspace_id, 'owner'::text)));


--
-- Name: marketplace_sales_days tenant_insert; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_insert ON public.marketplace_sales_days FOR INSERT WITH CHECK ((public.perk_store_access(workspace_id, store_id) AND public.perk_is_member(workspace_id, 'owner'::text)));


--
-- Name: marketplace_stock_cover tenant_insert; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_insert ON public.marketplace_stock_cover FOR INSERT WITH CHECK ((public.perk_store_access(workspace_id, store_id) AND public.perk_is_member(workspace_id, 'owner'::text)));


--
-- Name: marketplace_supply_snapshots tenant_insert; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_insert ON public.marketplace_supply_snapshots FOR INSERT WITH CHECK ((public.perk_store_access(workspace_id, store_id) AND public.perk_is_member(workspace_id, 'owner'::text)));


--
-- Name: marketplace_traffic_days tenant_insert; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_insert ON public.marketplace_traffic_days FOR INSERT WITH CHECK ((public.perk_store_access(workspace_id, store_id) AND public.perk_is_member(workspace_id, 'owner'::text)));


--
-- Name: marketplace_variant_costs tenant_insert; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_insert ON public.marketplace_variant_costs FOR INSERT WITH CHECK ((public.perk_store_access(workspace_id, store_id) AND public.perk_permission(workspace_id, 'costs.write'::text)));


--
-- Name: memberships tenant_insert; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_insert ON public.memberships FOR INSERT WITH CHECK ((public.perk_is_member(workspace_id, 'owner'::text) OR ((user_id = public.perk_actor()) AND ((role)::text = 'owner'::text) AND public.perk_created_workspace(workspace_id))));


--
-- Name: product_costs tenant_insert; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_insert ON public.product_costs FOR INSERT WITH CHECK ((public.perk_store_access(workspace_id, store_id) AND public.perk_permission(workspace_id, 'costs.write'::text)));


--
-- Name: store_credentials tenant_insert; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_insert ON public.store_credentials FOR INSERT WITH CHECK ((public.perk_store_access(workspace_id, store_id) AND public.perk_is_member(workspace_id, 'owner'::text)));


--
-- Name: store_events tenant_insert; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_insert ON public.store_events FOR INSERT WITH CHECK ((public.perk_store_access(workspace_id, store_id) AND public.perk_is_member(workspace_id, 'owner'::text)));


--
-- Name: store_goals tenant_insert; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_insert ON public.store_goals FOR INSERT WITH CHECK ((public.perk_store_access(workspace_id, store_id) AND public.perk_is_member(workspace_id, 'owner'::text)));


--
-- Name: stores tenant_insert; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_insert ON public.stores FOR INSERT WITH CHECK (public.perk_is_member(workspace_id, 'owner'::text));


--
-- Name: supply_destination_snapshots tenant_insert; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_insert ON public.supply_destination_snapshots FOR INSERT WITH CHECK ((public.perk_store_access(workspace_id, store_id) AND public.perk_is_member(workspace_id, 'owner'::text)));


--
-- Name: supply_packaging tenant_insert; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_insert ON public.supply_packaging FOR INSERT WITH CHECK ((public.perk_store_access(workspace_id, store_id) AND public.perk_is_member(workspace_id, 'owner'::text)));


--
-- Name: supply_plans tenant_insert; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_insert ON public.supply_plans FOR INSERT WITH CHECK ((public.perk_store_access(workspace_id, store_id) AND public.perk_is_member(workspace_id, 'owner'::text)));


--
-- Name: sync_schedules tenant_insert; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_insert ON public.sync_schedules FOR INSERT WITH CHECK ((public.perk_store_access(workspace_id, store_id) AND public.perk_is_member(workspace_id, 'owner'::text)));


--
-- Name: tax_settings tenant_insert; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_insert ON public.tax_settings FOR INSERT WITH CHECK ((public.perk_store_access(workspace_id, store_id) AND public.perk_permission(workspace_id, 'taxes.write'::text)));


--
-- Name: wb_daily_metrics tenant_insert; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_insert ON public.wb_daily_metrics FOR INSERT WITH CHECK ((public.perk_store_access(workspace_id, store_id) AND public.perk_is_member(workspace_id, 'owner'::text)));


--
-- Name: wb_metric_versions tenant_insert; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_insert ON public.wb_metric_versions FOR INSERT WITH CHECK ((public.perk_store_access(workspace_id, store_id) AND public.perk_is_member(workspace_id, 'owner'::text)));


--
-- Name: wb_records tenant_insert; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_insert ON public.wb_records FOR INSERT WITH CHECK ((public.perk_store_access(workspace_id, store_id) AND public.perk_is_member(workspace_id, 'owner'::text)));


--
-- Name: wb_staged_records tenant_insert; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_insert ON public.wb_staged_records FOR INSERT WITH CHECK ((public.perk_store_access(workspace_id, store_id) AND public.perk_is_member(workspace_id, 'owner'::text)));


--
-- Name: workspace_invites tenant_insert; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_insert ON public.workspace_invites FOR INSERT WITH CHECK (public.perk_is_member(workspace_id, 'owner'::text));


--
-- Name: workspaces tenant_insert; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_insert ON public.workspaces FOR INSERT WITH CHECK ((owner_user_id = public.perk_actor()));


--
-- Name: audit_events tenant_read; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_read ON public.audit_events FOR SELECT USING ((((workspace_id IS NULL) AND (user_id = public.perk_actor())) OR public.perk_is_member(workspace_id, 'owner'::text)));


--
-- Name: catalog_import_previews tenant_read; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_read ON public.catalog_import_previews FOR SELECT USING ((public.perk_store_access(workspace_id, store_id) AND (created_by = public.perk_actor()) AND public.perk_is_member(workspace_id, 'owner'::text)));


--
-- Name: catalog_overrides tenant_read; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_read ON public.catalog_overrides FOR SELECT USING ((public.perk_store_access(workspace_id, store_id) AND (public.perk_permission(workspace_id, 'inventory.read'::text) OR public.perk_permission(workspace_id, 'profit.read'::text))));


--
-- Name: catalog_product_matches tenant_read; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_read ON public.catalog_product_matches FOR SELECT USING ((public.perk_store_access(workspace_id, left_store_id) AND public.perk_store_access(workspace_id, right_store_id) AND public.perk_is_member(workspace_id, 'owner'::text)));


--
-- Name: cost_imports tenant_read; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_read ON public.cost_imports FOR SELECT USING (public.perk_store_access(workspace_id, store_id));


--
-- Name: external_expenses tenant_read; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_read ON public.external_expenses FOR SELECT USING (public.perk_store_access(workspace_id, store_id));


--
-- Name: finance_days tenant_read; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_read ON public.finance_days FOR SELECT USING (public.perk_store_access(workspace_id, store_id));


--
-- Name: finance_projections tenant_read; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_read ON public.finance_projections FOR SELECT USING (public.perk_store_access(workspace_id, store_id));


--
-- Name: insight_snapshots tenant_read; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_read ON public.insight_snapshots FOR SELECT USING (public.perk_store_access(workspace_id, store_id));


--
-- Name: inventory_settings tenant_read; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_read ON public.inventory_settings FOR SELECT USING (public.perk_permission(workspace_id, 'inventory.read'::text));


--
-- Name: inventory_snapshots tenant_read; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_read ON public.inventory_snapshots FOR SELECT USING (public.perk_store_access(workspace_id, store_id));


--
-- Name: marketplace_catalog_snapshots tenant_read; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_read ON public.marketplace_catalog_snapshots FOR SELECT USING ((public.perk_store_access(workspace_id, store_id) AND (public.perk_permission(workspace_id, 'inventory.read'::text) OR public.perk_permission(workspace_id, 'profit.read'::text) OR public.perk_permission(workspace_id, 'costs.write'::text))));


--
-- Name: marketplace_finance_days tenant_read; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_read ON public.marketplace_finance_days FOR SELECT USING ((public.perk_store_access(workspace_id, store_id) AND public.perk_permission(workspace_id, 'finance.read'::text)));


--
-- Name: marketplace_realizations tenant_read; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_read ON public.marketplace_realizations FOR SELECT USING ((public.perk_store_access(workspace_id, store_id) AND (public.perk_permission(workspace_id, 'analytics.read'::text) OR public.perk_permission(workspace_id, 'profit.read'::text))));


--
-- Name: marketplace_sales_days tenant_read; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_read ON public.marketplace_sales_days FOR SELECT USING ((public.perk_store_access(workspace_id, store_id) AND public.perk_permission(workspace_id, 'analytics.read'::text)));


--
-- Name: marketplace_stock_cover tenant_read; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_read ON public.marketplace_stock_cover FOR SELECT USING ((public.perk_store_access(workspace_id, store_id) AND public.perk_permission(workspace_id, 'inventory.read'::text)));


--
-- Name: marketplace_supply_snapshots tenant_read; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_read ON public.marketplace_supply_snapshots FOR SELECT USING ((public.perk_store_access(workspace_id, store_id) AND public.perk_permission(workspace_id, 'inventory.read'::text)));


--
-- Name: marketplace_traffic_days tenant_read; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_read ON public.marketplace_traffic_days FOR SELECT USING ((public.perk_store_access(workspace_id, store_id) AND public.perk_permission(workspace_id, 'analytics.read'::text)));


--
-- Name: marketplace_variant_costs tenant_read; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_read ON public.marketplace_variant_costs FOR SELECT USING ((public.perk_store_access(workspace_id, store_id) AND (public.perk_permission(workspace_id, 'profit.read'::text) OR public.perk_permission(workspace_id, 'costs.write'::text))));


--
-- Name: memberships tenant_read; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_read ON public.memberships FOR SELECT USING (((user_id = public.perk_actor()) OR public.perk_is_member(workspace_id, 'owner'::text)));


--
-- Name: ozon_analytics_sync tenant_read; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_read ON public.ozon_analytics_sync FOR SELECT USING (public.perk_store_access(workspace_id, store_id));


--
-- Name: ozon_catalog_sync tenant_read; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_read ON public.ozon_catalog_sync FOR SELECT USING (public.perk_store_access(workspace_id, store_id));


--
-- Name: product_costs tenant_read; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_read ON public.product_costs FOR SELECT USING (public.perk_store_access(workspace_id, store_id));


--
-- Name: store_credentials tenant_read; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_read ON public.store_credentials FOR SELECT USING ((public.perk_store_access(workspace_id, store_id) AND public.perk_is_member(workspace_id, 'owner'::text)));


--
-- Name: store_events tenant_read; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_read ON public.store_events FOR SELECT USING (public.perk_store_access(workspace_id, store_id));


--
-- Name: store_goals tenant_read; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_read ON public.store_goals FOR SELECT USING (public.perk_store_access(workspace_id, store_id));


--
-- Name: stores tenant_read; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_read ON public.stores FOR SELECT USING (public.perk_store_access(workspace_id, id));


--
-- Name: supply_destination_snapshots tenant_read; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_read ON public.supply_destination_snapshots FOR SELECT USING ((public.perk_store_access(workspace_id, store_id) AND public.perk_permission(workspace_id, 'inventory.read'::text)));


--
-- Name: supply_destination_sync tenant_read; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_read ON public.supply_destination_sync FOR SELECT USING (public.perk_store_access(workspace_id, store_id));


--
-- Name: supply_packaging tenant_read; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_read ON public.supply_packaging FOR SELECT USING ((public.perk_store_access(workspace_id, store_id) AND public.perk_permission(workspace_id, 'inventory.read'::text)));


--
-- Name: supply_plans tenant_read; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_read ON public.supply_plans FOR SELECT USING ((public.perk_store_access(workspace_id, store_id) AND public.perk_permission(workspace_id, 'inventory.read'::text)));


--
-- Name: sync_runs tenant_read; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_read ON public.sync_runs FOR SELECT USING (public.perk_store_access(workspace_id, store_id));


--
-- Name: sync_schedules tenant_read; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_read ON public.sync_schedules FOR SELECT USING (public.perk_store_access(workspace_id, store_id));


--
-- Name: tax_settings tenant_read; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_read ON public.tax_settings FOR SELECT USING (public.perk_store_access(workspace_id, store_id));


--
-- Name: wb_daily_metrics tenant_read; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_read ON public.wb_daily_metrics FOR SELECT USING (public.perk_store_access(workspace_id, store_id));


--
-- Name: wb_metric_versions tenant_read; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_read ON public.wb_metric_versions FOR SELECT USING (public.perk_store_access(workspace_id, store_id));


--
-- Name: wb_records tenant_read; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_read ON public.wb_records FOR SELECT USING (public.perk_store_access(workspace_id, store_id));


--
-- Name: wb_staged_records tenant_read; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_read ON public.wb_staged_records FOR SELECT USING (public.perk_store_access(workspace_id, store_id));


--
-- Name: workspace_invites tenant_read; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_read ON public.workspace_invites FOR SELECT USING (public.perk_is_member(workspace_id, 'owner'::text));


--
-- Name: workspaces tenant_read; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_read ON public.workspaces FOR SELECT USING ((public.perk_is_member(id) OR (owner_user_id = public.perk_actor())));


--
-- Name: audit_events tenant_update; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_update ON public.audit_events FOR UPDATE USING (false) WITH CHECK (false);


--
-- Name: catalog_import_previews tenant_update; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_update ON public.catalog_import_previews FOR UPDATE USING ((public.perk_store_access(workspace_id, store_id) AND (created_by = public.perk_actor()) AND public.perk_is_member(workspace_id, 'owner'::text))) WITH CHECK ((public.perk_store_access(workspace_id, store_id) AND (created_by = public.perk_actor()) AND public.perk_is_member(workspace_id, 'owner'::text)));


--
-- Name: catalog_overrides tenant_update; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_update ON public.catalog_overrides FOR UPDATE USING ((public.perk_store_access(workspace_id, store_id) AND public.perk_is_member(workspace_id, 'owner'::text))) WITH CHECK ((public.perk_store_access(workspace_id, store_id) AND public.perk_is_member(workspace_id, 'owner'::text)));


--
-- Name: catalog_product_matches tenant_update; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_update ON public.catalog_product_matches FOR UPDATE USING ((public.perk_store_access(workspace_id, left_store_id) AND public.perk_store_access(workspace_id, right_store_id) AND public.perk_is_member(workspace_id, 'owner'::text))) WITH CHECK ((public.perk_store_access(workspace_id, left_store_id) AND public.perk_store_access(workspace_id, right_store_id) AND public.perk_is_member(workspace_id, 'owner'::text)));


--
-- Name: cost_imports tenant_update; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_update ON public.cost_imports FOR UPDATE USING ((public.perk_store_access(workspace_id, store_id) AND public.perk_permission(workspace_id, 'costs.write'::text))) WITH CHECK ((public.perk_store_access(workspace_id, store_id) AND public.perk_permission(workspace_id, 'costs.write'::text)));


--
-- Name: external_expenses tenant_update; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_update ON public.external_expenses FOR UPDATE USING ((public.perk_store_access(workspace_id, store_id) AND public.perk_permission(workspace_id, 'expenses.write'::text))) WITH CHECK ((public.perk_store_access(workspace_id, store_id) AND public.perk_permission(workspace_id, 'expenses.write'::text)));


--
-- Name: finance_days tenant_update; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_update ON public.finance_days FOR UPDATE USING ((public.perk_store_access(workspace_id, store_id) AND public.perk_is_member(workspace_id, 'owner'::text))) WITH CHECK ((public.perk_store_access(workspace_id, store_id) AND public.perk_is_member(workspace_id, 'owner'::text)));


--
-- Name: finance_projections tenant_update; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_update ON public.finance_projections FOR UPDATE USING ((public.perk_store_access(workspace_id, store_id) AND public.perk_is_member(workspace_id, 'owner'::text))) WITH CHECK ((public.perk_store_access(workspace_id, store_id) AND public.perk_is_member(workspace_id, 'owner'::text)));


--
-- Name: insight_snapshots tenant_update; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_update ON public.insight_snapshots FOR UPDATE USING (public.perk_store_access(workspace_id, store_id)) WITH CHECK (public.perk_store_access(workspace_id, store_id));


--
-- Name: inventory_settings tenant_update; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_update ON public.inventory_settings FOR UPDATE USING (public.perk_is_member(workspace_id, 'owner'::text)) WITH CHECK (public.perk_is_member(workspace_id, 'owner'::text));


--
-- Name: inventory_snapshots tenant_update; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_update ON public.inventory_snapshots FOR UPDATE USING ((public.perk_store_access(workspace_id, store_id) AND public.perk_is_member(workspace_id, 'owner'::text))) WITH CHECK ((public.perk_store_access(workspace_id, store_id) AND public.perk_is_member(workspace_id, 'owner'::text)));


--
-- Name: marketplace_catalog_snapshots tenant_update; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_update ON public.marketplace_catalog_snapshots FOR UPDATE USING ((public.perk_store_access(workspace_id, store_id) AND public.perk_is_member(workspace_id, 'owner'::text))) WITH CHECK ((public.perk_store_access(workspace_id, store_id) AND public.perk_is_member(workspace_id, 'owner'::text)));


--
-- Name: marketplace_finance_days tenant_update; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_update ON public.marketplace_finance_days FOR UPDATE USING ((public.perk_store_access(workspace_id, store_id) AND public.perk_is_member(workspace_id, 'owner'::text))) WITH CHECK ((public.perk_store_access(workspace_id, store_id) AND public.perk_is_member(workspace_id, 'owner'::text)));


--
-- Name: marketplace_realizations tenant_update; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_update ON public.marketplace_realizations FOR UPDATE USING ((public.perk_store_access(workspace_id, store_id) AND public.perk_is_member(workspace_id, 'owner'::text))) WITH CHECK ((public.perk_store_access(workspace_id, store_id) AND public.perk_is_member(workspace_id, 'owner'::text)));


--
-- Name: marketplace_sales_days tenant_update; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_update ON public.marketplace_sales_days FOR UPDATE USING ((public.perk_store_access(workspace_id, store_id) AND public.perk_is_member(workspace_id, 'owner'::text))) WITH CHECK ((public.perk_store_access(workspace_id, store_id) AND public.perk_is_member(workspace_id, 'owner'::text)));


--
-- Name: marketplace_stock_cover tenant_update; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_update ON public.marketplace_stock_cover FOR UPDATE USING ((public.perk_store_access(workspace_id, store_id) AND public.perk_is_member(workspace_id, 'owner'::text))) WITH CHECK ((public.perk_store_access(workspace_id, store_id) AND public.perk_is_member(workspace_id, 'owner'::text)));


--
-- Name: marketplace_supply_snapshots tenant_update; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_update ON public.marketplace_supply_snapshots FOR UPDATE USING ((public.perk_store_access(workspace_id, store_id) AND public.perk_is_member(workspace_id, 'owner'::text))) WITH CHECK ((public.perk_store_access(workspace_id, store_id) AND public.perk_is_member(workspace_id, 'owner'::text)));


--
-- Name: marketplace_traffic_days tenant_update; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_update ON public.marketplace_traffic_days FOR UPDATE USING ((public.perk_store_access(workspace_id, store_id) AND public.perk_is_member(workspace_id, 'owner'::text))) WITH CHECK ((public.perk_store_access(workspace_id, store_id) AND public.perk_is_member(workspace_id, 'owner'::text)));


--
-- Name: marketplace_variant_costs tenant_update; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_update ON public.marketplace_variant_costs FOR UPDATE USING ((public.perk_store_access(workspace_id, store_id) AND public.perk_permission(workspace_id, 'costs.write'::text))) WITH CHECK ((public.perk_store_access(workspace_id, store_id) AND public.perk_permission(workspace_id, 'costs.write'::text)));


--
-- Name: memberships tenant_update; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_update ON public.memberships FOR UPDATE USING ((public.perk_is_member(workspace_id, 'owner'::text) AND (NOT public.perk_is_creator(workspace_id, user_id)))) WITH CHECK ((public.perk_is_member(workspace_id, 'owner'::text) AND (NOT public.perk_is_creator(workspace_id, user_id))));


--
-- Name: store_credentials tenant_update; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_update ON public.store_credentials FOR UPDATE USING ((public.perk_store_access(workspace_id, store_id) AND public.perk_is_member(workspace_id, 'owner'::text))) WITH CHECK ((public.perk_store_access(workspace_id, store_id) AND public.perk_is_member(workspace_id, 'owner'::text)));


--
-- Name: store_events tenant_update; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_update ON public.store_events FOR UPDATE USING ((public.perk_store_access(workspace_id, store_id) AND public.perk_is_member(workspace_id, 'owner'::text))) WITH CHECK ((public.perk_store_access(workspace_id, store_id) AND public.perk_is_member(workspace_id, 'owner'::text)));


--
-- Name: store_goals tenant_update; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_update ON public.store_goals FOR UPDATE USING ((public.perk_store_access(workspace_id, store_id) AND public.perk_is_member(workspace_id, 'owner'::text))) WITH CHECK ((public.perk_store_access(workspace_id, store_id) AND public.perk_is_member(workspace_id, 'owner'::text)));


--
-- Name: stores tenant_update; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_update ON public.stores FOR UPDATE USING (public.perk_is_member(workspace_id, 'owner'::text)) WITH CHECK (public.perk_is_member(workspace_id, 'owner'::text));


--
-- Name: supply_destination_snapshots tenant_update; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_update ON public.supply_destination_snapshots FOR UPDATE USING ((public.perk_store_access(workspace_id, store_id) AND public.perk_is_member(workspace_id, 'owner'::text))) WITH CHECK ((public.perk_store_access(workspace_id, store_id) AND public.perk_is_member(workspace_id, 'owner'::text)));


--
-- Name: supply_packaging tenant_update; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_update ON public.supply_packaging FOR UPDATE USING ((public.perk_store_access(workspace_id, store_id) AND public.perk_is_member(workspace_id, 'owner'::text))) WITH CHECK ((public.perk_store_access(workspace_id, store_id) AND public.perk_is_member(workspace_id, 'owner'::text)));


--
-- Name: supply_plans tenant_update; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_update ON public.supply_plans FOR UPDATE USING ((public.perk_store_access(workspace_id, store_id) AND public.perk_is_member(workspace_id, 'owner'::text))) WITH CHECK ((public.perk_store_access(workspace_id, store_id) AND public.perk_is_member(workspace_id, 'owner'::text)));


--
-- Name: sync_schedules tenant_update; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_update ON public.sync_schedules FOR UPDATE USING ((public.perk_store_access(workspace_id, store_id) AND public.perk_is_member(workspace_id, 'owner'::text))) WITH CHECK ((public.perk_store_access(workspace_id, store_id) AND public.perk_is_member(workspace_id, 'owner'::text)));


--
-- Name: tax_settings tenant_update; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_update ON public.tax_settings FOR UPDATE USING ((public.perk_store_access(workspace_id, store_id) AND public.perk_permission(workspace_id, 'taxes.write'::text))) WITH CHECK ((public.perk_store_access(workspace_id, store_id) AND public.perk_permission(workspace_id, 'taxes.write'::text)));


--
-- Name: wb_daily_metrics tenant_update; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_update ON public.wb_daily_metrics FOR UPDATE USING ((public.perk_store_access(workspace_id, store_id) AND public.perk_is_member(workspace_id, 'owner'::text))) WITH CHECK ((public.perk_store_access(workspace_id, store_id) AND public.perk_is_member(workspace_id, 'owner'::text)));


--
-- Name: wb_metric_versions tenant_update; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_update ON public.wb_metric_versions FOR UPDATE USING ((public.perk_store_access(workspace_id, store_id) AND public.perk_is_member(workspace_id, 'owner'::text))) WITH CHECK ((public.perk_store_access(workspace_id, store_id) AND public.perk_is_member(workspace_id, 'owner'::text)));


--
-- Name: wb_records tenant_update; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_update ON public.wb_records FOR UPDATE USING ((public.perk_store_access(workspace_id, store_id) AND public.perk_is_member(workspace_id, 'owner'::text))) WITH CHECK ((public.perk_store_access(workspace_id, store_id) AND public.perk_is_member(workspace_id, 'owner'::text)));


--
-- Name: wb_staged_records tenant_update; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_update ON public.wb_staged_records FOR UPDATE USING ((public.perk_store_access(workspace_id, store_id) AND public.perk_is_member(workspace_id, 'owner'::text))) WITH CHECK ((public.perk_store_access(workspace_id, store_id) AND public.perk_is_member(workspace_id, 'owner'::text)));


--
-- Name: workspace_invites tenant_update; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_update ON public.workspace_invites FOR UPDATE USING (public.perk_is_member(workspace_id, 'owner'::text)) WITH CHECK (public.perk_is_member(workspace_id, 'owner'::text));


--
-- Name: workspaces tenant_update; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_update ON public.workspaces FOR UPDATE USING (public.perk_is_member(id, 'owner'::text)) WITH CHECK (public.perk_is_member(id, 'owner'::text));


--
-- Name: ozon_analytics_sync tenant_write; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_write ON public.ozon_analytics_sync USING ((public.perk_store_access(workspace_id, store_id) AND public.perk_is_member(workspace_id, 'owner'::text))) WITH CHECK ((public.perk_store_access(workspace_id, store_id) AND public.perk_is_member(workspace_id, 'owner'::text)));


--
-- Name: ozon_catalog_sync tenant_write; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_write ON public.ozon_catalog_sync USING ((public.perk_store_access(workspace_id, store_id) AND public.perk_is_member(workspace_id, 'owner'::text))) WITH CHECK ((public.perk_store_access(workspace_id, store_id) AND public.perk_is_member(workspace_id, 'owner'::text)));


--
-- Name: supply_destination_sync tenant_write; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_write ON public.supply_destination_sync USING ((public.perk_store_access(workspace_id, store_id) AND public.perk_is_member(workspace_id, 'owner'::text))) WITH CHECK ((public.perk_store_access(workspace_id, store_id) AND public.perk_is_member(workspace_id, 'owner'::text)));


--
-- Name: sync_runs tenant_write; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_write ON public.sync_runs USING ((public.perk_store_access(workspace_id, store_id) AND public.perk_is_member(workspace_id, 'owner'::text))) WITH CHECK ((public.perk_store_access(workspace_id, store_id) AND public.perk_is_member(workspace_id, 'owner'::text)));


--
-- Name: wb_daily_metrics; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.wb_daily_metrics ENABLE ROW LEVEL SECURITY;

--
-- Name: wb_metric_versions; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.wb_metric_versions ENABLE ROW LEVEL SECURITY;

--
-- Name: wb_records; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.wb_records ENABLE ROW LEVEL SECURITY;

--
-- Name: wb_staged_records; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.wb_staged_records ENABLE ROW LEVEL SECURITY;

--
-- Name: workspace_invites; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.workspace_invites ENABLE ROW LEVEL SECURITY;

--
-- Name: workspaces; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.workspaces ENABLE ROW LEVEL SECURITY;

--
-- PostgreSQL database dump complete
--

\unrestrict N70bUuB0T8aRg79WKgjd27WcE2hK0mZ2mWLZhvzgyvcp6khABIlSygcXHMbsIHS

