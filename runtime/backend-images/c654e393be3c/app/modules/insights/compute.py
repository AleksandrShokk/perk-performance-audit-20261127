"""Snapshot builders shared by the API (first request) and the background refresh."""

from datetime import date, timedelta
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import select

from app.db.tenant import scope
from app.modules.accounts.models import Workspace
from app.modules.finance import economics, jobs
from app.modules.finance import report as reports
from app.modules.finance.models import TaxSetting
from app.modules.insights import buyouts, funnel, orders, returns
from app.modules.insights import service as insights
from app.modules.insights.goals import progress as goals_progress
from app.modules.inventory import service as inventory
from app.modules.sync.schemas import FINANCE_START, moscow_today

DEFAULT_DAYS = 30
ALL_PRODUCTS = 50000
MAX_PERIOD_DAYS = 1100


def default_period(days=DEFAULT_DAYS):
    end = moscow_today() - timedelta(days=1)
    return max(FINANCE_START, end - timedelta(days=days - 1)), end


def validated_period(date_from, date_to):
    """One rule for every report: both dates or none, ordered, within available history."""
    if (date_from is None) != (date_to is None):
        raise HTTPException(422, "Передайте обе даты периода или ни одной.")
    if date_from is None:
        return default_period()
    if date_from > date_to or date_to > moscow_today():
        raise HTTPException(422, "Выберите период с началом не позже конца и без будущих дат.")
    if date_from < FINANCE_START:
        raise HTTPException(422, f"История WB доступна с {FINANCE_START:%d.%m.%Y}.")
    if (date_to - date_from).days >= MAX_PERIOD_DAYS:
        raise HTTPException(422, "Выберите период не длиннее трёх лет.")
    return date_from, date_to


def period_params(date_from, date_to, currency=None, **extra):
    date_from, date_to = validated_period(date_from, date_to)
    return {
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "currency": currency,
        **extra,
    }


def finance_report(db, redis, vault, workspace_id, store_id, start, end, currency, limit):
    workspace = db.get(Workspace, workspace_id)
    currency = currency or workspace.currency
    result = reports.report(
        db, redis, vault, workspace_id, store_id, start, end, currency, limit, 0
    )
    if result.status == "preparing":
        jobs.enqueue(redis, vault, workspace_id, store_id, workspace.owner_user_id)
    return result


def tax_setting(db, workspace_id, store_id, day):
    return db.scalar(
        select(TaxSetting)
        .where(*scope(TaxSetting, workspace_id, store_id), TaxSetting.effective_from <= day)
        .order_by(TaxSetting.effective_from.desc())
        .limit(1)
    )


def dates(params):
    return date.fromisoformat(params["date_from"]), date.fromisoformat(params["date_to"])


def build(kind, params, db, redis, vault, workspace_id, store_id):
    if kind == "forecast":
        day, items, source = inventory.forecast(db, vault, workspace_id, store_id, params["window"])
        return {"snapshot_day": day.isoformat() if day else None, "items": items, **source}

    if kind == "seasonality":
        return insights.seasonality(
            db, vault, workspace_id, store_id, moscow_today(), params.get("nm_id")
        )

    if kind == "goals":
        month = date.fromisoformat(params["month"])
        return goals_progress(
            db,
            vault,
            workspace_id,
            store_id,
            month,
            lambda start, end: finance_report(
                db, redis, vault, workspace_id, store_id, start, end, None, 1
            ),
            lambda day: tax_setting(db, workspace_id, store_id, day),
        )

    start, end = dates(params)
    if kind == "funnel":
        return funnel.report(db, vault, workspace_id, store_id, start, end)
    if kind == "returns":
        return returns.report(db, vault, workspace_id, store_id, start, end)
    if kind == "buyouts":
        return buyouts.report(db, vault, workspace_id, store_id, start, end)
    if kind == "orders":
        return orders.report(
            db,
            vault,
            workspace_id,
            store_id,
            start,
            end,
            lambda source: sales_known_days(db, workspace_id, store_id, source),
        )
    currency = params.get("currency")
    if kind == "net_profit":
        report = finance_report(db, redis, vault, workspace_id, store_id, start, end, currency, 1)
        setting = tax_setting(db, workspace_id, store_id, end)
        return {
            **completeness(report),
            "revenue": report.summary.revenue,
            "tax_setting": tax_view(setting),
            "tax_setting_changed_in_period": tax_changed(db, workspace_id, store_id, start, end),
            **economics.net_profit(setting, report.summary),
        }

    report = finance_report(
        db, redis, vault, workspace_id, store_id, start, end, currency, ALL_PRODUCTS
    )
    if kind == "unit_economics":
        setting = tax_setting(db, workspace_id, store_id, end)
        target = Decimal(params["margin_target"])
        rows = [economics.unit_row(item, setting, target) for item in report.products]
        return {**completeness(report), "items": rows}

    if kind == "audit":
        previous = None
        if start - timedelta(days=1) >= FINANCE_START:
            previous_start = max(FINANCE_START, start - (end - start) - timedelta(days=1))
            previous = finance_report(
                db,
                redis,
                vault,
                workspace_id,
                store_id,
                previous_start,
                start - timedelta(days=1),
                currency,
                ALL_PRODUCTS,
            )
        _, items, _ = inventory.forecast(db, vault, workspace_id, store_id)
        return {
            **completeness(report),
            "revenue": report.summary.revenue,
            "findings": insights.audit(
                report, previous if previous and previous.status == "ready" else None, items
            ),
        }

    if kind == "dashboard":
        return dashboard(db, redis, vault, workspace_id, store_id, report, start, end)
    raise ValueError(kind)


