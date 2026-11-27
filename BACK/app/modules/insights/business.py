"""Workspace business view: only RLS-visible stores, stored reports, exact currency totals."""

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel
from sqlalchemy import and_, or_, select

from app.modules.accounts.access import allows
from app.modules.accounts.models import Workspace
from app.modules.accounts.reporting import reporting_stores
from app.modules.accounts.router import require_workspace
from app.modules.auth.dependencies import DB, FullIdentity
from app.modules.finance.models import FinanceProjection
from app.modules.finance.overview import FinanceOverview, build_overview, custom_expense_lines
from app.modules.finance.precision import money_precision
from app.modules.finance.projection import FORMAT
from app.modules.finance.router import SellerBalance, balance_snapshot, financial_report
from app.modules.finance.schemas import ProfitDay, ProfitReport, ProfitValues
from app.modules.insights import compute
from app.modules.insights.router import OrderFigures, served
from app.modules.sync.models import SyncRun
from app.modules.sync.schemas import moscow_today

router = APIRouter(prefix="/workspaces/{workspace_id}", tags=["Business"])


class BusinessStore(BaseModel):
    id: UUID
    name: str
    connection_status: str
    finance: ProfitReport
    balance: SellerBalance
    orders: OrderFigures | None = None
    orders_complete: bool = False
    metrics: dict[str, str | None] | None = None
    metrics_complete: bool = False


class BusinessDay(BaseModel):
    day: date
    orders: int | None
    buyouts: int | None
    orders_partial: bool
    buyouts_partial: bool


class BusinessReport(BaseModel):
    date_from: date
    date_to: date
    stores: list[BusinessStore]
    complete_stores: int
    total_stores: int
    finance: ProfitReport
    balances: list[SellerBalance]
    orders: OrderFigures | None
    metrics: dict[str, str | None] | None = None
    metrics_complete_stores: int = 0
    activity_daily: list[BusinessDay] = []


def merge_activity(reports, start, end):
    """Known counts are additive; unknown stores/days remain explicitly partial."""
    indexed = [{row["day"]: row for row in rows} for rows in reports]
    result = []
    day = start
    while day <= end:
        values = {"day": day}
        for field in ("orders", "buyouts"):
            samples = [rows.get(day.isoformat(), {}).get(field) for rows in indexed]
            known = [value for value in samples if value is not None]
            values[field] = sum(known) if known else None
            values[field + "_partial"] = len(known) != len(indexed) or not indexed
        result.append(BusinessDay(**values))
        day += timedelta(days=1)
    return result


def topic_metrics(topic, data):
    if topic == "stock":
        if not data.get("snapshot_day"):
            return None, False
        items = data["items"]
        return {
            "stock": str(sum(row["stock"] for row in items)),
            "to_client": str(sum(row["in_way_to_client"] for row in items)),
            "from_client": str(sum(row["in_way_from_client"] for row in items)),
            "urgent": str(
                sum(row["status"] in {"critical", "low", "out_of_stock"} for row in items)
            ),
        }, not data.get("source_stale", True)
    fields = (
        ("opens", "carts", "orders", "buyouts", "cancellations", "wishlist")
        if topic == "funnel"
        else ("sales", "returns", "net_units")
    )
    totals = data["totals"]
    return {
        field: str(totals[field]) if totals.get(field) is not None else None for field in fields
    }, data["status"] == "ready"


