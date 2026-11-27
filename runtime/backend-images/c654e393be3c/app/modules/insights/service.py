"""Money audit and seasonality from published reports. Findings cite their own figures."""

import json
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select

from app.db.tenant import scope
from app.integrations.wildberries.data import Source
from app.modules.finance.economics import money
from app.modules.sync.analytics import METRIC_FORMAT, coverage, metric_context
from app.modules.sync.models import WBDailyMetric, WBMetricVersion

REPORT_LAG_DAYS = 30

TOP = 10


def dec(value):
    return None if value is None else Decimal(value)


def share(part, whole):
    return format((part / whole * 100).quantize(Decimal("0.1")), "f") if part and whole else None


def expense(values, *fields):
    amounts = [dec(values.wb_expenses.get(field)) for field in fields]
    return None if any(value is None for value in amounts) else sum(amounts, Decimal(0))


def top(products, key):
    ranked = [(item.nm_id, key(item)) for item in products]
    ranked = [(nm, value) for nm, value in ranked if value]
    ranked.sort(key=lambda row: (-abs(row[1]), row[0]))
    return [{"nm_id": nm, "amount": money(value)} for nm, value in ranked[:TOP]]


def finding(code, severity, title, explanation, amount=None, revenue=None, items=None, **extra):
    return {
        "code": code,
        "severity": severity,
        "title": title,
        "explanation": explanation,
        "amount": money(amount),
        "share_of_revenue_percent": share(amount, revenue),
        "items": items or [],
        **extra,
    }


def audit(report, previous, forecast_items):
    """Return findings ordered by severity. Unknown amounts produce no finding, not a zero."""
    summary, revenue = report.summary, dec(report.summary.revenue)
    findings = []

    penalties = expense(summary, "penalty", "deduction")
    if penalties:
        before = expense(previous.summary, "penalty", "deduction") if previous else None
        change = f" Прошлый период: {money(before)}." if before is not None else ""
        findings.append(
            finding(
                "penalties",
                "high" if before is not None and penalties > before * Decimal("1.5") else "medium",
                "Штрафы и удержания",
                "Сумма штрафов и удержаний WB по финансовым отчётам." + change,
                penalties,
                revenue,
                top(report.products, lambda p: expense(p, "penalty", "deduction")),
                previous_amount=money(before),
            )
        )

    storage = expense(summary, "paid_storage")
    dead = [item for item in forecast_items if item["status"] == "no_sales" and item["stock"] > 0]
    if storage or dead:
        findings.append(
            finding(
                "storage",
                "medium" if dead else "info",
                "Платное хранение и товары без продаж",
                f"Хранение по отчётам; {len(dead)} артикулов лежат на складах без продаж "
                "за 30 дней и продолжают оплачиваться.",
                storage,
                revenue,
                [
                    {"nm_id": item["nm_id"], "units": item["stock"]}
                    for item in sorted(dead, key=lambda i: -i["stock"])[:TOP]
                ],
                dead_stock_units=sum(item["stock"] for item in dead),
            )
        )

    losing = [
        (item, dec(item.contribution_before_external_expenses))
        for item in report.products
        if item.contribution_before_external_expenses is not None
        and Decimal(item.contribution_before_external_expenses) < 0
    ]
    if losing:
        findings.append(
            finding(
                "loss_making",
                "high",
                "Убыточные товары",
                f"{len(losing)} артикулов приносят отрицательный вклад после себестоимости "
                "и расходов WB.",
                -sum((value for _, value in losing), Decimal(0)),
                revenue,
                top(
                    [item for item, _ in losing],
                    lambda p: dec(p.contribution_before_external_expenses),
                ),
            )
        )

    missing = [item for item in report.products if item.issues.get("missing_cost_units")]
    if missing:
        affected = sum((dec(item.revenue) or Decimal(0) for item in missing), Decimal(0))
        findings.append(
            finding(
                "missing_cost",
                "high",
                "Нет себестоимости",
                f"Для {len(missing)} артикулов не загружена себестоимость — прибыль по ним "
                "неизвестна. Загрузите шаблон себестоимости.",
                affected,
                revenue,
                top(missing, lambda p: dec(p.revenue)),
            )
        )

    lost = [item for item in forecast_items if item["lost_revenue_estimate"]]
    stockouts = [item for item in forecast_items if item["status"] in {"out_of_stock", "critical"}]
    if lost or stockouts:
        lost_total = sum((Decimal(item["lost_revenue_estimate"]) for item in lost), Decimal(0))
        findings.append(
            finding(
                "stockouts",
                "high" if stockouts else "medium",
                "Упущенная выручка из-за отсутствия товара",
                "Оценка: скорость продаж × дни без остатка × средняя цена. "
                f"Сейчас закончились или закончатся в течение недели: {len(stockouts)}.",
                lost_total or None,
                revenue,
                [
                    {
                        "nm_id": item["nm_id"],
                        "amount": item["lost_revenue_estimate"],
                        "days_of_cover": item["days_of_cover"],
                    }
                    for item in sorted(
                        stockouts or lost, key=lambda i: (i["days_of_cover"] or 0, i["nm_id"])
                    )[:TOP]
                ],
                is_estimate=True,
            )
        )

    logistics = expense(summary, "delivery_service")
    if logistics and revenue and logistics / revenue > Decimal("0.15"):
        findings.append(
            finding(
                "logistics",
                "medium",
                "Высокая доля логистики",
                "Логистика превышает 15% выручки: проверьте габариты, локализацию и возвраты.",
                logistics,
                revenue,
                top(report.products, lambda p: expense(p, "delivery_service")),
            )
        )

    returns = [
        item
        for item in report.products
        if item.sales >= 10 and item.returns / item.sales > Decimal("0.3")
    ]
    if returns:
        findings.append(
            finding(
                "returns",
                "medium",
                "Много возвратов",
                "У этих товаров возвращают больше 30% продаж: проверьте размерную сетку, "
                "описание и отзывы.",
                items=[
                    {
                        "nm_id": item.nm_id,
                        "sales": item.sales,
                        "returns": item.returns,
                        "return_rate_percent": format(
                            (Decimal(item.returns) / item.sales * 100).quantize(Decimal("0.1")),
                            "f",
                        ),
                    }
                    for item in sorted(returns, key=lambda i: -i.returns / i.sales)[:TOP]
                ],
            )
        )
    order = {"high": 0, "medium": 1, "info": 2}
    findings.sort(key=lambda item: (order[item["severity"]], -(Decimal(item["amount"] or 0))))
    return findings


