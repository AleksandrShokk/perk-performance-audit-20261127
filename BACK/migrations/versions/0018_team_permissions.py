"""Employee roles, section permissions and store scopes; verified-phone invitations."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0018_team_permissions"
down_revision = "0017_funnel_summary"
branch_labels = None
depends_on = None

HELPERS = """
CREATE OR REPLACE FUNCTION perk_is_member(ws uuid, required text DEFAULT NULL) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
 SELECT EXISTS (SELECT 1 FROM memberships WHERE workspace_id=ws AND user_id=perk_actor()
 AND (required IS NULL OR role=required OR (required='owner' AND role='admin')))
$$;
CREATE FUNCTION perk_store_access(ws uuid, sid uuid) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
 SELECT EXISTS (SELECT 1 FROM memberships WHERE workspace_id=ws AND user_id=perk_actor()
 AND (role IN ('owner','admin') OR store_ids IS NULL OR store_ids @> jsonb_build_array(sid::text)))
$$;
CREATE FUNCTION perk_permission(ws uuid, p text) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
 SELECT EXISTS (SELECT 1 FROM memberships WHERE workspace_id=ws AND user_id=perk_actor()
 AND (role IN ('owner','admin') OR COALESCE(permissions,
 CASE role WHEN 'manager' THEN '["analytics.read","inventory.read"]'::jsonb
 WHEN 'accountant' THEN '["analytics.read","finance.read","profit.read",
 "costs.write","expenses.write","taxes.write","reports.export"]'::jsonb
 WHEN 'viewer' THEN '["analytics.read","inventory.read","finance.read","profit.read"]'::jsonb
 ELSE '[]'::jsonb END) ? p))
$$;
CREATE FUNCTION perk_invite_details(digest text) RETURNS jsonb
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
 SELECT jsonb_build_object('email',i.email,'role',i.role,'workspace_name',w.name,
 'permissions',i.permissions,'store_ids',i.store_ids,'expires_at',i.expires_at)
 FROM workspace_invites i JOIN workspaces w ON w.id=i.workspace_id
 WHERE i.token_digest=digest AND i.accepted_at IS NULL AND i.expires_at>now()
 AND EXISTS (SELECT 1 FROM memberships m WHERE m.workspace_id=i.workspace_id
 AND m.user_id=i.invited_by AND m.role IN ('owner','admin'))
$$;
CREATE FUNCTION perk_lock_store(ws uuid, sid uuid, p text) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
BEGIN
 IF NOT perk_store_access(ws,sid) OR NOT perk_permission(ws,p) THEN RETURN false; END IF;
 PERFORM 1 FROM stores WHERE workspace_id=ws AND id=sid AND is_active FOR KEY SHARE;
 RETURN FOUND;
END $$;
CREATE OR REPLACE FUNCTION perk_accept_invite(digest text) RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
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
"""


def upgrade():
    for table in ("memberships", "workspace_invites"):
        op.add_column(table, sa.Column("permissions", postgresql.JSONB(), nullable=True))
        op.add_column(table, sa.Column("store_ids", postgresql.JSONB(), nullable=True))
        op.drop_constraint(op.f(f"ck_{table}_role"), table, type_="check")
        op.create_check_constraint(
            "role", table, "role IN ('owner','admin','manager','accountant','viewer')"
        )
        op.create_check_constraint(
            "permissions_array", table, "permissions IS NULL OR jsonb_typeof(permissions)='array'"
        )
        op.create_check_constraint(
            "stores_array", table, "store_ids IS NULL OR jsonb_typeof(store_ids)='array'"
        )
    op.execute(HELPERS)
    # Existing protected tables keep FORCE RLS; all store reads now honour the employee scope.
    connection = op.get_bind()
    tables = sa.inspect(connection)
    for table in tables.get_table_names():
        columns = {item["name"] for item in tables.get_columns(table)}
        if not {"workspace_id", "store_id"} <= columns:
            continue
        policies = {
            row[0]
            for row in connection.execute(
                sa.text(
                    "SELECT policyname FROM pg_policies "
                    "WHERE schemaname='public' AND tablename=:table"
                ),
                {"table": table},
            )
        }
        if "tenant_read" not in policies:
            continue  # Cross-store outbox tables intentionally have no RLS.
        scope = "perk_store_access(workspace_id,store_id)"
        read = scope
        if table == "store_credentials":
            read += " AND perk_is_member(workspace_id,'owner')"
        op.execute(f"ALTER POLICY tenant_read ON {table} USING ({read})")
        permission = {
            "product_costs": "costs.write",
            "cost_imports": "costs.write",
            "external_expenses": "expenses.write",
            "tax_settings": "taxes.write",
        }.get(table)
        writer = scope + (
            " AND perk_permission(workspace_id,'" + permission + "')"
            if permission
            else ""
            if table == "insight_snapshots"
            else " AND perk_is_member(workspace_id,'owner')"
        )
        for policy, command in [
            ("tenant_insert", "INSERT"),
            ("tenant_update", "UPDATE"),
            ("tenant_delete", "DELETE"),
        ]:
            if policy in policies:
                clause = f"WITH CHECK ({writer})" if command == "INSERT" else f"USING ({writer})"
                if command == "UPDATE":
                    clause += f" WITH CHECK ({writer})"
                op.execute(f"ALTER POLICY {policy} ON {table} {clause}")
    op.execute("ALTER POLICY tenant_read ON stores USING (perk_store_access(workspace_id,id))")
    op.execute(
        "ALTER POLICY tenant_read ON memberships USING "
        "(user_id=perk_actor() OR perk_is_member(workspace_id,'owner'))"
    )
    op.execute("REVOKE ALL ON FUNCTION perk_invite_details(text) FROM PUBLIC")
    op.execute("REVOKE ALL ON FUNCTION perk_lock_store(uuid,uuid,text) FROM PUBLIC")


def downgrade():
    # Restoring old access rules must be deliberate: it could widen employee store scopes.
    raise RuntimeError("Restore the preceding database snapshot to roll back team permissions.")
