"""Stored accruals only. Currency-safe groups shared with the existing finance UI."""

import json
from collections import defaultdict
from decimal import Decimal

from app.modules.accounts.models import Store
from app.modules.catalog.ozon_read import snapshot
from app.modules.finance import ozon_costs
from app.modules.finance.marketplace_models import MarketplaceFinanceDay
from app.modules.finance.models import ExternalExpense
from app.modules.finance.overview import (
    FinanceGroup,
    FinanceLine,
    FinanceOverview,
    FinanceTaxes,
    FinanceTotals,
    add,
    percent,
)
from app.modules.finance.ozon_facts import INCOME_GROUPS, TITLES, line_group, money
from app.modules.finance.ozon_jobs import aad
from app.modules.finance.precision import money_precision
from app.modules.finance.service import expense_view
from app.modules.insights.marketplace_models import OzonAnalyticsSync
from app.modules.sync.schemas import moscow_today
from sqlalchemy import select


@money_precision()
def report(db, vault, wid, sid, start, end, currency, can_profit=True):
    saved = db.scalars(
        select(MarketplaceFinanceDay)
        .where(
            MarketplaceFinanceDay.workspace_id == wid,
            MarketplaceFinanceDay.store_id == sid,
            MarketplaceFinanceDay.day.between(start, end),
        )
        .order_by(MarketplaceFinanceDay.day)
    ).all()
    lines = defaultdict(lambda: {"amount": Decimal(0), "title": ""})
    amounts = {key: Decimal(0) for key in ("seller_revenue", "buyer_revenue", "settlement")}
    unknown_buyer = False
    records = 0
    days = []
    for row in saved:
        value = json.loads(vault.open(row.ciphertext, aad(wid, sid, row.day)))
        records += value["records"]
        days.append((row.day, value))
        facts = value["currencies"].get(currency)
        if facts is None:
            continue
        for key in amounts:
            if facts[key] is None:
                unknown_buyer = True
            else:
                amounts[key] += Decimal(facts[key])
        for item in facts["lines"]:
            target = lines[(line_group(item), item["key"])]
            target["title"] = item["title"]
            target["amount"] += Decimal(item["amount"])
    known = bool(saved)
    revenue = money(amounts["seller_revenue"]) if known else None
    groups, expenses = [], Decimal(0)
    for key, title in TITLES.items():
        values = [
            FinanceLine(
                key=line_key,
                title=item["title"],
                amount=money(item["amount"] if key in INCOME_GROUPS else -item["amount"]),
            )
            for (group, line_key), item in lines.items()
            if group == key
        ]
        total = sum((Decimal(item.amount) for item in values), Decimal(0))
        if key not in INCOME_GROUPS:
            expenses += total
        # No fee rows on a confirmed empty day means zero, not unknown.
        value = money(total) if known else None
        groups.append(
            FinanceGroup(
                key=key,
                title=title,
                amount=value,
                share_percent=percent(value, revenue),
                lines=values,
            )
        )
    store = db.get(Store, sid)
    catalog, _ = snapshot(db, vault, wid, store) if can_profit else (None, None)
    costs = (
        ozon_costs.calculate(db, vault, store, catalog, days, currency, end)
        if can_profit
        else {"amount": None, "complete": False, "missing_variants": 0}
    )
    cogs = money(costs["amount"]) if costs["amount"] is not None else None
    groups.append(
        FinanceGroup(
            key="cogs",
            title="Себестоимость",
            amount=cogs,
            share_percent=percent(cogs, revenue),
            lines=[],
        )
    )
    external_rows = db.scalars(
        select(ExternalExpense)
        .where(
            ExternalExpense.workspace_id == wid,
            ExternalExpense.store_id == sid,
            ExternalExpense.expense_date.between(start, end),
            ExternalExpense.currency == currency,
            ExternalExpense.deleted_at.is_(None),
        )
        .limit(10001)
    ).all()
    if len(external_rows) > 10000:
        from fastapi import HTTPException

        raise HTTPException(422, "Слишком много внешних расходов. Уточните период.")
    external = defaultdict(lambda: Decimal(0))
    for row in external_rows:
        value = expense_view(vault, row)
        external[value.category] += Decimal(value.amount)
    manual = sum(external.values(), Decimal(0))
    advertisement = external.pop("advertising", Decimal(0))
    if advertisement:
        group = next(group for group in groups if group.key == "advertising")
        group.lines.append(
            FinanceLine(
                key="external_advertising", title="Внешняя реклама", amount=money(advertisement)
            )
        )
        group.amount = add(group.amount, money(advertisement))
        group.share_percent = percent(group.amount, revenue)
    expenses += manual
    if cogs is not None:
        expenses += costs["amount"]
    labels = {
        "packaging": "Упаковка",
        "fulfillment": "Фулфилмент",
        "transport": "Перевозка",
        "rent": "Аренда",
        "salary": "Зарплата",
        "other": "Прочее",
    }
    groups.append(
        FinanceGroup(
            key="external",
            title="Внешние расходы",
            amount=money(sum(external.values(), Decimal(0))),
            share_percent=percent(money(sum(external.values(), Decimal(0))), revenue),
            lines=[
                FinanceLine(key="external_" + key, title=labels.get(key, key), amount=money(value))
                for key, value in external.items()
            ],
        )
    )
    job = db.get(OzonAnalyticsSync, (wid, sid, "finance"))
    span = (end - start).days + 1
    invalid = sum(len(value.get("issues", [])) for _, value in days)
    covered = len(saved) == span and end < moscow_today() and not invalid
    errors = [job.error_code] if job and job.error_code else []
    if invalid:
        errors.append("ozon_invalid_record")
    loading = bool(
        (
            len(saved) < span
            or (can_profit and any(value.get("cost_basis") != "accrual_v1" for _, value in days))
        )
        and job
        and not errors
        and (job.cursor is not None or job.status in {"pending", "queued", "running"})
    )
    result = FinanceOverview(
        date_from=start,
        date_to=end,
        currency=currency,
        updated_at=min((row.updated_at for row in saved), default=None),
        is_partial=not covered,
        is_loading=loading,
        period_covered=covered,
        expenses_exclude_cogs=cogs is None,
        total_stores=1,
        data_sources=["ozon_accruals"],
        known_days=len(saved),
        source_errors=errors,
        totals=FinanceTotals(
            storage_total=money(
                -sum(
                    (
                        item["amount"]
                        for (group, key), item in lines.items()
                        if group == "warehouse"
                        and key not in {"ozon_SupplyInbound", "ozon_MicroFulfillmentSupply"}
                    ),
                    Decimal(0),
                )
            )
            if known
            else None,
            seller_revenue=revenue,
            marketplace_revenue=money(amounts["buyer_revenue"])
            if known and not unknown_buyer
            else None,
            expenses_before_tax=money(expenses) if known else None,
            profit_before_tax=money(
                amounts["seller_revenue"]
                + sum(
                    (
                        item["amount"]
                        for (group, key), item in lines.items()
                        if group == "compensations"
                    ),
                    Decimal(0),
                )
                - expenses
            )
            if can_profit
            and covered
            and costs["complete"]
            and not any(
                key == "ozon_unreconciled" and item["amount"]
                for (group, key), item in lines.items()
            )
            else None,
            settlement=money(amounts["settlement"]) if known else None,
        ),
        groups=groups,
        taxes=FinanceTaxes(
            configured_stores=0, total_stores=1, vat=None, tax=None, net_profit=None, notes=[]
        ),
        notes=(
            [f"Нет себестоимости или истории продажи: {costs['missing_variants']} вариантов."]
            if can_profit and costs["missing_variants"]
            else []
        ),
    )

    return apply_taxes(db, wid, sid, result)