def month_start(day):
    return day.replace(day=1)


def next_month(day):
    return (day.replace(day=28) + timedelta(days=4)).replace(day=1)


def covered_months(db, workspace_id, store_id, end):
    """Calendar months fully inside successful finance imports."""
    months = set()
    for interval in coverage(db, workspace_id, store_id)[Source.FINANCE]:
        left = date.fromisoformat(interval["date_from"])
        right = min(date.fromisoformat(interval["date_to"]), end)
        cursor = month_start(left) if left.day == 1 else next_month(left)
        while next_month(cursor) - timedelta(days=1) <= right:
            months.add(cursor)
            cursor = next_month(cursor)
    return months


def seasonality(db, vault, workspace_id, store_id, today, nm_id=None):
    end = month_start(today) - timedelta(days=1)
    months = covered_months(db, workspace_id, store_id, end)
    if len(months) < 12:
        return {
            "status": "unavailable",
            "reason": "Нужен хотя бы год полной истории финансовых отчётов. "
            f"Сейчас полных месяцев: {len(months)}.",
            "covered_months": len(months),
            "months": [],
        }
    # Sale date when aggregates have it (format 3+); a month then needs reports for
    # REPORT_LAG_DAYS after it, because sales are reported days after they happen.
    version = db.get(WBMetricVersion, (workspace_id, store_id))
    by_sale_date = bool(version and version.format_version >= METRIC_FORMAT)
    field = "report_bydate_sales" if by_sale_date else "report_sales"
    if by_sale_date:
        reported_through = max(
            date.fromisoformat(interval["date_to"])
            for interval in coverage(db, workspace_id, store_id)[Source.FINANCE]
        )
        lag = timedelta(days=REPORT_LAG_DAYS)
        months = {m for m in months if next_month(m) - timedelta(days=1) + lag <= reported_through}
        if len(months) < 12:
            return {
                "status": "unavailable",
                "reason": "Нужен хотя бы год полной истории финансовых отчётов. "
                f"Сейчас полных месяцев: {len(months)}.",
                "covered_months": len(months),
                "months": [],
            }
    units = defaultdict(Decimal)
    query = select(WBDailyMetric).where(
        *scope(WBDailyMetric, workspace_id, store_id),
        WBDailyMetric.source == Source.FINANCE,
        WBDailyMetric.dataset == "published",
        WBDailyMetric.day.between(min(months), end),
    )
    if nm_id:
        query = query.where(WBDailyMetric.nm_id == nm_id)
    for row in db.scalars(query.execution_options(yield_per=500)):
        start = month_start(row.day)
        if start not in months:
            continue
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
        units[start] += Decimal(values.get(field, 0))
    by_month = defaultdict(list)
    for start in months:
        by_month[start.month].append(units[start])
    averages = {month: sum(values) / len(values) for month, values in by_month.items()}
    overall = sum(averages.values()) / len(averages) if averages else Decimal(0)
    rows = []
    for month in range(1, 13):
        if month not in averages:
            rows.append({"month": month, "index": None, "average_units": None, "years": 0})
            continue
        rows.append(
            {
                "month": month,
                "index": format((averages[month] / overall).quantize(Decimal("0.01")), "f")
                if overall
                else None,
                "average_units": format(averages[month].quantize(Decimal("0.1")), "f"),
                "years": len(by_month[month]),
            }
        )
    return {
        "status": "ready",
        "reason": None,
        "covered_months": len(months),
        "basis": "report_sales_by_sale_date" if by_sale_date else "report_sales",
        "months": rows,
    }
