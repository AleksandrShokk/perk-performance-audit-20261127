"""Real daily stock observations. No synthetic days or inferred FBS quantities."""

import json
from collections import defaultdict
from datetime import timedelta

from sqlalchemy import delete, select

from app.integrations.wildberries.data import Source, WBError
from app.modules.inventory.models import InventorySnapshot
from app.modules.inventory.projection import build_snapshot, retained, snapshot_aad
from app.modules.sync.models import SyncRun


def catalog_sizes(db, vault, run):
    ready = db.scalar(
        select(SyncRun.id)
        .where(
            SyncRun.workspace_id == run.workspace_id,
            SyncRun.store_id == run.store_id,
            SyncRun.source == Source.CATALOG,
            SyncRun.status == "succeeded",
        )
        .limit(1)
    )
    if not ready:
        raise WBError("wb_catalog_not_ready", retryable=True)
    sizes = {}
    for card in retained(db, vault, run.workspace_id, run.store_id, Source.CATALOG):
        for size in card.get("sizes", []):
            chrt = size["chrt_id"]
            if chrt in sizes and sizes[chrt]["nm_id"] != card["nm_id"]:
                raise WBError("wb_catalog_size_conflict")
            sizes[chrt] = {"chrt_id": chrt, "nm_id": card["nm_id"]}
    return sorted(sizes.values(), key=lambda row: int(row["chrt_id"]))


def channel_aad(workspace_id, store_id, day, article, channel):
    return (
        snapshot_aad(workspace_id, store_id, day, article)
        if channel == "fbo"
        else f"perk-inventory:fbs:v1:{workspace_id}:{store_id}:{day}:{article}"
    )


def record_stock(db, vault, run):
    if run.source == Source.STOCKS:
        return build_snapshot(db, vault, run.workspace_id, run.store_id)
    day = (run.finished_at + timedelta(hours=3)).date()
    totals = defaultdict(int)
    for card in retained(db, vault, run.workspace_id, run.store_id, Source.CATALOG):
        totals[card["nm_id"]] = 0
    for row in retained(db, vault, run.workspace_id, run.store_id, Source.FBS):
        totals[row["nm_id"]] += row["quantity"]
    db.execute(
        delete(InventorySnapshot).where(
            InventorySnapshot.workspace_id == run.workspace_id,
            InventorySnapshot.store_id == run.store_id,
            InventorySnapshot.day == day,
            InventorySnapshot.channel == "fbs",
        )
    )
    for article, stock in totals.items():
        db.add(
            InventorySnapshot(
                workspace_id=run.workspace_id,
                store_id=run.store_id,
                day=day,
                nm_id=article,
                channel="fbs",
                updated_at=run.finished_at,
                ciphertext=vault.seal(
                    json.dumps({"stock": stock}),
                    channel_aad(run.workspace_id, run.store_id, day, article, "fbs"),
                ),
            )
        )
    db.flush()