def apply_taxes(db, wid, sid, report):
    from app.modules.finance.economics import tax_estimate
    from app.modules.insights.compute import tax_changed, tax_setting

    setting = tax_setting(db, wid, sid, report.date_to)
    if setting is None:
        return report
    report.taxes.configured_stores = 1
    if tax_changed(db, wid, sid, report.date_from, report.date_to):
        report.taxes.notes = [
            "В периоде менялись налоговые настройки. Выберите период с одним режимом."
        ]
        return report
    values = report.totals
    fees = next((group.amount for group in report.groups if group.key == "fees"), None)
    payout = (
        Decimal(values.seller_revenue) - Decimal(fees)
        if values.seller_revenue is not None and fees is not None
        else None
    )
    profit = Decimal(values.profit_before_tax) if values.profit_before_tax is not None else None
    vat, tax, notes = tax_estimate(
        setting,
        revenue=Decimal(values.marketplace_revenue)
        if values.marketplace_revenue is not None
        else None,
        payout=payout,
        profit=profit,
        income_adjustment=next(
            (
                Decimal(group.amount) if group.amount is not None else None
                for group in report.groups
                if group.key == "compensations"
            ),
            None,
        ),
    )
    report.taxes.vat = money(vat) if vat is not None else None
    report.taxes.tax = money(tax) if tax is not None else None
    report.taxes.net_profit = (
        money(profit - vat - tax)
        if profit is not None and vat is not None and tax is not None
        else None
    )
    report.taxes.notes = notes
    return report