@money_precision()
def sum_values(rows):
    """Null is not zero. Non-additive margins are recomputed, never added."""
    if not rows:
        return ProfitValues()
    data = {}
    for field in ProfitValues.model_fields:
        values = [getattr(row, field) for row in rows]
        if field == "calculation_complete":
            data[field] = all(values)
        elif field == "margin_percent":
            continue
        elif field == "issues":
            issues = defaultdict(int)
            for value in values:
                for key, count in (value or {}).items():
                    issues[key] += count
            data[field] = dict(issues)
        elif isinstance(values[0], dict):
            data[field] = {
                key: None
                if any(value.get(key) is None for value in values)
                else format(sum((Decimal(value[key]) for value in values), Decimal(0)), "f")
                for key in values[0]
            }
        elif any(value is None for value in values):
            data[field] = None
        elif isinstance(values[0], int):
            data[field] = sum(values)
        else:
            data[field] = format(sum((Decimal(value) for value in values), Decimal(0)), "f")
    revenue, profit = data.get("revenue"), data.get("profit_before_tax")
    if revenue is not None and profit is not None and Decimal(revenue) > 0:
        data["margin_percent"] = format(Decimal(profit) / Decimal(revenue) * 100, ".4f")
    return ProfitValues(**data)


@money_precision()
def merge_finance(reports, start, end, currency):
    ready = [report for report in reports if report.status == "ready"]
    complete = bool(reports) and all(
        report.status == "ready" and report.period_covered and not report.is_partial
        for report in reports
    )
    daily = defaultdict(list)
    for report in ready:
        for row in report.daily:
            daily[row.day].append(row)
    summary = sum_values([report.summary for report in ready])
    if not complete:
        summary.calculation_complete = False
        summary.issues["incomplete_period"] = 1
        summary.profit_before_tax = summary.margin_percent = None
    return ProfitReport(
        date_from=start,
        date_to=end,
        currency=currency,
        status="ready" if ready else "preparing" if reports else "no_data",
        is_partial=bool(ready) and not complete,
        period_covered=complete,
        summary=summary,
        daily=[
            ProfitDay(day=day, **sum_values(rows).model_dump())
            for day, rows in sorted(daily.items())
        ],
        product_count=sum(report.product_count for report in ready),
        products=[],  # Product identities are scoped by store; see stores[].finance.products.
        limit=100,
        offset=0,
    )