def completeness(report):
    """Shared quality flags: freshness of the cache never replaces these."""
    return {
        "currency": report.currency,
        "status": report.status,
        "is_partial": report.is_partial,
        "period_covered": report.period_covered,
        "products_truncated": report.product_count > len(report.products),
    }


def tax_changed(db, workspace_id, store_id, start, end):
    return bool(
        db.scalar(
            select(TaxSetting.effective_from)
            .where(
                *scope(TaxSetting, workspace_id, store_id),
                TaxSetting.effective_from > start,
                TaxSetting.effective_from <= end,
            )
            .limit(1)
        )
    )


def tax_view(setting):
    if setting is None:
        return None
    return {
        "effective_from": setting.effective_from.isoformat(),
        "regime": setting.regime,
        "rate": format(setting.rate, "f"),
        "vat_rate": format(setting.vat_rate, "f"),
        "income_base": setting.income_base,
    }


def sales_known_days(db, workspace_id, store_id, source="sales"):
    from app.modules.sync.analytics import known_days

    return known_days(db, workspace_id, store_id, source)


def dashboard(db, redis, vault, workspace_id, store_id, report, start, end):
    """Everything the first screen needs, in one small payload."""
    week_start = end - timedelta(days=6)
    sales = inventory.daily_sales(db, vault, workspace_id, store_id, week_start, end)
    days = {}
    for per_day in sales.values():
        for day, values in per_day.items():
            cell = days.setdefault(day, [Decimal(0), Decimal(0), Decimal(0)])
            for index, value in enumerate(values):
                cell[index] += value
    first, through = sales_known_days(db, workspace_id, store_id)
    series = []
    for offset in range(7):
        day = week_start + timedelta(days=offset)
        known = bool(first and first <= day <= through)
        units, amount, missing = days.get(day, (Decimal(0), Decimal(0), Decimal(0)))
        series.append(
            {
                "day": day.isoformat(),
                "known": known,
                # Zero only for a confirmed day; one unpriced sale makes the amount unknown.
                "units": int(units) if known else None,
                "amount": economics.money(amount) if known and not missing else None,
            }
        )
    known_days = sum(item["known"] for item in series)
    sales_status = "ready" if known_days == 7 else "partial" if known_days else "no_data"
    snapshot_day, items, source = inventory.forecast(db, vault, workspace_id, store_id)
    counts = {}
    for item in items:
        counts[item["status"]] = counts.get(item["status"], 0) + 1
    urgent = sorted(
        (item for item in items if item["status"] in {"out_of_stock", "critical"}),
        key=lambda item: (item["days_of_cover"] or 0, item["nm_id"]),
    )[:5]
    setting = tax_setting(db, workspace_id, store_id, end)
    findings = insights.audit(report, None, items) if report.status == "ready" else []
    week = orders.report(
        db,
        vault,
        workspace_id,
        store_id,
        week_start,
        end,
        lambda source: sales_known_days(db, workspace_id, store_id, source),
    )
    return {
        "orders": {
            "status": week["status"],
            "yesterday": week["daily"][-1],
            "last_7_days": week["totals"],
        },
        "currency": report.currency,
        "finance_status": report.status,
        "finance_is_partial": report.is_partial,
        "period": {"date_from": start.isoformat(), "date_to": end.isoformat()},
        "sales": {
            "status": sales_status,
            "yesterday": series[-1],
            "last_7_days": series,
            "basis": "buyouts",
        },
        "finance": {
            "revenue": report.summary.revenue,
            **economics.net_profit(setting, report.summary),
        },
        "stock": {
            "snapshot_day": snapshot_day.isoformat() if snapshot_day else None,
            "stock_as_of": source["stock_as_of"],
            "source_stale": source["source_stale"],
            "counts": counts,
            "urgent": [
                {
                    "nm_id": item["nm_id"],
                    "stock": item["stock"],
                    "days_of_cover": item["days_of_cover"],
                    "status": item["status"],
                }
                for item in urgent
            ],
        },
        "top_findings": [
            {key: finding[key] for key in ("code", "severity", "title", "amount")}
            for finding in findings[:3]
        ],
    }


def warm_defaults():
    """Snapshots every user opens first. Refreshed after each publication."""
    params = period_params(None, None)
    month = moscow_today().replace(day=1).isoformat()
    return [
        ("dashboard", params),
        ("orders", params),
        ("funnel", params),
        ("returns", params),
        ("buyouts", params),
        ("buyouts", period_params(*default_period(365))),
        ("audit", params),
        ("unit_economics", {**params, "margin_target": "15"}),
        ("net_profit", params),
        ("forecast", {"window": inventory.WINDOW}),
        ("goals", {"month": month}),
    ]


def warm_report_periods():
    """Plain finance summaries (limit 100) the charts request by default."""
    return [default_period(days) for days in (7, 30, 90)]
