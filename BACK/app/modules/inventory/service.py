"""Stock cover forecast and supply plan from snapshots and published daily demand.

Demand is non-cancelled WB orders when the orders report covers the whole window (stock
leaves the warehouse at order time), otherwise WB buyouts. A cancelled order never
reduces stock in the forecast. Days with a known zero stock are excluded from the rate.
"""

import json
import math
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select

from app.db.tenant import scope
from app.integrations.wildberries.data import Source
from app.modules.auth.dependencies import now
from app.modules.inventory.models import InventorySnapshot
from app.modules.inventory.projection import snapshot_aad
from app.modules.sync.analytics import known_days, metric_context
from app.modules.sync.models import WBDailyMetric
from app.modules.sync.schemas import moscow_today

WINDOW = 30
CRITICAL_DAYS = 7
LOW_DAYS = 14
SOURCE_STALE_AFTER = timedelta(days=2)


def latest_day(db, workspace_id, store_id):
    return db.scalar(
        select(func.max(InventorySnapshot.day)).where(
            *scope(InventorySnapshot, workspace_id, store_id), InventorySnapshot.channel == "fbo"
        )
    )


def snapshots(db, vault, workspace_id, store_id, start, end, nm_ids=None):
    query = select(InventorySnapshot).where(
        *scope(InventorySnapshot, workspace_id, store_id),
        InventorySnapshot.day.between(start, end),
        InventorySnapshot.channel == "fbo",
    )
    if nm_ids:
        query = query.where(InventorySnapshot.nm_id.in_(nm_ids))
    for row in db.scalars(query.execution_options(yield_per=500)):
        yield (
            row.day,
            row.nm_id,
            json.loads(
                vault.open(row.ciphertext, snapshot_aad(workspace_id, store_id, row.day, row.nm_id))
            ),
        )


def daily_sales(db, vault, workspace_id, store_id, start, end, source=Source.SALES):
    """Published operational demand per SKU and day: [units, buyer-paid amount, missing prices].

    SALES: buyouts. ORDERS: orders minus cancellations (units that left the stock).
    """
    units, amount = ("sales", "sales_amount")
    if source == Source.ORDERS:
        units, amount = ("orders", "orders_amount")
    result = defaultdict(lambda: defaultdict(lambda: [Decimal(0), Decimal(0), Decimal(0)]))
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
        values = json.loads(
            vault.open(
                row.ciphertext,
                metric_context(
                    workspace_id,
                    store_id,
                    row.source,
                    row.dataset,
                    row.day,
                    row.nm_id,
                    row.currency,
                ),
            )
        )
        cell = result[row.nm_id][row.day]
        cell[0] += Decimal(values.get(units, 0)) - Decimal(values.get("cancellations", 0))
        cell[1] += Decimal(values.get(amount, 0)) - Decimal(values.get("cancellations_amount", 0))
        cell[2] += Decimal(values.get("missing_prices", 0))
    return result


def demand(db, vault, workspace_id, store_id, start, end):
    """(basis, daily demand). Orders when they cover the whole window, else buyouts."""
    first, through = known_days(db, workspace_id, store_id, Source.ORDERS)
    if first and first <= start and through >= end:
        return "orders", daily_sales(db, vault, workspace_id, store_id, start, end, Source.ORDERS)
    return "buyouts", daily_sales(db, vault, workspace_id, store_id, start, end)


def status_for(stock, rate, cover):
    if rate == 0:
        return "no_sales" if stock else "inactive"
    if stock == 0:
        return "out_of_stock"
    if cover <= CRITICAL_DAYS:
        return "critical"
    if cover <= LOW_DAYS:
        return "low"
    return "ok"


def source_info(current, observed_days, basis="buyouts"):
    """When WB stock data was actually taken, and how much history the forecast has."""
    as_of = next((values.get("as_of") for values in current.values() if values.get("as_of")), None)
    moment = datetime.fromisoformat(as_of) if as_of else None
    return {
        "stock_as_of": as_of,
        "observed_days": observed_days,
        "source_stale": moment is None or now() - moment > SOURCE_STALE_AFTER,
        "demand_basis": basis,
    }