@router.get("/business", response_model=BusinessReport, operation_id="businessReport")
@money_precision()
def business_report(
    workspace_id: UUID,
    date_from: date,
    date_to: date,
    request: Request,
    db: DB,
    identity: FullIdentity,
    currency: str = Query(default="RUB", pattern=r"^[A-Z]{3}$"),
    store_id: UUID | None = None,
    topic: Literal[
        "overview", "sales", "orders", "buyouts", "funnel", "stock", "profit", "finance"
    ] = "overview",
):
    """One store or the whole business; no WB calls. RLS limits every store and report read."""
    from fastapi import Response

    member = require_workspace(db, identity, workspace_id)
    stores = reporting_stores(
        db,
        workspace_id,
        store_id,
        by_created=True,
        limit=100,
        missing_ok=topic != "finance",
        feature="finance_details" if topic in {"finance", "sales", "profit"} else "reports",
    )
    result = []
    params = compute.period_params(date_from, date_to)
    balances = defaultdict(list)
    figures = []
    activity = []
    for store in stores:
        report = (
            financial_report(
                workspace_id,
                store.id,
                request,
                db,
                identity,
                date_from,
                date_to,
                currency,
                100,
                0,
                include_product_identity=topic != "finance",
            )
            if allows(member, "finance.read")
            else merge_finance([], date_from, date_to, currency)
        )
        balance = (
            balance_snapshot(db, request.app.state.vault, workspace_id, store.id)
            if allows(member, "finance.read") and store.marketplace == "wildberries"
            else SellerBalance()
        )
        if balance.currency:
            balances[balance.currency].append(balance)
        data, fresh = (
            ({}, None)
            if topic == "finance"
            or store.marketplace == "ozon"
            or not allows(member, "analytics.read")
            else served(
                request,
                Response(),
                db,
                identity,
                workspace_id,
                store.id,
                "orders",
                params,
                conditional=False,
            )
        )
        orders = OrderFigures(**data["totals"]) if fresh is not None else None
        activity.append(data["daily"] if fresh is not None else [])
        if orders:
            figures.append(orders)
        metrics, metrics_complete = None, False
        if topic in {"funnel", "buyouts", "stock"}:
            kind = "forecast" if topic == "stock" else topic
            topic_params = (
                {"window": min(90, max(7, (date_to - date_from).days + 1))}
                if topic == "stock"
                else params
            )
            details, detail_fresh = served(
                request,
                Response(),
                db,
                identity,
                workspace_id,
                store.id,
                kind,
                topic_params,
                conditional=False,
            )
            if detail_fresh is not None:
                metrics, metrics_complete = topic_metrics(topic, details)
        result.append(
            BusinessStore(
                id=store.id,
                name=store.name,
                connection_status=store.connection_status,
                finance=report,
                balance=balance,
                orders=orders,
                orders_complete=fresh is not None and data["status"] == "ready",
                metrics=metrics,
                metrics_complete=metrics_complete,
            )
        )
    summed_orders = None
    if figures:
        values = {}
        for field in OrderFigures.model_fields:
            samples = [getattr(row, field) for row in figures]
            if field.endswith("percent") or field == "average_order_value":
                values[field] = None
            elif field.endswith("amount"):
                # WB statistics do not return a currency for amounts. Never mix cabinets.
                values[field] = samples[0] if len(result) == 1 else None
            else:
                values[field] = None if any(value is None for value in samples) else sum(samples)
        ordered, bought = values.get("net_orders"), values.get("buyouts")
        rates_known = len(figures) == len(result) and all(row.orders_complete for row in result)
        if rates_known and ordered and bought is not None:
            values["buyout_rate_percent"] = format(Decimal(bought) / Decimal(ordered) * 100, ".4f")
        if rates_known and values.get("orders") and values.get("cancellations") is not None:
            values["cancel_rate_percent"] = format(
                Decimal(values["cancellations"]) / Decimal(values["orders"]) * 100, ".4f"
            )
        if len(result) == 1:
            values["average_order_value"] = figures[0].average_order_value
        summed_orders = OrderFigures(**values)
    totals = []
    for unit, rows in balances.items():
        values = {}
        for field in ("current", "for_withdraw"):
            amounts = [getattr(row, field) for row in rows]
            values[field] = (
                None
                if any(value is None for value in amounts)
                else format(sum((Decimal(value) for value in amounts), Decimal(0)), "f")
            )
        totals.append(
            SellerBalance(
                currency=unit,
                **values,
                updated_at=min((row.updated_at for row in rows if row.updated_at), default=None),
            )
        )
    merged_metrics = None
    available = [row.metrics for row in result if row.metrics is not None]
    if available:
        merged_metrics = {}
        for field in available[0]:
            samples = [row[field] for row in available]
            merged_metrics[field] = (
                None
                if any(value is None for value in samples)
                else format(sum((Decimal(value) for value in samples), Decimal(0)), "f")
            )
    if (
        merged_metrics is not None
        and topic == "funnel"
        and len({store.marketplace for store in result}) > 1
    ):
        for key in ("opens", "carts", "wishlist"):
            merged_metrics[key] = None
    return BusinessReport(
        date_from=date_from,
        date_to=date_to,
        stores=result,
        complete_stores=sum(
            row.finance.period_covered
            and not row.finance.is_partial
            and row.orders_complete
            and row.connection_status == "connected"
            for row in result
        ),
        total_stores=len(result),
        finance=merge_finance([row.finance for row in result], date_from, date_to, currency),
        balances=totals,
        orders=summed_orders,
        metrics=merged_metrics,
        metrics_complete_stores=sum(row.metrics_complete for row in result),
        activity_daily=merge_activity(activity, date_from, date_to)
        if allows(member, "analytics.read")
        else [],
    )


