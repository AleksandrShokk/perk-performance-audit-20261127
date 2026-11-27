"""One dated recommendation rule, applied independently to native destinations."""

import json
from collections import Counter, defaultdict
from datetime import timedelta
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.integrations.wildberries.data import Source
from app.modules.auth.dependencies import now
from app.modules.catalog.ozon_read import item as ozon_item
from app.modules.catalog.ozon_read import snapshot as ozon_catalog
from app.modules.insights.marketplace_models import OzonAnalyticsSync
from app.modules.inventory.channel_cover import ozon_channel_rates
from app.modules.inventory.ozon_cover import read as ozon_cover
from app.modules.supplies.demand import calendar_rate
from app.modules.supplies.destinations.jobs import aad
from app.modules.supplies.destinations.models import (
    SupplyDestinationSnapshot,
    SupplyDestinationSync,
)
from app.modules.supplies.destinations.schemas import (
    SupplyDestination,
    SupplyDestinations,
)
from app.modules.supplies.fbs import quantities as fbs_quantities
from app.modules.supplies.incoming import read as incoming_read
from app.modules.supplies.packaging import apply as packaging_apply
from app.modules.supplies.packaging import multiples
from app.modules.supplies.schemas import ReplenishmentItem, ReplenishmentOverview
from app.modules.sync.models import SyncSchedule
from app.modules.sync.read import retained
from app.modules.sync.schemas import moscow_today


def candidates(db, vault, wid, store):
    return {
        row["nm_id"]: row
        for row in retained(db, vault, wid, store.id, Source.STOCK_HISTORY)
        if row.get("orders") is not None and row["orders"] > 0
    }


def refresh(db, vault, wid, stores):
    queued = 0
    for store in stores:
        if store.marketplace == "ozon":
            job = db.get(OzonAnalyticsSync, (wid, store.id, "stock_cover"))
            if job and job.status not in {"pending", "queued", "running"}:
                job.next_attempt_at = now()
                job.status = "pending"
                queued += 1
            continue
        plan = db.get(SyncSchedule, (wid, store.id, Source.SUPPLY_DEMAND))
        if not plan or not plan.enabled or not plan.requested_by:
            continue
        existing = {
            r.product_key: r
            for r in db.scalars(
                select(SupplyDestinationSync).where(
                    SupplyDestinationSync.workspace_id == wid,
                    SupplyDestinationSync.store_id == store.id,
                )
            )
        }
        for key in candidates(db, vault, wid, store):
            job = existing.get(key)
            if job and (
                job.status in {"pending", "queued", "running"}
                or (job.updated_at and now() - job.updated_at < timedelta(hours=6))
            ):
                continue
            end = moscow_today() - timedelta(days=1)
            if job:
                job.status, job.next_attempt_at, job.requested_by = (
                    "pending",
                    now(),
                    plan.requested_by,
                )
                job.date_from, job.date_to = end - timedelta(days=27), end
            else:
                statement = insert(SupplyDestinationSync).values(
                    workspace_id=wid,
                    store_id=store.id,
                    product_key=key,
                    requested_by=plan.requested_by,
                    status="pending",
                    date_from=end - timedelta(days=27),
                    date_to=end,
                    next_attempt_at=now(),
                )
                db.execute(statement.on_conflict_do_nothing())
            queued += 1
    return queued