@money_precision()
def merge(reports):
    first = reports[0]
    totals = {
        field: add(*(getattr(row.totals, field) for row in reports))
        for field in FinanceTotals.model_fields
    }
    if any(row.expenses_exclude_cogs for row in reports):
        values = []
        for row in reports:
            value = row.totals.expenses_before_tax
            if not row.expenses_exclude_cogs:
                cogs = next((group.amount for group in row.groups if group.key == "cogs"), None)
                value = (
                    money(Decimal(value) - Decimal(cogs))
                    if value is not None and cogs is not None
                    else None
                )
            values.append(value)
        totals["expenses_before_tax"] = add(*values)
    groups = []
    keys = list(dict.fromkeys(group.key for row in reports for group in row.groups))
    for key in keys:
        selected = [
            next((group for group in row.groups if group.key == key), None) for row in reports
        ]
        present = [group for group in selected if group]
        amount = add(*(group.amount for group in present))
        # A missing provider category is zero only after that provider has some confirmed data.
        if any(
            group is None and row.totals.seller_revenue is None
            for row, group in zip(reports, selected, strict=True)
        ):
            amount = None
        detail = []
        for row, group in zip(reports, selected, strict=True):
            if group:
                prefix = "Ozon" if "ozon_accruals" in row.data_sources else "WB"
                detail.extend(
                    item.model_copy(
                        update={
                            "key": prefix + ":" + item.key,
                            "title": prefix + " · " + item.title,
                        }
                    )
                    for item in group.lines
                )
        groups.append(
            FinanceGroup(
                key=key,
                title=TITLES.get(key, "Сервисы" if key == "services" else present[0].title),
                amount=amount,
                share_percent=percent(amount, totals["seller_revenue"]),
                lines=detail,
            )
        )
    return FinanceOverview(
        date_from=first.date_from,
        date_to=first.date_to,
        currency=first.currency,
        updated_at=min((row.updated_at for row in reports if row.updated_at), default=None),
        is_partial=any(row.is_partial for row in reports),
        is_loading=any(row.is_loading for row in reports),
        period_covered=all(row.period_covered for row in reports),
        expenses_exclude_cogs=any(row.expenses_exclude_cogs for row in reports),
        total_stores=sum(row.total_stores for row in reports),
        totals=FinanceTotals(**totals),
        groups=groups,
        data_sources=list(dict.fromkeys(source for row in reports for source in row.data_sources)),
        known_days=min(
            (row.known_days for row in reports if row.known_days is not None), default=None
        ),
        source_errors=list(dict.fromkeys(error for row in reports for error in row.source_errors)),
        taxes=FinanceTaxes(
            configured_stores=sum(row.taxes.configured_stores for row in reports),
            total_stores=sum(row.total_stores for row in reports),
            **{
                field: add(*(getattr(row.taxes, field) for row in reports))
                for field in ("vat", "tax", "net_profit")
            },
            notes=[],
        ),
        notes=list(dict.fromkeys(note for row in reports for note in row.notes)),
    )