def forecast(db, vault, workspace_id, store_id, window=WINDOW):
    """(snapshot day, items, source info). Zero-stock days come only from real observations."""
    day = latest_day(db, workspace_id, store_id)
    if day is None:
        return None, [], source_info({}, 0)
    end = moscow_today() - timedelta(days=1)
    start = end - timedelta(days=window - 1)
    basis, sales = demand(db, vault, workspace_id, store_id, start, end)
    current, zero_days, observed = {}, defaultdict(set), set()
    for snap_day, nm_id, values in snapshots(db, vault, workspace_id, store_id, start, day):
        observed.add(snap_day)
        if snap_day == day:
            current[nm_id] = values
        if values["stock"] == 0:
            zero_days[nm_id].add(snap_day)
    items = []
    for nm_id in sorted(set(current) | set(sales)):
        values = current.get(nm_id, {"stock": 0, "to_client": 0, "from_client": 0})
        units = sum((cell[0] for cell in sales[nm_id].values()), Decimal(0))
        amount = sum((cell[1] for cell in sales[nm_id].values()), Decimal(0))
        # A day without stock and without sales says nothing about demand.
        empty_days = {d for d in zero_days[nm_id] if start <= d <= end and d not in sales[nm_id]}
        in_stock_days = max(1, window - len(empty_days))
        rate = units / in_stock_days
        stock = values["stock"]
        # stock / (units / days) computed as one exact fraction: no rounding drift at whole days.
        cover = Decimal(stock) * in_stock_days / units if units else None
        average_price = amount / units if units else None
        lost = (
            (rate * len(empty_days) * average_price).quantize(Decimal("1"), ROUND_HALF_UP)
            if average_price is not None and empty_days
            else None
        )
        items.append(
            {
                "nm_id": nm_id,
                "stock": stock,
                "in_way_to_client": values["to_client"],
                "in_way_from_client": values["from_client"],
                "warehouses": dict(values.get("warehouses", {})),
                "sizes": dict(values.get("sizes", {})),
                "sold_units": int(units),
                "in_stock_days": in_stock_days,
                "out_of_stock_days": len(empty_days),
                "daily_rate": format(rate.quantize(Decimal("0.01")), "f"),
                "days_of_cover": int(cover) if cover is not None else None,
                "stockout_date": (day + timedelta(days=int(cover))).isoformat()
                if cover is not None and stock
                else None,
                "average_price": format(average_price.quantize(Decimal("0.01")), "f")
                if average_price is not None
                else None,
                "lost_revenue_estimate": format(lost, "f") if lost is not None else None,
                "status": status_for(stock, rate, cover),
                "demand_by_warehouse": dict(values.get("demand_by_warehouse", {})),
                "demand_by_size": dict(values.get("demand_by_size", {})),
            }
        )
    return day, items, source_info(current, len(observed), basis)


def split(total, shares):
    """Integer allocation by share with the largest remainder; the sum always equals total."""
    weight = sum(shares.values())
    if total <= 0 or not weight:
        return {}
    raw = {key: Decimal(total) * value / weight for key, value in shares.items()}
    result = {key: int(value) for key, value in raw.items()}
    for key in sorted(raw, key=lambda k: (-(raw[k] - result[k]), k))[
        : total - sum(result.values())
    ]:
        result[key] += 1
    return {key: value for key, value in result.items() if value}


def supply_plan(items, *, lead_time_days, cover_days, safety_days, nm_ids=None):
    plan = []
    horizon = lead_time_days + cover_days + safety_days
    for item in items:
        if nm_ids and item["nm_id"] not in nm_ids:
            continue
        rate = Decimal(item["daily_rate"])
        if not rate:
            continue
        # Stock in transit to buyers is already sold; returns in transit are not counted.
        need = rate * horizon - item["stock"]
        quantity = max(0, math.ceil(need))
        before_arrival = item["stock"] - rate * lead_time_days
        plan.append(
            {
                "nm_id": item["nm_id"],
                "quantity": quantity,
                "daily_rate": item["daily_rate"],
                "stock": item["stock"],
                "horizon_days": horizon,
                "stockout_before_arrival": before_arrival < 0,
                "by_warehouse": split(quantity, item["demand_by_warehouse"]),
                "by_size": split(quantity, item["demand_by_size"]),
                "explanation": (
                    f"{item['daily_rate']} шт./день × {horizon} дн. "
                    f"(доставка {lead_time_days} + запас {cover_days} + страховка {safety_days}) "
                    f"− остаток {item['stock']} = {quantity} шт."
                ),
            }
        )
    plan.sort(key=lambda row: (not row["stockout_before_arrival"], -row["quantity"]))
    return plan


def history(db, vault, workspace_id, store_id, start: date, end: date, nm_id: str | None):
    totals = defaultdict(lambda: {"stock": 0, "to_client": 0, "from_client": 0})
    for day, _, values in snapshots(
        db, vault, workspace_id, store_id, start, end, [nm_id] if nm_id else None
    ):
        for field, key in (
            ("stock", "stock"),
            ("to_client", "to_client"),
            ("from_client", "from_client"),
        ):
            totals[day][field] += values[key]
    return [{"day": day.isoformat(), **values} for day, values in sorted(totals.items())]