def wb_data(db, vault, wid, store):
    catalog = {r["nm_id"]: r for r in retained(db, vault, wid, store.id, Source.CATALOG)}
    wanted = candidates(db, vault, wid, store)
    snapshots = db.scalars(
        select(SupplyDestinationSnapshot).where(
            SupplyDestinationSnapshot.workspace_id == wid,
            SupplyDestinationSnapshot.store_id == store.id,
        )
    ).all()
    jobs = db.scalars(
        select(SupplyDestinationSync).where(
            SupplyDestinationSync.workspace_id == wid,
            SupplyDestinationSync.store_id == store.id,
        )
    ).all()
    records = []
    for snapshot in snapshots:
        key = snapshot.product_key
        if key not in wanted:
            continue
        row = catalog.get(key, {})
        product = dict(
            id="",
            marketplace="wildberries",
            marketplace_code=key,
            demand_basis="wb_orders",
            store_id=store.id,
            store_name=store.name,
            nm_id=key,
            vendor_code=row.get("vendor_code", ""),
            title=row.get("title") or f"Товар {key}",
            photo=(row.get("photos") or [None])[0],
            colors=row.get("colors", []),
            barcodes=list(
                dict.fromkeys(b for size in row.get("sizes", []) for b in size["barcodes"])
            ),
        )
        values = json.loads(vault.open(snapshot.ciphertext, aad(wid, store.id, key)))
        values = calendar_destinations(values, calendar_rate(wanted[key]))
        for value in values:
            if not value.get("id", "").startswith("wb-office:"):
                continue
            records.append((product, value, snapshot.updated_at, [key]))
    return (
        records,
        len({s.product_key for s in snapshots if s.product_key in wanted}),
        len(wanted),
        any(j.status in {"pending", "queued", "running"} and j.product_key in wanted for j in jobs),
        sum(j.status == "error" and j.product_key in wanted for j in jobs),
    )


def ozon_data(db, vault, wid, store):
    catalog, stamp = ozon_catalog(db, vault, wid, store)
    source = ozon_cover(db, vault, wid, store.id)
    facts = source["products"]
    order_rates, demand_stamp = ozon_channel_rates(db, vault, wid, store.id, channel="all")
    owners = Counter(
        sku for row in catalog or [] for sku in set(row.get("channel_skus", {}).get("fbo", []))
    )
    records = []
    loaded, total = 0, 0
    for row in catalog or []:
        skus = set(row.get("channel_skus", {}).get("fbo", []))
        if not skus:
            continue
        total += 1
        if any(owners[s] != 1 for s in skus):
            continue
        groups = defaultdict(list)
        for sku in skus:
            for group in facts.get(sku, {}).get("destinations", []):
                groups[group["id"]].append(group)
        if groups:
            loaded += 1
        product = ozon_item(row, store, stamp, True)
        metadata = dict(
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
        )
        native = []
        for cid, values in groups.items():
            rates = [
                Decimal(v["daily_orders"]) if v["daily_orders"] is not None else None
                for v in values
            ]
            rate = (
                sum(rates, Decimal(0))
                if len(values) == len(skus) and all(r is not None for r in rates)
                else None
            )
            group = dict(
                id=cid,
                name=values[0]["name"],
                stock=sum(v["stock"] for v in values),
                daily_orders=str(rate) if rate is not None else None,
                warehouse_ids=list({w for v in values for w in v["warehouse_ids"]}),
            )
            native.append(group)
        aliases = (
            set(row.get("sku_aliases", []))
            | {row["marketplace_code"]}
            | {sku for group_skus in row.get("channel_skus", {}).values() for sku in group_skus}
        )
        rate = (
            sum((order_rates.get(sku, Decimal(0)) for sku in aliases), Decimal(0))
            if order_rates is not None
            else None
        )
        for group in calendar_destinations(native, rate):
            records.append(
                (
                    metadata,
                    group,
                    min(
                        (s for s in (source["updated_at"], demand_stamp) if s),
                        default=None,
                    ),
                    list(skus),
                )
            )
    return records, loaded, total, source["loading"], int(bool(source["error_code"]))


def calendar_destinations(groups, rate):
    """Native demand proportions; their total is bounded by actual 28-day orders."""
    values = [Decimal(g["daily_orders"]) if g["daily_orders"] is not None else None for g in groups]
    total = sum((v for v in values if v is not None), Decimal(0))
    known = rate is not None and all(v is not None for v in values)
    return [
        {
            **group,
            "daily_orders": str(rate * value / total)
            if known and total > 0
            else "0"
            if known and rate == 0
            else None,
        }
        for group, value in zip(groups, values, strict=True)
    ]


