"""Channel-matched stock and demand. No subtraction of availability-adjusted rates."""

import json
from datetime import timedelta
from decimal import Decimal, localcontext

from sqlalchemy import select

from app.modules.insights.marketplace_models import MarketplaceSalesDay
from app.modules.insights.ozon_jobs import sales_aad
from app.modules.sync.schemas import moscow_today


def ozon_channel_rates(db, vault, wid, sid, channel="fbs"):
    end = moscow_today() - timedelta(days=1)
    rows = db.scalars(
        select(MarketplaceSalesDay).where(
            MarketplaceSalesDay.workspace_id == wid,
            MarketplaceSalesDay.store_id == sid,
            MarketplaceSalesDay.day.between(end - timedelta(days=27), end),
        )
    ).all()
    if len(rows) != 28:
        return None, None
    totals = {}
    channels = ("fbo", "fbs") if channel == "all" else (channel,)
    for row in rows:
        value = json.loads(vault.open(row.ciphertext, sales_aad(wid, sid, row.day)))
        if "channel_orders" not in value:
            return None, None
        for key in channels:
            if key not in value["channel_orders"]:
                return None, None
            for sku, units in value["channel_orders"][key].items():
                totals[sku] = totals.get(sku, 0) + units
    return {sku: Decimal(units) / 28 for sku, units in totals.items()}, min(
        row.updated_at for row in rows
    )


def channel_position(units, rate):
    if units is None or rate is None:
        return None, "no_data"
    if rate == 0:
        return None, "no_orders"
    with localcontext() as context:
        context.prec = 64
        return format((Decimal(units) / rate).quantize(Decimal(".01")), "f"), "ready"


def channel_total(rows):
    partial = any(units is None or (units > 0 and rate is None) for units, rate in rows)
    known = [(units, rate) for units, rate in rows if units is not None and rate is not None]
    value, _ = channel_position(
        sum(units for units, _ in known), sum((rate for _, rate in known), Decimal(0))
    )
    return value, partial
