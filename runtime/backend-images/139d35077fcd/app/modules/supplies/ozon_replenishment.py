"""Calendar order demand and current native FBO/FBS stock for a supply plan."""

from collections import Counter
from decimal import Decimal

from app.modules.catalog.ozon_read import item, snapshot
from app.modules.insights.marketplace_models import OzonAnalyticsSync
from app.modules.inventory.channel_cover import ozon_channel_rates
from app.modules.supplies.schemas import ReplenishmentItem


def estimates(db, vault, workspace_id, store, calculate, *, include_fbs=False):
    catalog, stamp = snapshot(db, vault, workspace_id, store)
    rates, demand_stamp = ozon_channel_rates(db, vault, workspace_id, store.id, channel="all")

    def codes(row):
        return (
            set(row.get("sku_aliases", []))
            | {row["marketplace_code"]}
            | {sku for values in row.get("channel_skus", {}).values() for sku in values}
        )

    owners = Counter(sku for row in catalog or [] for sku in codes(row))
    items, unknown, no_orders = [], 0, 0
    incomplete_fbs = False
    for row in catalog or []:
        skus = codes(row)
        if rates is None or any(owners[sku] != 1 for sku in skus):
            unknown += 1
            continue
        rate = sum((rates.get(sku, Decimal(0)) for sku in skus), Decimal(0))
        if rate <= 0:
            no_orders += 1
            continue
        stock = row["channels"]["fbo"]["quantity"]
        if stock is None:
            unknown += 1
            continue
        fbs = row["channels"]["fbs"]["quantity"] if include_fbs else 0
        incomplete_fbs |= include_fbs and fbs is None
        result = calculate(stock, rate, row.get("channel_skus", {}).get("fbo", []), stamp, fbs)
        if not result or not result["quantity"]:
            continue
        product = item(row, store, stamp, True)
        items.append(
            ReplenishmentItem(
                id=product.id,
                marketplace="ozon",
                marketplace_code=row["marketplace_code"],
                demand_basis="ozon_orders",
                store_id=store.id,
                store_name=store.name,
                nm_id="",
                vendor_code=row["vendor_code"],
                title=row["title"] or row["vendor_code"],
                photo=(row["photos"] or [None])[0],
                colors=row["colors"],
                barcodes=row["barcodes"],
                **result,
            )
        )
    job = db.get(OzonAnalyticsSync, (workspace_id, store.id, "sales"))
    loading = bool(job and job.status in {"pending", "queued", "running"})
    return {
        "items": items,
        "updated_at": min((s for s in (stamp, demand_stamp) if s), default=None),
        "unknown": unknown,
        "no_orders": no_orders,
        "ready": catalog is not None and rates is not None,
        "loading": loading,
        "partial": catalog is None or rates is None or unknown > 0 or incomplete_fbs,
    }
