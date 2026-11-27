"""Replenishment from actual calendar orders, native stock and seller parameters."""

import math
from datetime import timedelta
from decimal import Decimal, localcontext

from app.integrations.wildberries.data import Source
from app.modules.auth.dependencies import now
from app.modules.supplies.demand import calendar_rate
from app.modules.supplies.incoming import read as read_incoming
from app.modules.supplies.packaging import apply as apply_packaging
from app.modules.supplies.packaging import multiples
from app.modules.supplies.schemas import (
    ReplenishmentItem,
    ReplenishmentOverview,
    SupplyCard,
    SupplyList,
)
from app.modules.sync.models import SyncSchedule
from app.modules.sync.read import retained, source_states
from app.modules.sync.schemas import moscow_today

TARGET_DAYS, LEAD_TIME_DAYS, URGENT_DAYS = 30, 7, 7


def recommendation(row, *, target_days=TARGET_DAYS, lead_time_days=LEAD_TIME_DAYS, arrivals=()):
    """Target cover AFTER arrival. Lost demand before arrival is not an order backlog."""
    rate = calendar_rate(row)
    return from_demand(
        row["stock"],
        rate,
        target_days=target_days,
        lead_time_days=lead_time_days,
        arrivals=arrivals,
    )


def from_demand(
    stock,
    rate,
    *,
    target_days=TARGET_DAYS,
    lead_time_days=LEAD_TIME_DAYS,
    arrivals=(),
    fbs_stock=0,
):
    if stock is None or rate is None or rate <= 0:
        return None
    with localcontext() as ctx:
        ctx.prec = 64
        stock_at_arrival = max(Decimal(0), Decimal(stock) - rate * lead_time_days)
        baseline = max(
            0,
            math.ceil((rate * target_days - stock_at_arrival).quantize(Decimal("0.000000000001"))),
        )
        # Simulate dated arrivals. A late shipment cannot cover an earlier stockout.
        balance, previous, needed = Decimal(stock), 0, Decimal(0)
        horizon = lead_time_days + target_days
        events = sorted((e for e in arrivals if 0 <= e.day <= horizon), key=lambda e: e.day)
        for event in events:
            if event.day <= lead_time_days:
                balance = max(Decimal(0), balance - rate * (event.day - previous))
            else:
                if previous < lead_time_days:
                    balance = max(Decimal(0), balance - rate * (lead_time_days - previous))
                    previous = lead_time_days
                balance -= rate * (event.day - previous)
                needed = max(needed, -balance)
            balance += event.quantity
            previous = event.day
        if previous < lead_time_days:
            balance = max(Decimal(0), balance - rate * (lead_time_days - previous))
            previous = lead_time_days
        needed = max(needed, rate * (horizon - previous) - balance)
        quantity = max(0, math.ceil(needed.quantize(Decimal("0.000000000001"))))
        incoming_reduction = baseline - quantity
        fbs_reduction = min(quantity, fbs_stock or 0)
        quantity -= fbs_reduction
        cover = Decimal(stock) / rate
        return {
            "stock": stock,
            "daily_orders": format(rate, "f"),
            "days_of_stock": format(cover.quantize(Decimal("0.01")), "f"),
            "quantity": quantity,
            "urgent": cover <= URGENT_DAYS,
            "incoming_reduction": incoming_reduction,
            "fbs_stock": fbs_stock,
            "fbs_reduction": fbs_reduction,
        }


