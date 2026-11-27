"""Bounded WB source precision, preserved through preview and published calculations."""

from contextlib import contextmanager
from decimal import ROUND_HALF_UP, Decimal, localcontext

MAX_AMOUNT_SCALE = 24
MONEY_PRECISION = 64  # 16 integer + 24 fractional digits, plus totals and quantity products.


@contextmanager
def money_precision():
    with localcontext() as context:
        context.prec = max(context.prec, MONEY_PRECISION)
        yield


def money(value):
    """Canonical rounding for displayed money; calculations keep source precision."""
    if value is None:
        return None
    with money_precision():
        return format(Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), "f")