def reports(db, vault, wid, stores, *, target_days=30, lead_time_days=7, include_fbs=False):
    from app.modules.supplies.service import from_demand

    result = []
    processed = total = failures = 0
    loading = False
    for store in stores:
        records, done, count, busy, errors = (
            ozon_data if store.marketplace == "ozon" else wb_data
        )(db, vault, wid, store)
        processed += done
        total += count
        failures += errors
        loading |= busy
        groups = defaultdict(list)
        for record in records:
            groups[record[1]["id"]].append(record)
        incoming = incoming_read(
            db,
            vault,
            wid,
            store,
            today=moscow_today(),
            target_days=target_days,
            lead_time_days=lead_time_days,
        )
        rules = multiples(db, wid, [store])
        fbs = fbs_quantities(db, vault, wid, store) if include_fbs else {}
        known_warehouses = {w for _, value, _, _ in records for w in value["warehouse_ids"]}
        for cid, values in sorted(groups.items()):
            warehouses = {w for _, v, _, _ in values for w in v["warehouse_ids"]}
            native = incoming.for_warehouses(warehouses, known_warehouses)
            items = []
            unknown = no_orders = 0
            known = False
            for product, group, stamp, keys in values:
                raw = group["daily_orders"]
                if raw is None or group["stock"] is None:
                    unknown += 1
                    continue
                known = True
                rate = Decimal(raw)
                if rate <= 0:
                    no_orders += 1
                    continue
                product_key = product["id"] or product["nm_id"]
                fbs_stock = fbs.get(product_key, 0) if fbs is not None else None
                estimate = from_demand(
                    group["stock"],
                    rate,
                    target_days=target_days,
                    lead_time_days=lead_time_days,
                    arrivals=native.events(keys, stamp),
                    fbs_stock=fbs_stock,
                )
                if estimate and fbs is not None:
                    fbs[product_key] = (fbs_stock or 0) - estimate["fbs_reduction"]
                if estimate and estimate["quantity"]:
                    items.append(
                        ReplenishmentItem(
                            **product,
                            **estimate,
                            destination_id=cid,
                            destination_name=group["name"],
                            incoming_quantity=native.quantity(keys),
                        )
                    )
            items = packaging_apply(items, rules)
            items.sort(key=lambda i: (not i.urgent, Decimal(i.days_of_stock), i.id or i.nm_id))
            dates = [r[2] for r in values if r[2]]
            stale = any(now() - stamp > timedelta(days=2) for stamp in dates)
            report = ReplenishmentOverview(
                include_fbs=include_fbs,
                target_days=target_days,
                lead_time_days=lead_time_days,
                destination_id=cid,
                destination_name=values[0][1]["name"],
                recommended_units=sum(i.quantity for i in items) if known else None,
                product_count=len(items) if known else None,
                urgent_count=sum(i.urgent for i in items) if known else None,
                unknown_count=unknown,
                no_orders_count=no_orders,
                partial=unknown > 0
                or done < count
                or stale
                or not native.complete
                or (include_fbs and fbs is None),
                loading=busy,
                stale=stale,
                updated_at=min(dates) if dates else None,
                incoming_complete=native.complete,
                incoming_units=sum(native.quantities.values()) if native.complete else None,
                items=items,
                count=len(items),
                limit=len(items),
                offset=0,
            )
            result.append((store, report))
    return result, processed, total, loading, failures


def overview(db, vault, wid, stores, **parameters):
    values, done, total, loading, errors = reports(db, vault, wid, stores, **parameters)
    return SupplyDestinations(
        items=[
            SupplyDestination(
                id=r.destination_id,
                name=r.destination_name,
                store_id=s.id,
                store_name=s.name,
                marketplace=s.marketplace,
                recommended_units=r.recommended_units,
                product_count=r.product_count or 0,
                urgent_count=r.urgent_count or 0,
                partial=r.partial,
                updated_at=r.updated_at,
            )
            for s, r in values
        ],
        loaded_products=done,
        total_products=total,
        loading=loading,
        failed_products=errors,
    )


def selected(
    db,
    vault,
    wid,
    stores,
    destination_id,
    *,
    limit=3,
    offset=0,
    urgent_only=False,
    **parameters,
):
    if len(stores) != 1:
        raise HTTPException(422, "Выберите один кабинет для направления.")
    values, *_ = reports(db, vault, wid, stores, **parameters)
    report = next((r for _, r in values if r.destination_id == destination_id), None)
    if report is None:
        raise HTTPException(404, "Направление не найдено.")
    rows = [i for i in report.items if i.urgent] if urgent_only else report.items
    return report.model_copy(
        update={
            "items": rows[offset : offset + limit] if limit is not None else rows,
            "count": len(rows),
            "limit": limit if limit is not None else len(rows),
            "offset": offset,
        }
    )
