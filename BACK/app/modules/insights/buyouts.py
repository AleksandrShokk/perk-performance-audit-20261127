"""Buyouts (sales and returns) for any period since 2024-01-29, by the date they happened.

Each day takes ONE source, never both:
  sales_report   — WB operational sales report, while the day is inside its covered
                   90-day window (fresh, includes days not yet in a weekly report);
  finance_report — WB financial (realization) report rows grouped by sale date, for
                   older days. Such a day counts only when finance imports cover it and
                   at least REPORT_LAG_DAYS after it, so late-reported sales have arrived;
  null           — not covered: unknown, never zero.

Units are comparable across sources. Amounts are not: the sales report has the price paid
by the buyer, the financial report the retail price WB used for commission. They are
returned separately per basis and currency and never added together.
"""

import json
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select

from app.db.tenant import scope
from app.integrations.wildberries.data import Source
from app.modules.finance.economics import money
from app.modules.insights.service import REPORT_LAG_DAYS
from app.modules.sync.analytics import METRIC_FORMAT, coverage, known_days, metric_context
from app.modules.sync.models import WBDailyMetric, WBMetricVersion
from app.modules.sync.schemas import moscow_today

PRODUCT_LIMIT = 500
FIELDS = ("sales", "returns", "sales_amount", "returns_amount", "missing_prices")


def report_days(windows, start, end, yesterday):
    """Days whose sales can be taken from financial reports grouped by sale date."""
    result = set()
    for window in windows:
        left = max(date.fromisoformat(window["date_from"]), start)
        right = date.fromisoformat(window["date_to"])
        day = left
        while day <= min(right, end):
            if right >= min(day + timedelta(days=REPORT_LAG_DAYS), yesterday):
                result.add(day)
            day += timedelta(days=1)
    return result


def rows(db, vault, workspace_id, store_id, source, start, end):
    query = select(WBDailyMetric).where(
        *scope(WBDailyMetric, workspace_id, store_id),
        WBDailyMetric.source == source,
        WBDailyMetric.dataset == "published",
        WBDailyMetric.day.between(start, end),
    )
    for row in db.scalars(query.execution_options(yield_per=500)):
        aad = metric_context(
            workspace_id, store_id, row.source, row.dataset, row.day, row.nm_id, row.currency
        )
        yield row.day, row.nm_id, row.currency, json.loads(vault.open(row.ciphertext, aad))


def units(values):
    sales, returns = int(values["sales"]), int(values["returns"])
    return {"sales": sales, "returns": returns, "net_units": sales - returns}


def amounts(values):
    known = not values["missing_prices"]
    return {
        "sales_amount": money(values["sales_amount"]) if known else None,
        "returns_amount": money(values["returns_amount"]) if known else None,
        "net_amount": money(values["sales_amount"] - values["returns_amount"]) if known else None,
        "missing_prices": int(values["missing_prices"]),
    }


def report(db, vault, workspace_id, store_id, start, end):
    yesterday = moscow_today() - timedelta(days=1)
    first, through = known_days(db, workspace_id, store_id, Source.SALES)
    version = db.get(WBMetricVersion, (workspace_id, store_id))
    # Old aggregates have no sale-date fields until the background upgrade finishes.
    finance_ready = bool(version and version.format_version >= METRIC_FORMAT)
    finance_days = (
        report_days(coverage(db, workspace_id, store_id)[Source.FINANCE], start, end, yesterday)
        if finance_ready
        else set()
    )
    source_of = {}
    day = start
    while day <= end:
        if first and first <= day <= through:
            source_of[day] = "sales_report"
        elif day in finance_days:
            source_of[day] = "finance_report"
        day += timedelta(days=1)

    per_day = defaultdict(lambda: defaultdict(Decimal))
    per_product = defaultdict(lambda: defaultdict(Decimal))
    money_by = defaultdict(lambda: defaultdict(Decimal))
    totals = defaultdict(Decimal)
    missing_dates = Decimal(0)

    def add(day, nm_id, basis, currency, values):
        for field in ("sales", "returns"):
            for target in (per_day[day], per_product[nm_id], totals):
                target[field] += values[field]
        for field in ("sales_amount", "returns_amount", "missing_prices"):
            money_by[(basis, currency)][field] += values[field]

    if "sales_report" in source_of.values():
        for day, nm_id, _, values in rows(
            db, vault, workspace_id, store_id, Source.SALES, start, end
        ):
            if source_of.get(day) == "sales_report":
                add(day, nm_id, "buyer_paid", None, {f: Decimal(values.get(f, 0)) for f in FIELDS})
    if "finance_report" in source_of.values():
        for day, nm_id, currency, values in rows(
            db, vault, workspace_id, store_id, Source.FINANCE, start, end
        ):
            if source_of.get(day) != "finance_report" or "report_bydate_records" not in values:
                continue
            add(
                day,
                nm_id,
                "retail_price",
                currency,
                {f: Decimal(values.get("report_bydate_" + f, 0)) for f in FIELDS},
            )
            missing_dates += Decimal(values.get("report_bydate_missing_dates", 0))

    span = (end - start).days + 1
    known = len(source_of)
    ranked = sorted(
        per_product.items(),
        key=lambda item: (-(item[1]["sales"] - item[1]["returns"]), item[0]),
    )
    preparing = not finance_ready and known < span
    return {
        "status": "ready"
        if known == span
        else "preparing"
        if preparing
        else "partial"
        if known
        else "no_data",
        "period_days": span,
        "known_days": known,
        "sales_report_days": sum(v == "sales_report" for v in source_of.values()),
        "finance_report_days": sum(v == "finance_report" for v in source_of.values()),
        "report_lag_days": REPORT_LAG_DAYS,
        "rows_without_sale_date": int(missing_dates),
        "totals": units(totals) if known else {"sales": None, "returns": None, "net_units": None},
        "amounts": [
            {"basis": basis, "currency": currency, **amounts(values)}
            for (basis, currency), values in sorted(
                money_by.items(), key=lambda item: (item[0][0], item[0][1] or "")
            )
        ],
        "daily": [
            {
                "day": (start + timedelta(days=offset)).isoformat(),
                "source": source_of.get(start + timedelta(days=offset)),
                **(
                    units(per_day[start + timedelta(days=offset)])
                    if start + timedelta(days=offset) in source_of
                    else {"sales": None, "returns": None, "net_units": None}
                ),
            }
            for offset in range(span)
        ],
        "products": [{"nm_id": nm_id, **units(values)} for nm_id, values in ranked[:PRODUCT_LIMIT]],
        "products_truncated": len(ranked) > PRODUCT_LIMIT,
    }
