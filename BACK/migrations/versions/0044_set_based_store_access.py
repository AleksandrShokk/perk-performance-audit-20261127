"""Evaluate store access once per statement instead of once per row.

Row-level policies called perk_store_access(workspace_id, store_id) for every row. The
function is SECURITY DEFINER with its own search_path, so PostgreSQL cannot inline it:
each call ran a memberships lookup (~16 us per row on a test database, ~44 us in
production; 50 000 rows took ~800 ms instead of ~8 ms).

The policies now compare the row with the set of (workspace, store) pairs the current
actor may access. perk_accessible_stores() returns exactly the pairs for which
perk_store_access() is true for an existing store, and the planner evaluates it once
per statement (hashed subplan). Every rewritten table has NOT NULL store columns and,
except wb_staged_records (rows are only written for existing stores), a foreign key to
stores, so no row changes visibility. The stores table keeps the per-row function: a
store being inserted is not yet part of the set. perk_store_access() itself is kept for
other functions and for that table.
"""

import re

from alembic import op
from sqlalchemy import text

revision = "0044_set_based_store_access"
down_revision = "0043_phone_change"
branch_labels = None
depends_on = None

ACCESSIBLE = """
CREATE OR REPLACE FUNCTION public.perk_accessible_stores()
RETURNS TABLE (workspace_id uuid, store_id uuid)
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path TO 'public', 'pg_temp'
AS $$
 SELECT s.workspace_id, s.id FROM memberships m JOIN stores s ON s.workspace_id = m.workspace_id
 WHERE m.user_id = perk_actor()
 AND (m.role IN ('owner','admin') OR m.store_ids IS NULL
      OR m.store_ids @> jsonb_build_array(s.id::text))
$$
"""
STORE_COLUMNS = ("store_id", "left_store_id", "right_store_id")
PER_ROW = re.compile(r"perk_store_access\(workspace_id, (" + "|".join(STORE_COLUMNS) + r")\)")
SET_BASED = (
    "((workspace_id, {column}) IN "
    "(SELECT a.workspace_id, a.store_id FROM public.perk_accessible_stores() a))"
)
# How PostgreSQL prints SET_BASED back in pg_policies.
PRINTED = re.compile(
    r"\(\(workspace_id, (" + "|".join(STORE_COLUMNS) + r")\) IN \( SELECT a\.workspace_id,"
    r"\s+a\.store_id\s+FROM perk_accessible_stores\(\) a\(workspace_id, store_id\)\)\)"
)


def policies(connection, marker):
    return connection.execute(
        text(
            "SELECT tablename, policyname, qual, with_check FROM pg_policies "
            "WHERE schemaname = 'public' AND tablename <> 'stores' "
            "AND (coalesce(qual, '') LIKE :marker OR coalesce(with_check, '') LIKE :marker) "
            "ORDER BY tablename, policyname"
        ),
        {"marker": f"%{marker}%"},
    ).all()


def rewrite(connection, marker, pattern, replace):
    changed = 0
    for table, name, qual, check in policies(connection, marker):
        parts = []
        for clause, expression in (("USING", qual), ("WITH CHECK", check)):
            if expression is not None:
                parts.append(f"{clause} ({pattern.sub(replace, expression)})")
        op.execute(f'ALTER POLICY "{name}" ON public."{table}" ' + " ".join(parts))
        changed += 1
    return changed


def upgrade():
    connection = op.get_bind()
    op.execute(ACCESSIBLE)
    changed = rewrite(
        connection,
        "perk_store_access(workspace_id, ",
        PER_ROW,
        lambda match: SET_BASED.format(column=match.group(1)),
    )
    if not changed:
        raise RuntimeError("No store policies found to rewrite")
    remaining = [
        f"{table}.{name}"
        for table, name, *_ in policies(connection, "perk_store_access(workspace_id, ")
    ]
    if remaining:
        raise RuntimeError("Store policies left per-row: " + ", ".join(remaining))


def downgrade():
    connection = op.get_bind()
    rewrite(
        connection,
        "perk_accessible_stores()",
        PRINTED,
        lambda match: f"perk_store_access(workspace_id, {match.group(1)})",
    )
    remaining = [f"{t}.{n}" for t, n, *_ in policies(connection, "perk_accessible_stores()")]
    if remaining:
        raise RuntimeError("Store policies not restored: " + ", ".join(remaining))
    op.execute("DROP FUNCTION public.perk_accessible_stores()")
