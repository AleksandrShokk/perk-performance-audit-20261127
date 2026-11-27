"""Planning uses observed orders per calendar day, without extrapolating stockouts."""

from datetime import date
from decimal import Decimal, localcontext

WINDOW = 28


def calendar_rate(row):
    if row is None or row.get("orders") is None:
        return None
    days = (date.fromisoformat(row["date_to"]) - date.fromisoformat(row["date_from"])).days + 1
    if days != WINDOW:
        return None
    with localcontext() as ctx:
        ctx.prec = 64
        return Decimal(row["orders"]) / days
