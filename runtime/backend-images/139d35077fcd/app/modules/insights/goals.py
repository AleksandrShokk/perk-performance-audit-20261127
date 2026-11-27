"""Monthly plan/fact. The forecast is a linear run-rate, stated as such."""

import calendar
import json
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select

from app.db.tenant import scope
from app.modules.finance import economics
from app.modules.insights.models import StoreGoal
from app.modules.sync.schemas import moscow_today

METRICS = ("revenue", "profit", "net_profit", "units")


def goal_aad(workspace_id, store_id, month, metric):
    return f"perk-goal:v1:{workspace_id}:{store_id}:{month}:{metric}"


def targets(db, vault, workspace_id, store_id, month):
    rows = db.scalars(
        select(StoreGoal).where(*scope(StoreGoal, workspace_id, store_id), StoreGoal.month == month)
    ).all()
    return {
        row.metric: Decimal(
            json.loads(
                vault.open(row.ciphertext, goal_aad(workspace_id, store_id, month, row.metric))
            )["target"]
        )
        for row in rows
    }


def actual_values(report, setting):
    summary = report.summary
    net = economics.net_profit(setting, summary)["net_profit"]
    return {
        "revenue": economics.dec(summary.revenue),
        "profit": economics.dec(summary.profit_before_tax),
        "net_profit": economics.dec(net),
        "units": Decimal(summary.net_units) if report.status == "ready" else None,
    }


def progress(db, vault, workspace_id, store_id, month, report_for, setting_for):
    days = calendar.monthrange(month.year, month.month)[1]
    month_end = month.replace(day=days)
    through = min(month_end, moscow_today() - timedelta(days=1))
    goals = targets(db, vault, workspace_id, store_id, month)
    elapsed = (through - month).days + 1 if through >= month else 0
    actual = {}
    status = "not_started"
    if elapsed:
        report = report_for(month, through)
        status = report.status
        actual = actual_values(report, setting_for(through))
    rows = []
    for metric in METRICS:
        value = actual.get(metric)
        target = goals.get(metric)
        forecast = value / elapsed * days if value is not None and elapsed else None
        rows.append(
            {
                "metric": metric,
                "target": economics.money(target),
                "actual": economics.money(value),
                "forecast": economics.money(forecast),
                "percent_of_target": format((value / target * 100).quantize(Decimal("0.1")), "f")
                if value is not None and target
                else None,
                "forecast_percent_of_target": format(
                    (forecast / target * 100).quantize(Decimal("0.1")), "f"
                )
                if forecast is not None and target
                else None,
            }
        )
    return {
        "month": month.isoformat(),
        "days_in_month": days,
        "days_elapsed": elapsed,
        "through": through.isoformat() if elapsed else None,
        "finance_status": status,
        "forecast_method": "linear_run_rate",
        "metrics": rows,
    }


def month_start(value: date) -> date:
    return value.replace(day=1)
