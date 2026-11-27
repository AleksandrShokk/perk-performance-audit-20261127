"""Current stock coverage from the marketplace report, with no local waiting period."""

from datetime import date
from decimal import ROUND_HALF_UP, Decimal, localcontext

WINDOW = 28


def order_rate(row):
    """Ordered units per day in stock. WB reports out-of-stock time in hours."""
    if row is None or row["orders"] is None or row["missing_hours"] is None:
        return None
    days = (date.fromisoformat(row["date_to"]) - date.fromisoformat(row["date_from"])).days + 1
    available_hours = days * 24 - row["missing_hours"]
    if days != WINDOW or available_hours <= 0:
        return None
    with localcontext() as ctx:
        ctx.prec = 64
        return Decimal(row["orders"]) * 24 / available_hours


def stock_cover(rows):
    """Sum inventory / sum demand; never average per-product coverage numbers.

    Sold-out products don't shorten the coverage of unrelated inventory. Products
    with stock but unknown demand make the total unknown, rather than silently
    disappearing from it. The report supplies the stock at its own refresh time.
    """
    stock, demand, sold_out_demand = 0, Decimal(0), False
    with localcontext() as ctx:
        ctx.prec = 64
        for row in rows:
            if row["stock"] is None:
                return None
            if row["stock"] == 0:
                rate = order_rate(row)
                sold_out_demand |= rate is not None and rate > 0
                continue
            rate = order_rate(row)
            if rate is None:
                return None
            stock += row["stock"]
            demand += rate
        if demand <= 0:
            return "0.00" if stock == 0 and sold_out_demand else None
        return format(
            (Decimal(stock) / demand).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), "f"
        )


def product_cover(row):
    if row is None or row["stock"] is None:
        return None
    rate = order_rate(row)
    if rate is None or rate <= 0:
        return None
    with localcontext() as ctx:
        ctx.prec = 64
        return format(
            (Decimal(row["stock"]) / rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), "f"
        )


def product_coverage(row, *, loading=False):
    """Explain an unavailable value without treating unknown orders as zero."""
    days = product_cover(row)
    if days is not None:
        return days, "ready"
    if row is None:
        return None, "loading" if loading else "no_data"
    period = (date.fromisoformat(row["date_to"]) - date.fromisoformat(row["date_from"])).days + 1
    if period == WINDOW and row["orders"] == 0:
        return None, "no_orders"
    return None, "no_data"


def coverage_summary(rows):
    """A provider anomaly leaves a visible partial result, never a false total."""
    known, partial = [], False
    for row in rows:
        if row["stock"] is None or (row["stock"] > 0 and order_rate(row) is None):
            partial = True
        else:
            known.append(row)
    return stock_cover(known), partial
