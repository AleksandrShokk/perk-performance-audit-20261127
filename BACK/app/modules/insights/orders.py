"""Orders, cancellations and buyouts from the WB operational reports (published aggregates).

Orders come from the WB orders report (90-day retention, refreshed every 30 minutes),
buyouts and returns from the sales report. The buyout rate here is a period ratio
(buyouts / non-cancelled orders in the same days), not a per-order cohort: an order made
at the end of the period may be bought out after it. Days without completed imports are
reported as unknown (null), never as zero.
"""

import json
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import select

from app.db.tenant import scope
from app.integrations.wildberries.data import Source
from app.modules.finance.economics import money
from app.modules.sync.analytics import metric_context
from app.modules.sync.models import WBDailyMetric

PRODUCT_LIMIT = 500
ORDER_FIELDS = ("orders", "orders_amount", "cancellations", "cancellations_amount")
SALE_FIELDS = ("sales", "sales_amount", "returns", "returns_amount")


def published(db, vault, workspace_id, store_id, source, start, end):
    rows = db.scalars(
        select(WBDailyMetric)
        .where(
            *scope(WBDailyMetric, workspace_id, store_id),
            WBDailyMetric.source == source,
            WBDailyMetric.dataset == "published",
            WBDailyMetric.day.between(start, end),
        )
        .execution_options(yield_per=500)
    )
    for row in rows:
        aad = metric_context(
            workspace_id, store_id, row.source, row.dataset, row.day, row.nm_id, row.currency
        )
        yield row.day, row.nm_id, json.loads(vault.open(row.ciphertext, aad))


def percent(part, whole):
    if not whole:
        return None
    return format((Decimal(part) / Decimal(whole) * 100).quantize(Decimal("0.1")), "f")


def view(values, orders_known=True, sales_known=True, rate_known=None):
    """One row of figures. Unknown coverage or an unpriced order makes amounts null."""
    rate_known = orders_known and sales_known if rate_known is None else rate_known
    orders, cancels = int(values["orders"]), int(values["cancellations"])
    sales, returns = int(values["sales"]), int(values["returns"])
    priced = not values["orders_missing_prices"]
    sales_priced = not values["sales_missing_prices"]
    net = orders - cancels
    amount = values["orders_amount"] - values["cancellations_amount"]
    return {
        "orders": orders if orders_known else None,
        "orders_amount": money(values["orders_amount"]) if orders_known and priced else None,
        "cancellations": cancels if orders_known else None,
        "cancellations_amount": money(values["cancellations_amount"])
        if orders_known and priced
        else None,
        "net_orders": net if orders_known else None,
        "net_orders_amount": money(amount) if orders_known and priced else None,
        "cancel_rate_percent": percent(cancels, orders) if orders_known else None,
        "average_order_value": money(values["orders_amount"] / orders)
        if orders_known and priced and orders
        else None,
        "buyouts": sales if sales_known else None,
        "buyouts_amount": money(values["sales_amount"]) if sales_known and sales_priced else None,
        "returns": returns if sales_known else None,
        "buyout_rate_percent": percent(sales, net) if rate_known else None,
    }


def empty():
    return defaultdict(Decimal)


def add(target, values, fields, missing_key):
    for field in fields:
        target[field] += Decimal(values.get(field, 0))
    target[missing_key] += Decimal(values.get("missing_prices", 0))


def report(db, vault, workspace_id, store_id, start, end, known_days):
    """known_days(source) -> (first, through) of complete coverage, or (None, None)."""
    orders_first, orders_through = known_days(Source.ORDERS)
    sales_first, sales_through = known_days(Source.SALES)

    def known(first, through, day):
        return bool(first and first <= day <= through)

    days, products = defaultdict(empty), defaultdict(empty)
    for day, nm_id, values in published(
        db, vault, workspace_id, store_id, Source.ORDERS, start, end
    ):
        if known(orders_first, orders_through, day):
            add(days[day], values, ORDER_FIELDS, "orders_missing_prices")
            add(products[nm_id], values, ORDER_FIELDS, "orders_missing_prices")
    for day, nm_id, values in published(
        db, vault, workspace_id, store_id, Source.SALES, start, end
    ):
        if known(sales_first, sales_through, day):
            add(days[day], values, SALE_FIELDS, "sales_missing_prices")
            add(products[nm_id], values, SALE_FIELDS, "sales_missing_prices")

    daily, totals = [], empty()
    orders_days = sales_days = both_days = 0
    day = start
    while day <= end:
        has_orders = known(orders_first, orders_through, day)
        has_sales = known(sales_first, sales_through, day)
        orders_days += has_orders
        sales_days += has_sales
        if has_orders and has_sales:
            both_days += 1
        for field, value in days[day].items():
            totals[field] += value
        daily.append({"day": day.isoformat(), **view(days[day], has_orders, has_sales)})
        day += timedelta(days=1)
    span = (end - start).days + 1
    # Sums cover known days only (counts below say how many). Comparing buyouts with orders
    # is meaningful only when both reports cover the same, whole period.
    has_orders, has_sales, comparable = bool(orders_days), bool(sales_days), both_days == span
    ranked = sorted(products.items(), key=lambda item: (-item[1]["orders"], item[0]))
    status = "ready" if comparable else "partial" if orders_days else "no_data"
    return {
        "status": status,
        "orders_known_days": orders_days,
        "sales_known_days": sales_days,
        "period_days": span,
        "orders_known_through": orders_through.isoformat() if orders_through else None,
        "buyout_rate_basis": "period_ratio",
        "totals": view(totals, has_orders, has_sales, comparable),
        "daily": daily,
        "products": [
            {"nm_id": nm_id, **view(values, has_orders, has_sales, comparable)}
            for nm_id, values in ranked[:PRODUCT_LIMIT]
        ],
        "products_truncated": len(ranked) > PRODUCT_LIMIT,
    }
