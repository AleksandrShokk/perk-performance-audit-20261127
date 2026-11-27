"""Enrich a postings report only with confirmed native traffic days."""

import json

from sqlalchemy import select

from app.modules.insights.extra_jobs import aad
from app.modules.insights.extra_models import MarketplaceTrafficDay

FIELDS = ("opens", "carts", "add_to_cart_percent", "cart_to_order_percent", "open_to_order_percent")


def percent(part, whole):
    from decimal import Decimal

    return (
        format((Decimal(part) / Decimal(whole) * 100).quantize(Decimal("0.1")), "f")
        if part is not None and whole
        else None
    )


def enrich(
    db,
    vault,
    wid,
    sid,
    start,
    end,
    totals,
    daily,
    available,
    products=None,
    sales_complete=True,
    coverage=None,
):
    # Read long periods in small batches; retain totals per SKU, not every SKU/day.
    rows = db.scalars(
        select(MarketplaceTrafficDay)
        .where(
            MarketplaceTrafficDay.workspace_id == wid,
            MarketplaceTrafficDay.store_id == sid,
            MarketplaceTrafficDay.day.between(start, end),
        )
        .execution_options(yield_per=7)
    )
    indexed, traffic = {}, {}
    for row in rows:
        values = json.loads(vault.open(row.ciphertext, aad(wid, sid, "traffic", row.day)))
        sku_values = values.pop("products", {})
        if values.get("version") == 2:
            add_traffic(traffic, sku_values)
        indexed[row.day.isoformat()] = values
    for row in daily:
        values = indexed.get(row["day"])
        if values:
            row.update({field: values.get(field) for field in ("impressions", "opens", "carts")})
            row["add_to_cart_percent"] = percent(row["carts"], row["opens"])
            row["cart_to_order_percent"] = percent(row["orders"], row["carts"])
            row["open_to_order_percent"] = percent(row["orders"], row["opens"])
    if indexed:
        available.extend(("opens", "carts"))
        for field in ("opens", "carts"):
            totals[field] = sum(row[field] for row in indexed.values())
        if all(row.get("impressions") is not None for row in indexed.values()):
            totals["impressions"] = sum(row["impressions"] for row in indexed.values())
            available.append("impressions")
    if len(indexed) == (end - start).days + 1:
        totals["add_to_cart_percent"] = percent(totals["carts"], totals["opens"])
        totals["cart_to_order_percent"] = (
            percent(totals["orders"], totals["carts"]) if sales_complete else None
        )
        totals["open_to_order_percent"] = (
            percent(totals["orders"], totals["opens"]) if sales_complete else None
        )
        available.extend(FIELDS[2:])
    if coverage is not None:
        coverage["products"] = sum(row.get("version") == 2 for row in indexed.values())
    if products is not None:
        enrich_products(products, indexed, (end - start).days + 1, sales_complete, traffic)
    return available


def add_traffic(target, products):
    for sku, values in products.items():
        totals = target.setdefault(sku, dict.fromkeys(("impressions", "opens", "carts"), 0))
        for field in totals:
            totals[field] += values[field]


def enrich_products(products, days, span, sales_complete, traffic=None):
    """Only a fully imported SKU/day window can confirm absent traffic as zero."""
    days = {day: row for day, row in days.items() if row.get("version") == 2}
    if not days:
        return
    complete = len(days) == span
    by_sku = {row["marketplace_code"]: row for row in products}
    if traffic is None:
        traffic = {}
        for day in days.values():
            add_traffic(traffic, day["products"])
    for sku in sorted(set(by_sku) | set(traffic)):
        item = by_sku.get(sku)
        if item is None:
            item = {
                "nm_id": "",
                "marketplace": "ozon",
                "marketplace_code": sku,
                "identifier_kind": "sku",
                "wishlist": None,
                "buyout_percent": None,
            }
            for field in ("orders", "buyouts", "cancellations"):
                item[field] = 0 if sales_complete else None
                item[field + "_amount"] = "0" if sales_complete else None
            products.append(item)
        if not complete and sku not in traffic:
            continue
        for field in ("impressions", "opens", "carts"):
            item[field] = traffic.get(sku, {}).get(field, 0)
        item["add_to_cart_percent"] = percent(item["carts"], item["opens"])
        item["cart_to_order_percent"] = (
            percent(item["orders"], item["carts"]) if sales_complete and complete else None
        )
        item["open_to_order_percent"] = (
            percent(item["orders"], item["opens"]) if sales_complete and complete else None
        )
