"""Daily stock snapshots from retained WB rows. Runs in a worker under the store lock."""

import json
from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import delete, select

from app.db.tenant import scope
from app.integrations.wildberries.data import Source
from app.modules.auth.dependencies import now
from app.modules.inventory.models import InventorySnapshot
from app.modules.sync.analytics import record_context
from app.modules.sync.models import SyncRun, WBRecord

DEMAND_DAYS = 30


def snapshot_aad(workspace_id, store_id, day, nm_id):
    return f"perk-inventory:v1:{workspace_id}:{store_id}:{day}:{nm_id}"


def retained(db, vault, workspace_id, store_id, source):
    last_key = ""
    while True:
        batch = db.execute(
            select(WBRecord.record_key, WBRecord.ciphertext)
            .where(
                *scope(WBRecord, workspace_id, store_id),
                WBRecord.source == source,
                WBRecord.record_key > last_key,
            )
            .order_by(WBRecord.record_key)
            .limit(1000)
        ).all()
        if not batch:
            return
        for key, ciphertext in batch:
            yield json.loads(
                vault.open(ciphertext, record_context(workspace_id, store_id, source, key))
            )
        last_key = batch[-1][0]


def latest_stock_import(db, workspace_id, store_id):
    """The import whose rows are currently retained: stock publication replaces them."""
    return db.scalar(
        select(SyncRun)
        .where(
            *scope(SyncRun, workspace_id, store_id),
            SyncRun.source == Source.STOCKS,
            SyncRun.status == "succeeded",
            SyncRun.finished_at.is_not(None),
        )
        .order_by(SyncRun.finished_at.desc())
        .limit(1)
    )


def moscow_date(moment):
    return (moment + timedelta(hours=3)).date()


def recorded_run(db, vault, workspace_id, store_id, day):
    row = db.scalar(
        select(InventorySnapshot)
        .where(
            *scope(InventorySnapshot, workspace_id, store_id),
            InventorySnapshot.day == day,
            InventorySnapshot.channel == "fbo",
        )
        .limit(1)
    )
    if row is None:
        return None
    payload = json.loads(
        vault.open(row.ciphertext, snapshot_aad(workspace_id, store_id, day, row.nm_id))
    )
    return payload.get("stock_run_id")


def empty():
    return {
        "stock": 0,
        "to_client": 0,
        "from_client": 0,
        "warehouses": defaultdict(int),
        "sizes": defaultdict(int),
        "demand_by_warehouse": defaultdict(int),
        "demand_by_size": defaultdict(int),
    }


def build_snapshot(db, vault, workspace_id, store_id) -> bool:
    """Record the latest stock import as an observation on the day it was taken.

    Old imports never become new observations: the snapshot day is the Moscow date of the
    import, and an import that is already recorded is not written again.
    """
    run = latest_stock_import(db, workspace_id, store_id)
    if run is None:
        return False
    today = moscow_date(run.finished_at)
    if recorded_run(db, vault, workspace_id, store_id, today) == str(run.id):
        return False
    sizes = {}
    for item in retained(db, vault, workspace_id, store_id, Source.CATALOG):
        for size in item.get("sizes", []):
            for barcode in size["barcodes"]:
                sizes[(item["nm_id"], barcode)] = size["size"] or size["chrt_id"]
            sizes[(item["nm_id"], "chrt:" + size["chrt_id"])] = size["size"] or size["chrt_id"]
    rows = defaultdict(empty)
    for item in retained(db, vault, workspace_id, store_id, Source.STOCKS):
        row = rows[item["nm_id"]]
        row["stock"] += item["quantity"]
        row["to_client"] += item["in_way_to_client"]
        row["from_client"] += item["in_way_from_client"]
        row["warehouses"][item["warehouse_name"]] += item["quantity"]
        size = sizes.get((item["nm_id"], "chrt:" + item["chrt_id"]), item["chrt_id"])
        row["sizes"][size] += item["quantity"]
    # Demand allocation uses where buyers ordered from, not where stock already lies.
    start = today - timedelta(days=DEMAND_DAYS)
    for item in retained(db, vault, workspace_id, store_id, Source.SALES):
        if item["kind"] != "sale" or not start <= date.fromisoformat(item["date"][:10]) < today:
            continue
        row = rows[item["nm_id"]]
        row["demand_by_warehouse"][item["warehouse_name"] or "unknown"] += 1
        size = sizes.get((item["nm_id"], item["barcode"]))
        if size:
            row["demand_by_size"][size] += 1
    db.execute(
        delete(InventorySnapshot).where(
            *scope(InventorySnapshot, workspace_id, store_id),
            InventorySnapshot.day == today,
            InventorySnapshot.channel == "fbo",
        )
    )
    stamp = now()
    for nm_id, row in rows.items():
        row["stock_run_id"] = str(run.id)
        row["as_of"] = run.finished_at.isoformat()
        db.add(
            InventorySnapshot(
                workspace_id=workspace_id,
                store_id=store_id,
                day=today,
                nm_id=nm_id,
                updated_at=stamp,
                ciphertext=vault.seal(
                    json.dumps(row, separators=(",", ":"), ensure_ascii=False),
                    snapshot_aad(workspace_id, store_id, today, nm_id),
                ),
            )
        )
    db.flush()
    return True
