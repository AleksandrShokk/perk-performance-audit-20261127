"""Native Ozon product ledger in the shared financial report contract. No guessed allocations."""

import json
from collections import defaultdict
from decimal import Decimal
from uuid import NAMESPACE_URL, uuid5

from app.modules.catalog.identifiers import product_key
from app.modules.catalog.ozon_read import snapshot
from app.modules.finance import ozon_costs, ozon_read
from app.modules.finance.marketplace_models import MarketplaceFinanceDay
from app.modules.finance.ozon_facts import INCOME_GROUPS, line_group, money
from app.modules.finance.ozon_jobs import aad
from app.modules.finance.precision import money_precision
from app.modules.finance.schemas import ProfitDay, ProfitProduct, ProfitReport, ProfitValues
from app.modules.finance.variant_costs import sku_variants
from sqlalchemy import select


def empty():
    return {
        "records": 0,
        "sales": 0,
        "returns": 0,
        "buyer_revenue": Decimal(0),
        "buyer_unknown": False,
        "lines": defaultdict(Decimal),
    }


def merge(target, source):
    target["records"] += source.get("records", 0)
    target["sales"] += source["sales"]
    target["returns"] += source["returns"]
    if source["buyer_revenue"] is None:
        target["buyer_unknown"] = True
    else:
        target["buyer_revenue"] += Decimal(source["buyer_revenue"])
    for line in source["lines"]:
        target["lines"][(line_group(line), line["key"])] += Decimal(line["amount"])


def values(ledger, cost, complete=True):
    lines = ledger["lines"]

    def group(key):
        return sum((amount for (name, _), amount in lines.items() if name == key), Decimal(0))

    sales, fees = group("sales"), -group("fees")
    expense = -sum(
        (amount for (key, _), amount in lines.items() if key not in INCOME_GROUPS), Decimal(0)
    )
    cogs = cost["known"] if cost["complete"] else None
    contribution = sales + group("compensations") - expense - cogs if cogs is not None else None
    revenue = None if ledger["buyer_unknown"] else ledger["buyer_revenue"]
    issues = {}
    if not cost["complete"]:
        issues["missing_cost_units"] = cost.get("missing_units", 1)
    if any(key == "ozon_unreconciled" and amount for (_, key), amount in lines.items()):
        contribution = None
        issues["unreconciled_adjustment"] = 1
    storage = -sum(
        (
            amount
            for (key, name), amount in lines.items()
            if key == "warehouse"
            and name not in {"ozon_SupplyInbound", "ozon_MicroFulfillmentSupply"}
        ),
        Decimal(0),
    )
    acceptance = -group("warehouse") - storage
    result = ProfitValues(
        records=ledger["records"],
        sales=ledger["sales"],
        returns=ledger["returns"],
        net_units=ledger["sales"] - ledger["returns"],
        revenue=money(revenue) if revenue is not None else None,
        for_pay=money(sales - fees),
        financial_details={
            "tax_income_adjustment": money(group("compensations")),
            "seller_revenue": money(sales),
            "fees_total": money(fees),
            "customer_payout": money(sales - fees),
            "wb_expenses_total": money(expense),
            "total_expenses": money(expense + cogs) if cogs is not None else None,
        },
        wb_expenses={
            "delivery_service": money(-group("logistics")),
            "paid_storage": money(storage),
            "paid_acceptance": money(acceptance),
            "penalty": money(-group("penalties")),
            "deduction": money(-group("other")),
        },
        settlement_estimate=money(sum(lines.values(), Decimal(0))),
        cogs=money(cogs) if cogs is not None else None,
        contribution_before_external_expenses=money(contribution)
        if contribution is not None
        else None,
        profit_before_tax=money(contribution) if contribution is not None and complete else None,
        margin_percent=money(contribution / revenue * 100)
        if contribution is not None and revenue
        else None,
        issues=issues,
        calculation_complete=complete and contribution is not None,
    )
    return result


