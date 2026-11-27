"""Forced RLS for workspace metadata and credentials; team invitations.

Policies call small SECURITY DEFINER helpers: a policy on `memberships` that read
`memberships` directly would recurse. sync_runs stays without RLS on purpose: it is the
outbox that cross-tenant workers scan for identifiers before switching to the owner actor.
"""

import sqlalchemy as sa
from alembic import op

revision = "0012_tenant_rls_team"
down_revision = "0011_audit_fixes"
branch_labels = None
depends_on = None

HELPERS = """
CREATE FUNCTION perk_actor() RETURNS uuid LANGUAGE sql STABLE AS $$
  SELECT NULLIF(current_setting('perk.user_id', true), '')::uuid
$$;
CREATE FUNCTION perk_is_member(ws uuid, required text DEFAULT NULL) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
  SELECT EXISTS (
    SELECT 1 FROM memberships
    WHERE workspace_id = ws AND user_id = perk_actor() AND (required IS NULL OR role = required)
  )
$$;
CREATE FUNCTION perk_created_workspace(ws uuid) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
  SELECT EXISTS (SELECT 1 FROM workspaces WHERE id = ws AND owner_user_id = perk_actor())
$$;
CREATE FUNCTION perk_is_creator(ws uuid, subject uuid) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
  SELECT EXISTS (SELECT 1 FROM workspaces WHERE id = ws AND owner_user_id = subject)
$$;
"""

ACCEPT = """
CREATE FUNCTION perk_accept_invite(digest text) RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE invite workspace_invites%ROWTYPE; actor uuid := perk_actor(); address text;
BEGIN
  IF actor IS NULL THEN RETURN NULL; END IF;
  SELECT email INTO address FROM users
    WHERE id = actor AND is_active AND email_verified_at IS NOT NULL;
  IF address IS NULL THEN RETURN NULL; END IF;
  SELECT * INTO invite FROM workspace_invites
    WHERE token_digest = digest AND accepted_at IS NULL AND expires_at > now() FOR UPDATE;
  -- Only the invited, verified address can accept; anything else looks like a bad code.
  IF NOT FOUND OR invite.email <> address THEN RETURN NULL; END IF;
  IF NOT EXISTS (SELECT 1 FROM memberships WHERE workspace_id = invite.workspace_id
      AND user_id = invite.invited_by AND role = 'owner') THEN RETURN NULL; END IF;
  INSERT INTO memberships (user_id, workspace_id, role)
    VALUES (actor, invite.workspace_id, invite.role)
    ON CONFLICT (user_id, workspace_id) DO NOTHING;
  UPDATE workspace_invites SET accepted_at = now(), accepted_by = actor WHERE id = invite.id;
  RETURN invite.workspace_id;
END $$;
"""

POLICIES = {
    "workspaces": {
        # A just-created workspace must be readable by its creator before membership exists.
        "read": "perk_is_member(id) OR owner_user_id = perk_actor()",
        "insert": "owner_user_id = perk_actor()",
        "update": "perk_is_member(id, 'owner')",
        "delete": "perk_is_member(id, 'owner')",
    },
    "memberships": {
        "read": "perk_is_member(workspace_id)",
        "insert": "perk_is_member(workspace_id, 'owner') OR "
        "(user_id = perk_actor() AND role = 'owner' AND perk_created_workspace(workspace_id))",
        "update": "perk_is_member(workspace_id, 'owner') "
        "AND NOT perk_is_creator(workspace_id, user_id)",
        "delete": "(perk_is_member(workspace_id, 'owner') OR user_id = perk_actor()) "
        "AND NOT perk_is_creator(workspace_id, user_id)",
    },
    "stores": {
        "read": "perk_is_member(workspace_id)",
        "insert": "perk_is_member(workspace_id, 'owner')",
        "update": "perk_is_member(workspace_id, 'owner')",
        "delete": "perk_is_member(workspace_id, 'owner')",
    },
    "store_credentials": {
        "read": "perk_is_member(workspace_id)",
        "insert": "perk_is_member(workspace_id, 'owner')",
        "update": "perk_is_member(workspace_id, 'owner')",
        "delete": "perk_is_member(workspace_id, 'owner')",
    },
    "audit_events": {
        # Account events (no workspace) are written before sign-in completes.
        "read": "(workspace_id IS NULL AND user_id = perk_actor()) OR "
        "perk_is_member(workspace_id, 'owner')",
        # Former members' queued jobs still append permission-revoked events, but cannot read
        # the workspace afterwards. This does not grant them SELECT/UPDATE/DELETE.
        "insert": "workspace_id IS NULL OR user_id = perk_actor()",
        "update": "false",
        "delete": "false",
    },
    "workspace_invites": {
        "read": "perk_is_member(workspace_id, 'owner')",
        "insert": "perk_is_member(workspace_id, 'owner')",
        "update": "perk_is_member(workspace_id, 'owner')",
        "delete": "perk_is_member(workspace_id, 'owner')",
    },
}


def upgrade():
    op.create_table(
        "workspace_invites",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("token_digest", sa.String(64), nullable=False),
        sa.Column("invited_by", sa.Uuid(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("accepted_by", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("role IN ('owner', 'viewer')", name=op.f("ck_workspace_invites_role")),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_workspace_invites_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["invited_by"], ["users.id"], name=op.f("fk_workspace_invites_invited_by_users")
        ),
        sa.ForeignKeyConstraint(
            ["accepted_by"], ["users.id"], name=op.f("fk_workspace_invites_accepted_by_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workspace_invites")),
        sa.UniqueConstraint("token_digest", name=op.f("uq_workspace_invites_token_digest")),
    )
    op.create_index(
        op.f("ix_workspace_invites_workspace_id"), "workspace_invites", ["workspace_id"]
    )
    op.execute(HELPERS)
    op.execute(ACCEPT)
    for table, rules in POLICIES.items():
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY tenant_read ON {table} FOR SELECT USING ({rules['read']})")
        op.execute(
            f"CREATE POLICY tenant_insert ON {table} FOR INSERT WITH CHECK ({rules['insert']})"
        )
        op.execute(
            f"CREATE POLICY tenant_update ON {table} FOR UPDATE "
            f"USING ({rules['update']}) WITH CHECK ({rules['update']})"
        )
        op.execute(f"CREATE POLICY tenant_delete ON {table} FOR DELETE USING ({rules['delete']})")
    op.execute("REVOKE ALL ON FUNCTION perk_accept_invite(text) FROM PUBLIC")


def downgrade():
    for table in POLICIES:
        for policy in ("tenant_read", "tenant_insert", "tenant_update", "tenant_delete"):
            op.execute(f"DROP POLICY IF EXISTS {policy} ON {table}")
        if table != "workspace_invites":
            op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
            op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
    op.execute("DROP FUNCTION IF EXISTS perk_accept_invite(text)")
    op.drop_table("workspace_invites")
    op.execute("DROP FUNCTION IF EXISTS perk_created_workspace(uuid)")
    op.execute("DROP FUNCTION IF EXISTS perk_is_creator(uuid, uuid)")
    op.execute("DROP FUNCTION IF EXISTS perk_is_member(uuid, text)")
    op.execute("DROP FUNCTION IF EXISTS perk_actor()")