def replenishment(
    db,
    vault,
    workspace_id,
    stores,
    *,
    urgent_only=False,
    limit=3,
    offset=0,
    target_days=TARGET_DAYS,
    lead_time_days=LEAD_TIME_DAYS,
    destination_id=None,
    include_fbs=False,
):
    if destination_id:
        from app.modules.supplies.destinations.service import selected

        return selected(
            db,
            vault,
            workspace_id,
            stores,
            destination_id,
            include_fbs=include_fbs,
            limit=limit,
            offset=offset,
            urgent_only=urgent_only,
            target_days=target_days,
            lead_time_days=lead_time_days,
        )
    items, dates = [], []
    incoming_complete, incoming_units = True, 0
    loading, partial, ready = False, False, False
    unknown, no_orders = 0, 0
    for store in stores:
        incoming = read_incoming(
            db,
            vault,
            workspace_id,
            store,
            today=moscow_today(),
            lead_time_days=lead_time_days,
            target_days=target_days,
        )
        incoming_complete &= incoming.complete
        incoming_units += sum(incoming.quantities.values()) if incoming.current else 0
        if store.marketplace == "ozon":
            from app.modules.supplies.ozon_replenishment import estimates

            def calculate(stock, rate, skus, stock_updated_at, fbs_stock=0, incoming=incoming):
                result = from_demand(
                    stock,
                    rate,
                    target_days=target_days,
                    lead_time_days=lead_time_days,
                    arrivals=incoming.events(skus, stock_updated_at),
                    fbs_stock=fbs_stock,
                )
                if result:
                    result["incoming_quantity"] = incoming.quantity(skus)
                return result

            value = estimates(db, vault, workspace_id, store, calculate, include_fbs=include_fbs)
            items.extend(value["items"])
            unknown += value["unknown"]
            no_orders += value["no_orders"]
            loading |= value["loading"]
            partial |= value["partial"]
            ready |= value["ready"]
            if value["updated_at"]:
                dates.append(value["updated_at"])
            continue
        states = source_states(
            db,
            workspace_id,
            store.id,
            [Source.STOCK_HISTORY, Source.SUPPLY_DEMAND, Source.FBS],
        )
        state = states[Source.STOCK_HISTORY]
        run = state.success
        loading |= state.loading
        if not run or not run.date_from or not run.date_to:
            partial = True
            continue
        dates.append(run.finished_at)
        catalog = {
            row["nm_id"]: row for row in retained(db, vault, workspace_id, store.id, Source.CATALOG)
        }
        stock_state = states[Source.SUPPLY_DEMAND]
        stock_run = stock_state.success
        ready |= stock_run is not None
        if stock_run:
            dates.append(stock_run.finished_at)
        fbo = {
            r["nm_id"]: r["stock"]
            for r in retained(db, vault, workspace_id, store.id, Source.SUPPLY_DEMAND)
            if stock_run
            and r["date_from"] == str(stock_run.date_from)
            and r["date_to"] == str(stock_run.date_to)
        }
        fbs = {}
        if include_fbs and states[Source.FBS].success:
            for record in retained(db, vault, workspace_id, store.id, Source.FBS):
                fbs[record["nm_id"]] = fbs.get(record["nm_id"], 0) + record["quantity"]
        fbs_known = bool(states[Source.FBS].success)
        if include_fbs and fbs_known:
            dates.append(states[Source.FBS].success.finished_at)
        loading |= stock_state.loading or (include_fbs and states[Source.FBS].loading)
        partial |= not stock_run or (include_fbs and not fbs_known)
        rows = {
            row["nm_id"]: row
            for row in retained(db, vault, workspace_id, store.id, Source.STOCK_HISTORY)
            if row["date_from"] == run.date_from.isoformat()
            and row["date_to"] == run.date_to.isoformat()
        }
        for article in sorted(set(catalog) | set(rows)):
            row = rows.get(article)
            if row is None:
                unknown += 1
                continue
            if row["orders"] == 0:
                no_orders += 1
                continue
            result = recommendation(
                {**row, "stock": fbo.get(article)},
                target_days=target_days,
                lead_time_days=lead_time_days,
                arrivals=incoming.events([article], stock_run.finished_at if stock_run else None),
            )
            if result:
                result["incoming_quantity"] = incoming.quantity([article])
                result["fbs_stock"] = (
                    (fbs.get(article, 0) if fbs_known else None) if include_fbs else 0
                )
                result["fbs_reduction"] = min(result["quantity"], result["fbs_stock"] or 0)
                result["quantity"] -= result["fbs_reduction"]
            if result is None:
                unknown += 1
                continue
            if not result["quantity"]:
                continue
            product = catalog.get(article, {})
            photos = product.get("photos", [])
            items.append(
                ReplenishmentItem(
                    store_id=store.id,
                    store_name=store.name,
                    nm_id=article,
                    vendor_code=product.get("vendor_code", ""),
                    title=product.get("title") or f"Товар {article}",
                    photo=photos[0] if photos else None,
                    colors=product.get("colors", []),
                    barcodes=list(
                        dict.fromkeys(
                            barcode
                            for size in product.get("sizes", [])
                            for barcode in size["barcodes"]
                        )
                    ),
                    **result,
                )
            )
    items = apply_packaging(items, multiples(db, workspace_id, stores))
    items.sort(
        key=lambda item: (
            not item.urgent,
            Decimal(item.days_of_stock),
            -item.quantity,
            str(item.store_id),
            item.id or item.nm_id,
        )
    )
    selection = [item for item in items if item.urgent] if urgent_only else items
    stale = any(now() - value > timedelta(days=2) for value in dates)
    return ReplenishmentOverview(
        include_fbs=include_fbs,
        target_days=target_days,
        lead_time_days=lead_time_days,
        incoming_units=incoming_units if incoming_complete else None,
        incoming_complete=incoming_complete,
        recommended_units=sum(item.quantity for item in items) if ready else None,
        product_count=len(items) if ready else None,
        urgent_count=sum(item.urgent for item in items) if ready else None,
        unknown_count=unknown,
        no_orders_count=no_orders,
        partial=partial or unknown > 0 or stale,
        loading=loading,
        stale=stale,
        updated_at=min(dates) if dates else None,
        items=selection[offset : offset + limit] if limit is not None else selection,
        count=len(selection),
        limit=limit if limit is not None else len(selection),
        offset=offset,
    )