@money_precision()
def report(db, vault, wid, store, start, end, currency, limit=100, offset=0, can_profit=True):
    sid = store.id
    overview = ozon_read.report(db, vault, wid, sid, start, end, currency, can_profit=can_profit)
    saved = db.scalars(
        select(MarketplaceFinanceDay)
        .where(
            MarketplaceFinanceDay.workspace_id == wid,
            MarketplaceFinanceDay.store_id == sid,
            MarketplaceFinanceDay.day.between(start, end),
        )
        .order_by(MarketplaceFinanceDay.day)
    ).all()
    days = [
        (row.day, json.loads(vault.open(row.ciphertext, aad(wid, sid, row.day)))) for row in saved
    ]
    ready = bool(days) and all(
        value.get("details_basis") == "accrual_products_v1" for _, value in days
    )
    catalog, _ = snapshot(db, vault, wid, store)
    mapping = sku_variants(catalog, sid)
    metadata = {}
    for row in catalog or []:
        for sku in [
            row["marketplace_code"],
            *row.get("sku_aliases", []),
            *(sku for codes in row.get("channel_skus", {}).values() for sku in codes),
        ]:
            if mapping.get(sku):
                metadata[mapping[sku]] = row
    costs = (
        ozon_costs.calculate(db, vault, store, catalog, days, currency, end)
        if can_profit
        else {"products": {}, "days": {}, "missing_units": 0}
    )
    from app.modules.finance.models import ExternalExpense
    from app.modules.finance.service import expense_view

    manual_by_day = defaultdict(Decimal)
    for row in db.scalars(
        select(ExternalExpense).where(
            ExternalExpense.workspace_id == wid,
            ExternalExpense.store_id == sid,
            ExternalExpense.currency == currency,
            ExternalExpense.expense_date.between(start, end),
            ExternalExpense.deleted_at.is_(None),
        )
    ):
        manual_by_day[row.expense_date] += Decimal(expense_view(vault, row).amount)
    ledgers = {}
    unassigned = empty()
    daily = []
    for day, data in days:
        if data.get("details_basis") != "accrual_products_v1":
            continue
        ledger = empty()
        for sku, item in data.get("product_details", {}).get(currency, {}).items():
            merge(ledger, item)
            if not sku:
                merge(unassigned, item)
            else:
                merge(ledgers.setdefault(mapping.get(sku) or "sku:" + sku, empty()), item)
        cogs = costs["days"].get(day, {"known": Decimal(0), "complete": can_profit})
        point = values(ledger, cogs, overview.period_covered)
        point.records = data["records"]
        point.external_expenses = money(manual_by_day[day])
        if point.financial_details["total_expenses"] is not None:
            point.financial_details["total_expenses"] = money(
                Decimal(point.financial_details["total_expenses"]) + manual_by_day[day]
            )
        if point.profit_before_tax is not None:
            point.profit_before_tax = money(Decimal(point.profit_before_tax) - manual_by_day[day])
        daily.append(ProfitDay(day=day, **point.model_dump()))
    products = []
    for key, ledger in ledgers.items():
        row = metadata.get(key)
        code = row["marketplace_code"] if row else key.removeprefix("sku:")
        identity = (
            product_key(sid, "ozon", row["external_id"])
            if row
            else str(uuid5(NAMESPACE_URL, f"perk:{sid}:ozon:sku:{code}"))
        )
        cogs = costs["products"].get(key, {"known": Decimal(0), "complete": can_profit})
        product = ProfitProduct(
            id=identity,
            marketplace="ozon",
            marketplace_code=code,
            nm_id="",
            title=row["title"] if row else "",
            vendor_code=row["vendor_code"] if row else None,
            barcodes=row["barcodes"] if row else [],
            **values(ledger, cogs, overview.period_covered).model_dump(),
        )
        products.append(product)
    products.sort(key=lambda item: (-Decimal(item.revenue or 0), item.id))
    total = empty()
    for ledger in ledgers.values():
        total["sales"] += ledger["sales"]
        total["returns"] += ledger["returns"]
    summary = ProfitValues(
        records=sum(value["records"] for _, value in days),
        sales=total["sales"],
        returns=total["returns"],
        net_units=total["sales"] - total["returns"],
        revenue=overview.totals.marketplace_revenue,
        for_pay=None,
        settlement_estimate=overview.totals.settlement,
        cogs=next((g.amount for g in overview.groups if g.key == "cogs"), None),
        profit_before_tax=overview.totals.profit_before_tax,
        calculation_complete=overview.period_covered
        and overview.totals.profit_before_tax is not None,
    )
    groups = {g.key: g.amount for g in overview.groups}
    summary.financial_details = {
        "tax_income_adjustment": groups.get("compensations"),
        "seller_revenue": overview.totals.seller_revenue,
        "fees_total": groups.get("fees"),
        "total_expenses": overview.totals.expenses_before_tax if summary.cogs is not None else None,
        "wb_expenses_total": money(
            sum(
                (
                    Decimal(line.amount)
                    for group in overview.groups
                    if group.key not in INCOME_GROUPS | {"cogs", "external"}
                    for line in group.lines
                    if not line.key.startswith("external_") and line.amount is not None
                ),
                Decimal(0),
            )
        ),
    }
    if overview.totals.seller_revenue is not None and groups.get("fees") is not None:
        summary.for_pay = money(Decimal(overview.totals.seller_revenue) - Decimal(groups["fees"]))
    manual = sum(
        (
            Decimal(line.amount)
            for group in overview.groups
            for line in group.lines
            if line.key.startswith("external_") and line.amount is not None
        ),
        Decimal(0),
    )
    summary.external_expenses = money(manual)
    if costs["missing_units"]:
        summary.issues["missing_cost_units"] = costs["missing_units"]
    if summary.profit_before_tax is not None:
        summary.contribution_before_external_expenses = money(
            Decimal(summary.profit_before_tax) + manual
        )
    if summary.profit_before_tax is not None and summary.revenue and Decimal(summary.revenue):
        summary.margin_percent = money(
            Decimal(summary.profit_before_tax) / Decimal(summary.revenue) * 100
        )
    unallocated = values(
        unassigned, {"known": Decimal(0), "complete": can_profit}, overview.period_covered
    )
    unallocated.external_expenses = money(manual)
    if unallocated.financial_details["total_expenses"] is not None:
        unallocated.financial_details["total_expenses"] = money(
            Decimal(unallocated.financial_details["total_expenses"]) + manual
        )
    if unallocated.profit_before_tax is not None:
        unallocated.profit_before_tax = money(Decimal(unallocated.profit_before_tax) - manual)
    if not can_profit:
        for item in [summary, unallocated, *products, *daily]:
            item.cogs = item.profit_before_tax = item.contribution_before_external_expenses = (
                item.margin_percent
            ) = None
            item.calculation_complete = False
            item.issues = {}
    return ProfitReport(
        date_from=start,
        date_to=end,
        currency=currency,
        status="ready" if ready else "preparing" if overview.is_loading or days else "no_data",
        is_partial=overview.is_partial,
        period_covered=overview.period_covered,
        updated_at=overview.updated_at,
        summary=summary,
        unassigned=unallocated,
        daily=daily,
        products=products[offset : offset + limit] if ready else [],
        product_count=len(products) if ready else 0,
        limit=limit,
        offset=offset,
    )
