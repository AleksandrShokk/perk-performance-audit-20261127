"""Ozon adapter for the shared catalog contract, independent of WB's nm/chrt IDs."""

import json
from collections import defaultdict
from datetime import timedelta

from app.modules.auth.dependencies import now
from app.modules.catalog.marketplace_models import (
    MarketplaceCatalogSnapshot,
    OzonCatalogSync,
)
from app.modules.catalog.ozon_jobs import aad
from app.modules.catalog.schemas import ProductItem, ProductModel, ProductVariant


def snapshot(db, vault, workspace_id, store):
    row = db.get(MarketplaceCatalogSnapshot, (workspace_id, store.id))
    return (
        (
            json.loads(vault.open(row.ciphertext, aad(workspace_id, store.id))),
            row.updated_at,
        )
        if row
        else (None, None)
    )


def state(db, workspace_id, store_id):
    row = db.get(OzonCatalogSync, (workspace_id, store_id))
    return {
        "status": row.status if row else "pending",
        "records_processed": row.records_processed if row else 0,
        "updated_at": row.updated_at if row else None,
        "error_code": row.error_code if row else None,
    }


def item(row, store, updated_at, can_stock):
    fbo = row["channels"]["fbo"]["quantity"] if can_stock else None
    return ProductItem(
        store_id=store.id,
        store_name=store.name,
        marketplace="ozon",
        nm_id="",
        external_id=row["external_id"],
        marketplace_code=row["marketplace_code"],
        vendor_code=row["vendor_code"],
        title=row["title"],
        brand=row["brand"],
        subject="",
        colors=row["colors"],
        photos=row["photos"],
        variants=[
            ProductVariant(
                chrt_id="",
                external_id=row["external_id"],
                size=row["size"],
                barcodes=row["barcodes"],
                stock=fbo,
                to_client=None,
                from_client=None,
                warehouses=[],
                unit_cost=None,
            )
        ],
        stock=fbo,
        stock_updated_at=updated_at if can_stock else None,
        stock_stale=bool(can_stock and updated_at and now() - updated_at > timedelta(hours=2)),
        missing_cost_variants=None,
    )


def matches(row, query):
    text = query.strip().casefold()
    return not text or any(
        text in str(value).casefold()
        for value in (
            row["title"],
            row["vendor_code"],
            row["external_id"],
            row["marketplace_code"],
            row["brand"],
            *row["barcodes"],
            *row.get("sku_aliases", []),
        )
    )


def products(
    db,
    vault,
    workspace_id,
    store,
    query,
    in_stock,
    missing_cost,
    can_stock,
    can_cost=False,
    currency="RUB",
):
    rows, stamp = snapshot(db, vault, workspace_id, store)
    from app.modules.finance.variant_costs import apply, book
    from app.modules.sync.schemas import moscow_today

    prices = book(db, vault, workspace_id, store.id, currency, moscow_today()) if can_cost else {}
    items = [
        item(row, store, stamp, can_stock)
        for row in rows or []
        if matches(row, query)
        and (not in_stock or any(row["channels"][key]["quantity"] > 0 for key in ("fbo", "fbs")))
    ]
    if can_cost:
        items = [apply(card, prices, moscow_today()) for card in items]
    if missing_cost:
        items = [card for card in items if card.missing_cost_variants]
    info = state(db, workspace_id, store.id)
    return (
        items,
        info["status"] in {"pending", "queued", "running"},
        rows is None or info["error_code"] is not None,
        info["error_code"],
    )


def models(
    db,
    vault,
    workspace_id,
    store,
    query,
    in_stock,
    missing_cost,
    can_stock,
    can_cost=False,
    currency="RUB",
):
    rows, stamp = snapshot(db, vault, workspace_id, store)
    from app.modules.catalog.model_service import overrides

    manual = overrides(db, vault, workspace_id, store.id)
    groups = defaultdict(list)
    for row in rows or []:
        chosen = manual.get(row["external_id"])
        key = (
            chosen["key"]
            if chosen
            else ("model:" + row["group_id"])
            if row["group_id"]
            else ("product:" + row["external_id"])
        )
        groups[key].append(row)
    result = []
    from app.modules.finance.variant_costs import apply, book
    from app.modules.sync.schemas import moscow_today

    prices = book(db, vault, workspace_id, store.id, currency, moscow_today()) if can_cost else {}
    for key, members in groups.items():
        if not any(matches(row, query) for row in members):
            continue
        if in_stock and not any(
            row["channels"][channel]["quantity"] > 0
            for row in members
            for channel in ("fbo", "fbs")
        ):
            continue
        cards = [
            item(row, store, stamp, can_stock)
            for row in sorted(members, key=lambda row: row["external_id"])
        ]
        if can_cost:
            cards = [apply(card, prices, moscow_today()) for card in cards]
        missing = sum(card.missing_cost_variants for card in cards) if can_cost else None
        if missing_cost and not missing:
            continue
        result.append(
            ProductModel(
                id=f"{store.id}:ozon:{key}",
                store_id=store.id,
                store_name=store.name,
                marketplace="ozon",
                title=next(
                    (
                        manual[row["external_id"]]["title"]
                        for row in members
                        if row["external_id"] in manual and manual[row["external_id"]]["title"]
                    ),
                    cards[0].title,
                ),
                brand=cards[0].brand,
                grouping="manual"
                if key.startswith("manual:")
                else "marketplace"
                if key.startswith("model:")
                else "single",
                products=cards,
                stock=sum(card.stock for card in cards) if can_stock else None,
                missing_cost_variants=missing,
            )
        )
    return result
