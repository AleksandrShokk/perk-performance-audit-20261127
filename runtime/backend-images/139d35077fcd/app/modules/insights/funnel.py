"""WB card funnel: card opens -> cart -> orders -> buyouts, by day and by SKU (last 360 days).

Figures come from the WB sales-funnel report. WB attributes buyouts, cancellations and
returns to the ORDER day, so recent days keep gaining buyouts while deliveries complete;
`buyouts_maturing_from` marks those days. Days outside completed imports are null.
Amounts are shown only when the whole result is in one currency.
"""

import json
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select

from app.db.tenant import scope
from app.integrations.wildberries.data import Source
from app.modules.finance.economics import money
from app.modules.insights.funnel_days import datasets
from app.modules.sync.analytics import FUNNEL_FIELDS, metric_context
from app.modules.sync.models import SyncRun, SyncSchedule, WBDailyMetric
from app.modules.sync.schemas import history_limits, moscow_today

PRODUCT_LIMIT = 500
MATURING_DAYS = 14
SUMS = ("order_sum", "buyout_sum", "cancel_sum")


def percent(part, whole):
    if not whole:
        return None
    return format((Decimal(part) / Decimal(whole) * 100).quantize(Decimal("0.1")), "f")


def view(values, currency_known):
    opens, carts, orders = (int(values[f]) for f in ("open_count", "cart_count", "order_count"))
    buyouts, cancels = int(values["buyout_count"]), int(values["cancel_count"])

    def amount(field):
        return money(values[field]) if currency_known and not values["missing_" + field] else None

    return {
        "opens": opens,
        "carts": carts,
        "orders": orders,
        "buyouts": buyouts,
        "cancellations": cancels,
        "wishlist": int(values["wishlist_count"]),
        "orders_amount": amount("order_sum"),
        "buyouts_amount": amount("buyout_sum"),
        "cancellations_amount": amount("cancel_sum"),
        "add_to_cart_percent": percent(carts, opens),
        "cart_to_order_percent": percent(orders, carts),
        "open_to_order_percent": percent(orders, opens),
        # WB definition: excludes units still on their way to the buyer.
        "buyout_percent": percent(buyouts, buyouts + cancels),
    }


def unknown():
    return {key: None for key in view(defaultdict(Decimal), True)}


def known_days(windows, start, end):
    days = set()
    for window in windows:
        day = max(date.fromisoformat(window["date_from"]), start)
        right = min(date.fromisoformat(window["date_to"]), end)
        while day <= right:
            days.add(day)
            day += timedelta(days=1)
    return days


def preparing(start, end):
    """An uncomputed snapshot is unknown, never an empty or zero-sales report."""
    span = (end - start).days + 1
    return {
        "status": "preparing",
        "is_loading": False,
        "period_days": span,
        "known_days": 0,
        "currency": None,
        "buyouts_by": "order_date",
        "buyouts_maturing_from": None,
        "totals": unknown(),
        "daily": [
            {"day": (start + timedelta(days=i)).isoformat(), **unknown()} for i in range(span)
        ],
        "products": [],
        "products_truncated": False,
    }


def report(
    db,
    vault,
    workspace_id,
    store_id,
    start,
    end,
    *,
    product_limit=PRODUCT_LIMIT,
    include_labels=True,
):
    selected = datasets(db, workspace_id, store_id, start, end)
    known = set(selected)
    per_day = defaultdict(lambda: defaultdict(Decimal))
    per_product = defaultdict(lambda: defaultdict(Decimal))
    totals = defaultdict(Decimal)
    currencies = set()
    rows = db.execute(
        select(
            WBDailyMetric.day,
            WBDailyMetric.dataset,
            WBDailyMetric.nm_id,
            WBDailyMetric.currency,
            WBDailyMetric.ciphertext,
        )
        .where(
            *scope(WBDailyMetric, workspace_id, store_id),
            WBDailyMetric.source == Source.FUNNEL,
            WBDailyMetric.dataset.in_(set(selected.values())),
            WBDailyMetric.day.between(start, end),
        )
        .execution_options(yield_per=5000)
    )
    for row in rows:
        if selected.get(row.day) != row.dataset:
            continue
        aad = metric_context(
            workspace_id,
            store_id,
            Source.FUNNEL,
            row.dataset,
            row.day,
            row.nm_id,
            row.currency,
        )
        values = json.loads(vault.open(row.ciphertext, aad))
        if Decimal(values.get("records", 0)) <= 0:
            continue
        currencies.add(row.currency)
        for field in (*FUNNEL_FIELDS, *SUMS, *("missing_" + s for s in SUMS)):
            value = Decimal(values.get(field, 0))
            for target in (per_day[row.day], per_product[row.nm_id], totals):
                target[field] += value
    single = len(currencies) <= 1
    span = (end - start).days + 1
    yesterday = moscow_today() - timedelta(days=1)
    ranked = sorted(
        per_product.items(),
        key=lambda item: (-item[1]["order_count"], -item[1]["open_count"], item[0]),
    )
    active = db.scalar(
        select(SyncRun.id)
        .where(
            *scope(SyncRun, workspace_id, store_id),
            SyncRun.source == Source.FUNNEL,
            SyncRun.status.in_(["queued", "running"]),
        )
        .limit(1)
    )
    plan = db.get(SyncSchedule, (workspace_id, store_id, Source.FUNNEL))
    pending = active is not None or (
        plan is not None
        and plan.enabled
        and not plan.error_code
        and (
            not plan.recent_completed
            or (
                plan.history_from
                and plan.backfill_to
                and plan.backfill_to >= max(start, plan.history_from)
            )
        )
    )
    from app.modules.insights.product_labels import enrich

    native_floor = history_limits()[Source.FUNNEL]["date_from"]
    available = {
        start + timedelta(days=i) for i in range(span) if start + timedelta(days=i) >= native_floor
    } | known
    return {
        "history_available_from": min(available).isoformat() if available else str(native_floor),
        "available_days": len(available),
        "is_loading": bool(available - known and pending),
        "status": "ready" if len(known) == span else "partial" if known else "no_data",
        "period_days": span,
        "known_days": len(known),
        "currency": next(iter(currencies)) if len(currencies) == 1 else None,
        "buyouts_by": "order_date",
        "buyouts_maturing_from": max(
            start, yesterday - timedelta(days=MATURING_DAYS - 1)
        ).isoformat()
        if end > yesterday - timedelta(days=MATURING_DAYS)
        else None,
        "totals": view(totals, single) if known else unknown(),
        "daily": [
            {
                "day": (start + timedelta(days=offset)).isoformat(),
                **(
                    view(per_day[start + timedelta(days=offset)], single)
                    if start + timedelta(days=offset) in known
                    else unknown()
                ),
            }
            for offset in range(span)
        ],
        "products": enrich(
            [{"nm_id": nm_id, **view(values, single)} for nm_id, values in ranked[:product_limit]],
            db,
            vault,
            workspace_id,
            store_id,
            "wildberries",
        )
        if include_labels
        else [{"nm_id": nm_id, **view(values, single)} for nm_id, values in ranked[:product_limit]],
        "products_truncated": product_limit is not None and len(ranked) > product_limit,
    }