def supplies(db, vault, workspace_id, stores, *, limit=3, offset=0):
    items, dates = [], []
    loading, incomplete, missing_access = False, False, False
    for store in stores:
        if store.marketplace == "ozon":
            import json

            from app.modules.insights.extra_jobs import aad
            from app.modules.insights.extra_models import MarketplaceSupplySnapshot
            from app.modules.insights.marketplace_models import OzonAnalyticsSync

            snapshot = db.get(MarketplaceSupplySnapshot, (workspace_id, store.id))
            job = db.get(OzonAnalyticsSync, (workspace_id, store.id, "supplies"))
            loading |= bool(job and job.status in {"pending", "queued", "running"})
            missing_access |= bool(job and job.error_code == "ozon_access_denied")
            if snapshot:
                dates.append(snapshot.updated_at)
                data = json.loads(
                    vault.open(snapshot.ciphertext, aad(workspace_id, store.id, "supplies"))
                )
                items.extend(
                    SupplyCard(store_id=store.id, store_name=store.name, **row)
                    for row in data["items"]
                    if row.get("status") not in {"accepted", "cancelled"}
                )
            else:
                incomplete = True
            continue
        state = source_states(db, workspace_id, store.id, [Source.SUPPLIES])[Source.SUPPLIES]
        run = state.success
        loading |= state.loading
        plan = db.get(SyncSchedule, (workspace_id, store.id, Source.SUPPLIES))
        missing_access |= bool(plan and plan.error_code in {"wb_scope_missing", "wb_access_denied"})
        if not run:
            incomplete = True
            continue
        dates.append(run.finished_at)
        items.extend(
            SupplyCard(store_id=store.id, store_name=store.name, **row)
            for row in retained(db, vault, workspace_id, store.id, Source.SUPPLIES)
        )
    # Active first; then the latest dates. Stable final identity prevents list jumps.
    items.sort(
        key=lambda item: (
            item.status == "accepted",
            -(item.planned_date or item.created_date).toordinal()
            if item.planned_date or item.created_date
            else 0,
            str(item.store_id),
            item.external_id,
        )
    )
    stale = any(now() - value > timedelta(days=2) for value in dates)
    return SupplyList(
        items=items[offset : offset + limit],
        count=len(items),
        limit=limit,
        offset=offset,
        loading=loading,
        incomplete=incomplete or stale,
        missing_access=missing_access,
        updated_at=min(dates) if dates else None,
        stale=stale,
    )
