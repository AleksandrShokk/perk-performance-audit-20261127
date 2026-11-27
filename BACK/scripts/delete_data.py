"""Manual deletion under the migration role. Dry-run is the default; never run on a schedule."""

import argparse
import json
from uuid import UUID

from sqlalchemy import MetaData, delete, select, text

from app.core.config import get_settings
from app.db.session import build_engine
from app.modules.audit.models import AuditEvent


def remove(db, workspace_id, store_id=None, execute=False):
    metadata = MetaData()
    metadata.reflect(bind=db.bind)
    root = metadata.tables["stores" if store_id else "workspaces"]
    condition = root.c.id == (store_id or workspace_id)
    if store_id:
        condition &= root.c.workspace_id == workspace_id
    if db.scalar(select(root.c.id).where(condition)) is None:
        raise ValueError("Target does not exist in the specified workspace")
    # Tables are processed in reverse FK order, including tables without ON DELETE CASCADE.
    tables = list(reversed(metadata.sorted_tables))
    counts = {}
    for table in tables:
        if table.name in {"alembic_version", "workspaces", "stores"}:
            continue
        if "workspace_id" not in table.c:
            continue
        condition = table.c.workspace_id == workspace_id
        if store_id is not None:
            if "store_id" not in table.c:
                continue
            condition &= table.c.store_id == store_id
        count = db.scalar(select(text("count(*)")).select_from(table).where(condition))
        if count:
            counts[table.name] = count
            if execute:
                db.execute(delete(table).where(condition))
    condition = root.c.id == (store_id or workspace_id)
    if store_id:
        condition &= root.c.workspace_id == workspace_id
    if execute:
        db.execute(delete(root).where(condition))
        db.add(
            AuditEvent(
                action="data.store_deleted" if store_id else "data.workspace_deleted",
                target_id=store_id or workspace_id,
                success=True,
            )
        )
    return counts


def main():
    from sqlalchemy.orm import Session

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=UUID, required=True)
    parser.add_argument("--store", type=UUID)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--confirm", type=UUID)
    args = parser.parse_args()
    if args.execute and args.confirm != (args.store or args.workspace):
        parser.error("--confirm must exactly match the target UUID")
    engine = build_engine(get_settings())
    try:
        with Session(engine) as db, db.begin():
            if not db.scalar(
                text("SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname=current_user")
            ):
                raise RuntimeError("Run only with the migration/admin database role")
            print(
                json.dumps(
                    {
                        "dry_run": not args.execute,
                        "rows": remove(db, args.workspace, args.store, args.execute),
                    }
                )
            )
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