@router.get("/finance/overview", response_model=FinanceOverview, operation_id="financeOverview")
def finance_overview(
    workspace_id: UUID,
    date_from: date,
    date_to: date,
    request: Request,
    db: DB,
    identity: FullIdentity,
    currency: str | None = Query(default=None, pattern=r"^[A-Z]{3}$"),
    store_id: UUID | None = None,
):
    """Stored finance groups, both revenue bases, expenses and estimated taxes."""
    require_workspace(db, identity, workspace_id)
    currency = currency or db.get(Workspace, workspace_id).currency
    stores = reporting_stores(db, workspace_id, store_id, feature="finance")
    if any(store.marketplace == "ozon" for store in stores):
        from app.modules.finance import ozon_read
        from app.modules.insights.ozon_read import ensure_range

        compute.validated_period(date_from, date_to)
        if date_from < moscow_today() - timedelta(days=1099):
            from fastapi import HTTPException

            raise HTTPException(422, "Для финансов Ozon выберите последние три года.")
        profit_visible = allows(require_workspace(db, identity, workspace_id), "profit.read")
        reports = []
        for store in stores:
            if store.marketplace == "ozon":
                ensure_range(db, workspace_id, store.id, date_from, source="finance")
                reports.append(
                    ozon_read.report(
                        db,
                        request.app.state.vault,
                        workspace_id,
                        store.id,
                        date_from,
                        date_to,
                        currency,
                        can_profit=profit_visible,
                    )
                )
            else:
                reports.append(
                    finance_overview(
                        workspace_id, date_from, date_to, request, db, identity, currency, store.id
                    )
                )
        db.commit()
        result = ozon_read.merge(reports) if len(reports) > 1 else reports[0]
        if not profit_visible:
            result.groups = [group for group in result.groups if group.key != "cogs"]
        return custom_expense_lines(
            result, db, request.app.state.vault, workspace_id, [store.id for store in stores]
        )
    business = business_report(
        workspace_id,
        date_from,
        date_to,
        request,
        db,
        identity,
        currency=currency,
        store_id=store_id,
        topic="finance",
    )
    settings = [
        (
            compute.tax_setting(db, workspace_id, store.id, date_to),
            compute.tax_changed(db, workspace_id, store.id, date_from, date_to),
        )
        for store in business.stores
    ]
    result = custom_expense_lines(
        build_overview(business, settings),
        db,
        request.app.state.vault,
        workspace_id,
        [store.id for store in business.stores],
    )
    result.is_loading |= (
        db.scalar(
            select(SyncRun.id)
            .where(
                SyncRun.workspace_id == workspace_id,
                SyncRun.store_id.in_([store.id for store in business.stores]),
                SyncRun.source == "finance",
                SyncRun.status.in_(["queued", "running"]),
                SyncRun.date_from <= date_to,
                SyncRun.date_to >= date_from,
            )
            .limit(1)
        )
        is not None
    )
    # Keep polling after publication until its financial projection is rebuilt.
    result.is_loading |= (
        db.scalar(
            select(SyncRun.id)
            .outerjoin(
                FinanceProjection,
                and_(
                    FinanceProjection.workspace_id == SyncRun.workspace_id,
                    FinanceProjection.store_id == SyncRun.store_id,
                ),
            )
            .where(
                SyncRun.workspace_id == workspace_id,
                SyncRun.store_id.in_([store.id for store in business.stores]),
                SyncRun.source == "finance",
                SyncRun.status == "succeeded",
                or_(
                    FinanceProjection.store_id.is_(None),
                    FinanceProjection.format_version != FORMAT,
                    SyncRun.finished_at > FinanceProjection.updated_at,
                ),
            )
            .limit(1)
        )
        is not None
    )
    member = require_workspace(db, identity, workspace_id)
    if not allows(member, "profit.read"):
        result.groups = [group for group in result.groups if group.key != "cogs"]
        result.taxes.configured_stores = 0
        result.taxes.vat = result.taxes.tax = result.taxes.net_profit = None
        result.taxes.notes = []
    return result
