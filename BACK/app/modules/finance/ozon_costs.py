"""Resolve financial units against cost history, preserving original return cost dates."""

from collections import defaultdict
from decimal import Decimal

from sqlalchemy import select

from app.modules.finance.marketplace_models import MarketplaceRealization
from app.modules.finance.precision import money_precision
from app.modules.finance.variant_costs import book, resolve, sku_variants


def sale_dates(db, wid, sid, keys):
    result = defaultdict(set)
    keys = sorted(set(keys))
    for offset in range(0, len(keys), 1000):
        rows = db.execute(
            select(
                MarketplaceRealization.posting_key,
                MarketplaceRealization.sku,
                MarketplaceRealization.day,
            ).where(
                MarketplaceRealization.workspace_id == wid,
                MarketplaceRealization.store_id == sid,
                MarketplaceRealization.posting_key.in_(keys[offset : offset + 1000]),
            )
        )
        for key, sku, day in rows:
            result[(key, sku)].add(day)
    return result


@money_precision()
def calculate(db, vault, store, catalog, days, currency, end):
    prices = book(db, vault, store.workspace_id, store.id, currency, end)
    mapping = sku_variants(catalog, store.id)
    entries = [
        (day, item)
        for day, value in days
        for item in value.get("cost_items", [])
        if item["currency"] == currency
    ]
    original = sale_dates(
        db,
        store.workspace_id,
        store.id,
        [item["key"] for _, item in entries if (item.get("quantity") or 0) < 0],
    )
    amount, missing = Decimal(0), set()
    products, per_day = {}, {}
    missing_units = 0
    complete = bool(days) and all(value.get("cost_basis") == "accrual_v1" for _, value in days)
    for day, item in entries:
        variant = mapping.get(item["sku"])
        quantity = item["quantity"]
        cost = None
        product = products.setdefault(
            variant or "sku:" + item["sku"],
            {"known": Decimal(0), "complete": True, "missing_units": 0},
        )
        daily = per_day.setdefault(day, {"known": Decimal(0), "complete": True})
        if variant and quantity:
            if quantity > 0:
                cost = resolve(prices, variant, day)
            else:
                dates = original.get((item["key"], item["sku"]), set())
                candidates = {resolve(prices, variant, date) for date in dates}
                if len(candidates) == 1 and None not in candidates:
                    cost = next(iter(candidates))
        if cost is None:
            missing.add(variant or "sku:" + item["sku"])
            complete = False
            product["complete"] = daily["complete"] = False
            product["missing_units"] += abs(quantity or 1)
            missing_units += abs(quantity or 1)
        else:
            amount += cost * quantity
            product["known"] += cost * quantity
            daily["known"] += cost * quantity
    return {
        "products": products,
        "days": per_day,
        "missing_units": missing_units,
        "amount": amount if complete else None,
        "known": amount,
        "missing_variants": len(missing),
        "complete": complete,
    }
