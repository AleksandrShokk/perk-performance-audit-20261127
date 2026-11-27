import json
import logging
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select

from app.db.tenant import scope
from app.modules.accounts.reporting import require_reporting_store
from app.modules.accounts.router import find_store, require_workspace
from app.modules.audit.service import audit as audit_event
from app.modules.auth.dependencies import DB, FullIdentity, now
from app.modules.finance.router import owner_store
from app.modules.finance.schemas import Currency
from app.modules.insights import compute, snapshots
from app.modules.insights.goals import goal_aad, month_start
from app.modules.insights.models import StoreEvent, StoreGoal
from app.modules.sync import funnel_summary
from app.modules.sync.schemas import moscow_today

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/workspaces/{workspace_id}/stores/{store_id}", tags=["Insights"])
Severity = Literal["high", "medium", "info"]
EventKind = Literal["price_change", "promotion", "advertising", "supply", "content", "other"]
GoalMetric = Literal["revenue", "profit", "net_profit", "units"]


class Freshness(BaseModel):
    computed_at: datetime
    stale: bool = Field(description="Store data changed; a refreshed snapshot is being prepared.")


class Finding(BaseModel):
    code: str
    severity: Severity
    title: str
    explanation: str
    amount: str | None
    share_of_revenue_percent: str | None
    items: list[dict[str, str | int | None]]
    previous_amount: str | None = None
    dead_stock_units: int | None = None
    is_estimate: bool = False


class MoneyAudit(BaseModel):
    date_from: date
    date_to: date
    currency: str
    status: str
    is_partial: bool
    period_covered: bool
    products_truncated: bool
    revenue: str | None
    findings: list[Finding]
    freshness: Freshness


class SalesDay(BaseModel):
    day: date
    known: bool = Field(description="Covered by completed imports; otherwise values are null.")
    units: int | None
    amount: str | None = Field(description="Null if unknown or a sale in the day has no price.")


class DashboardSales(BaseModel):
    status: Literal["ready", "partial", "no_data"]
    yesterday: SalesDay
    last_7_days: list[SalesDay]
    basis: Literal["buyouts"]


class DashboardFinance(BaseModel):
    revenue: str | None
    profit_before_tax: str | None
    vat: str | None
    tax: str | None
    net_profit: str | None
    net_margin_percent: str | None
    notes: list[str]


class UrgentStock(BaseModel):
    nm_id: str
    stock: int
    days_of_cover: int | None
    status: str


class DashboardStock(BaseModel):
    snapshot_day: date | None
    stock_as_of: datetime | None = Field(description="When WB stock data was actually imported.")
    source_stale: bool = Field(description="Stock data is older than two days.")
    counts: dict[str, int]
    urgent: list[UrgentStock]


class TopFinding(BaseModel):
    code: str
    severity: Severity
    title: str
    amount: str | None


class Period(BaseModel):
    date_from: date
    date_to: date


class OrderFigures(BaseModel):
    """Null = unknown (no completed import for those days, or an unpriced order)."""

    orders: int | None
    orders_amount: str | None
    cancellations: int | None
    cancellations_amount: str | None
    net_orders: int | None
    net_orders_amount: str | None
    cancel_rate_percent: str | None
    average_order_value: str | None
    buyouts: int | None
    buyouts_amount: str | None
    returns: int | None
    buyout_rate_percent: str | None = Field(
        description="Buyouts / non-cancelled orders of the same days; whole covered period only."
    )


class OrderDay(OrderFigures):
    day: date


class OrderProduct(OrderFigures):
    nm_id: str


ReportStatus = Literal["ready", "partial", "no_data"]


class OrdersReport(BaseModel):
    date_from: date
    date_to: date
    status: ReportStatus
    orders_known_days: int
    sales_known_days: int
    period_days: int
    orders_known_through: date | None
    buyout_rate_basis: Literal["period_ratio"]
    totals: OrderFigures
    daily: list[OrderDay]
    products: list[OrderProduct]
    products_truncated: bool
    freshness: Freshness


class BuyoutUnits(BaseModel):
    sales: int | None
    returns: int | None
    net_units: int | None


class BuyoutDay(BuyoutUnits):
    day: date
    source: Literal["sales_report", "finance_report"] | None = Field(
        description="Where this day comes from; null = not covered by imports (unknown)."
    )


class BuyoutProduct(BuyoutUnits):
    nm_id: str


class BuyoutAmount(BaseModel):
    basis: Literal["buyer_paid", "retail_price"] = Field(
        description="buyer_paid: sales report (price paid); retail_price: financial report."
    )
    currency: str | None = Field(description="Null for the sales report (cabinet currency).")
    sales_amount: str | None
    returns_amount: str | None
    net_amount: str | None
    missing_prices: int


class BuyoutsReport(BaseModel):
    date_from: date
    date_to: date
    status: Literal["ready", "partial", "preparing", "no_data"]
    period_days: int
    known_days: int
    sales_report_days: int
    finance_report_days: int
    report_lag_days: int
    rows_without_sale_date: int
    totals: BuyoutUnits
    amounts: list[BuyoutAmount]
    daily: list[BuyoutDay]
    products: list[BuyoutProduct]
    products_truncated: bool
    freshness: Freshness


class FunnelFigures(BaseModel):
    impressions: int | None = Field(
        default=None, description="Native Ozon impressions; unavailable for WB."
    )
    opens: int | None
    carts: int | None
    orders: int | None
    buyouts: int | None
    cancellations: int | None = Field(description="WB combines cancellations and returns.")
    wishlist: int | None
    orders_amount: str | None
    buyouts_amount: str | None
    cancellations_amount: str | None
    add_to_cart_percent: str | None
    cart_to_order_percent: str | None
    open_to_order_percent: str | None
    buyout_percent: str | None


class FunnelPeriodTotals(BaseModel):
    partial_amounts: list[str] = Field(
        default_factory=list,
        description="Known-price subtotals; amounts in this list are not full totals.",
    )
    date_from: date
    date_to: date
    totals: FunnelFigures


class FunnelSummaryReport(FunnelPeriodTotals):
    data_source: Literal["wb_funnel", "ozon_postings"] = "wb_funnel"
    status: Literal["ready", "preparing", "error"]
    currency: str | None
    previous: FunnelPeriodTotals
    error_code: str | None
    freshness: Freshness


class FunnelDay(FunnelFigures):
    partial_amounts: list[str] = Field(
        default_factory=list,
        description="Known-price subtotals; amounts in this list are not full totals.",
    )
    day: date


class FunnelProduct(FunnelFigures):
    partial_amounts: list[str] = Field(
        default_factory=list,
        description="Known-price subtotals; amounts in this list are not full totals.",
    )
    id: str = ""
    marketplace: str = "wildberries"
    marketplace_code: str = ""
    identifier_kind: Literal["nm_id", "sku"] = "nm_id"
    nm_id: str
    title: str = ""
    vendor_code: str = ""
    photos: list[str] = Field(default_factory=list)
    barcodes: list[str] = Field(default_factory=list)


class FunnelLoadProgress(BaseModel):
    revision: str
    known_days: int
    available_days: int
    is_loading: bool
    records_processed: int
    pages_processed: int
    next_attempt_at: datetime | None
    error_code: str | None


class FunnelReport(BaseModel):
    history_available_from: date | None = None
    available_days: int | None = None
    traffic_known_days: int | None = None
    product_traffic_known_days: int | None = None
    partial_amounts: list[str] = Field(
        default_factory=list,
        description="Known-price subtotals; amounts in this list are not full totals.",
    )
    data_source: Literal["wb_funnel", "ozon_postings"] = "wb_funnel"
    available_metrics: list[str] | None = None
    error_code: str | None = None
    is_loading: bool = False
    date_from: date
    date_to: date
    status: Literal["ready", "partial", "preparing", "no_data"]
    period_days: int
    known_days: int
    currency: str | None
    buyouts_by: Literal["order_date"]
    buyouts_maturing_from: date | None = Field(
        description="Heuristic warning for the last 14 days, not WB's finalization guarantee."
    )
    totals: FunnelFigures
    daily: list[FunnelDay]
    products: list[FunnelProduct]
    products_truncated: bool
    freshness: Freshness


class NamedCount(BaseModel):
    name: str
    count: int


class ReturnsDay(BaseModel):
    day: date
    returns: int | None


class ReturnsProduct(BaseModel):
    nm_id: str
    returns: int
    types: list[NamedCount]


class PickupItem(BaseModel):
    nm_id: str
    barcode: str
    size: str
    return_type: str
    return_status: str
    ready_on: date
    expires_on: date | None
    days_left: int | None = Field(description="Negative: storage already expired.")
    office_address: str


class ReturnsPickup(BaseModel):
    awaiting: int
    expiring_soon: int = Field(description="Ready items with 0-3 days of storage left.")
    expired: int
    in_transit: int
    items: list[PickupItem]
    items_truncated: bool


class ReturnsTotals(BaseModel):
    returns: int | None


class ReturnsReport(BaseModel):
    date_from: date
    date_to: date
    status: Literal["ready", "partial", "no_data"]
    period_days: int
    known_days: int
    as_of: datetime | None
    date_basis: Literal["ready_for_pickup"]
    totals: ReturnsTotals
    by_type: list[NamedCount]
    by_status: list[NamedCount]
    daily: list[ReturnsDay]
    products: list[ReturnsProduct]
    products_truncated: bool
    pickup: ReturnsPickup = Field(description="Current state, independent of the period.")
    freshness: Freshness


class DashboardOrders(BaseModel):
    status: ReportStatus
    yesterday: OrderDay
    last_7_days: OrderFigures


class Dashboard(BaseModel):
    currency: str
    finance_status: str
    finance_is_partial: bool
    period: Period
    sales: DashboardSales
    # Snapshots computed before orders were added omit it until their refresh.
    orders: DashboardOrders | None = None
    finance: DashboardFinance
    stock: DashboardStock
    top_findings: list[TopFinding]
    freshness: Freshness


class SeasonMonth(BaseModel):
    month: int
    index: str | None = Field(description="1.00 = average month; 1.40 = 40% above average.")
    average_units: str | None
    years: int


class Seasonality(BaseModel):
    status: Literal["ready", "unavailable"]
    reason: str | None
    covered_months: int
    basis: str | None = None
    months: list[SeasonMonth]
    freshness: Freshness


class EventInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    day: date
    kind: EventKind
    title: str = Field(max_length=200)
    note: str = Field(default="", max_length=2000)
    nm_id: str | None = Field(default=None, pattern=r"^[1-9][0-9]{0,18}$")

    @field_validator("title")
    @classmethod
    def title_policy(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("Введите название.")
        return value


class EventView(BaseModel):
    id: UUID
    day: date
    kind: EventKind
    title: str
    note: str
    nm_id: str | None
    created_at: datetime


class GoalInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    month: date = Field(description="Any day of the month; stored as its first day.")
    metric: GoalMetric
    target: Decimal = Field(gt=0, max_digits=16, decimal_places=2)


class GoalMetricView(BaseModel):
    metric: GoalMetric
    target: str | None
    actual: str | None
    forecast: str | None
    percent_of_target: str | None
    forecast_percent_of_target: str | None


class GoalProgress(BaseModel):
    month: date
    days_in_month: int
    days_elapsed: int
    through: date | None
    finance_status: str
    forecast_method: Literal["linear_run_rate"]
    metrics: list[GoalMetricView]
    freshness: Freshness


def readable(db, identity, workspace_id, store_id):
    require_workspace(db, identity, workspace_id)
    require_reporting_store(find_store(db, workspace_id, store_id))


def served(
    request,
    response,
    db,
    identity,
    workspace_id,
    store_id,
    kind,
    params,
    conditional=True,
    cold_start=None,
):
    readable(db, identity, workspace_id, store_id)
    state = request.app.state

    def builder(session):
        return compute.build(
            kind, params, session, state.redis, state.vault, workspace_id, store_id
        )

    return snapshots.serve(
        request,
        response,
        db,
        identity,
        workspace_id,
        store_id,
        kind,
        params,
        builder,
        conditional=conditional,
        cold_start=cold_start,
    )


@router.get("/dashboard", response_model=Dashboard, operation_id="storeDashboard")
def store_dashboard(
    workspace_id: UUID,
    store_id: UUID,
    request: Request,
    response: Response,
    db: DB,
    identity: FullIdentity,
):
    """First screen in one request: sales, profit, stock alerts and top money findings."""
    params = compute.period_params(None, None)
    data, fresh = served(
        request, response, db, identity, workspace_id, store_id, "dashboard", params
    )
    return data if fresh is None else {**data, "freshness": fresh}


@router.get("/insights/audit", response_model=MoneyAudit, operation_id="insightsMoneyAudit")
def money_audit(
    workspace_id: UUID,
    store_id: UUID,
    request: Request,
    response: Response,
    db: DB,
    identity: FullIdentity,
    date_from: date | None = None,
    date_to: date | None = None,
    currency: Currency | None = None,
):
    """Where the store loses money: penalties, storage, loss-making SKUs, stockouts."""
    params = compute.period_params(date_from, date_to, currency)
    data, fresh = served(request, response, db, identity, workspace_id, store_id, "audit", params)
    if fresh is None:
        return data
    return {
        **data,
        "date_from": params["date_from"],
        "date_to": params["date_to"],
        "freshness": fresh,
    }


@router.get("/insights/orders", response_model=OrdersReport, operation_id="insightsOrders")
def orders_report(
    workspace_id: UUID,
    store_id: UUID,
    request: Request,
    response: Response,
    db: DB,
    identity: FullIdentity,
    date_from: date | None = None,
    date_to: date | None = None,
):
    """Orders, cancellations, buyouts and the buyout rate by day and by SKU (last 90 days)."""
    params = compute.period_params(date_from, date_to)
    data, fresh = served(request, response, db, identity, workspace_id, store_id, "orders", params)
    if fresh is None:
        return data
    return {
        **data,
        "date_from": params["date_from"],
        "date_to": params["date_to"],
        "freshness": fresh,
    }


@router.get("/insights/buyouts", response_model=BuyoutsReport, operation_id="insightsBuyouts")
def buyouts_report(
    workspace_id: UUID,
    store_id: UUID,
    request: Request,
    response: Response,
    db: DB,
    identity: FullIdentity,
    date_from: date | None = None,
    date_to: date | None = None,
):
    """Buyouts by sale date for any period since 2024-01-29.

    Recent days come from the sales report, older ones from financial reports.
    """
    params = compute.period_params(date_from, date_to)
    data, fresh = served(request, response, db, identity, workspace_id, store_id, "buyouts", params)
    if fresh is None:
        return data
    return {
        **data,
        "date_from": params["date_from"],
        "date_to": params["date_to"],
        "freshness": fresh,
    }


@router.get(
    "/insights/funnel/summary",
    response_model=FunnelSummaryReport,
    operation_id="insightsFunnelSummary",
)
def funnel_period_summary(
    workspace_id: UUID,
    store_id: UUID,
    request: Request,
    db: DB,
    identity: FullIdentity,
    date_from: date,
    date_to: date,
    include_previous_days: bool = False,
    price_basis: Literal["customer", "seller"] = "customer",
):
    """Complete period totals and comparison, independent of daily chart loading."""
    require_workspace(db, identity, workspace_id)
    store = find_store(db, workspace_id, store_id)
    if store.marketplace == "ozon":
        from app.modules.insights import ozon_read

        require_reporting_store(store, "analytics")
        start, end = ozon_read.period(date_from, date_to)
        if end != moscow_today() - timedelta(days=1) or not 0 <= (end - start).days < 28:
            raise HTTPException(422, "Выберите от 1 до 28 завершённых дней по вчерашний день.")
        data = ozon_read.summary(
            db, request.app.state.vault, workspace_id, store_id, start, end, price_basis
        )
        db.commit()
        return data
    readable(db, identity, workspace_id, store_id)
    yesterday = moscow_today() - timedelta(days=1)
    if date_to != yesterday or not 0 <= (date_to - date_from).days < 28:
        raise HTTPException(422, "Выберите от 1 до 28 завершённых дней по вчерашний день.")
    state = request.app.state
    data = funnel_summary.read(db, state.vault, workspace_id, store_id, date_from, date_to)
    if data["freshness"]["stale"] or include_previous_days:
        from app.workers.tasks import request_funnel_summary

        key = "perk:funnel-summary-request:" + state.vault.digest(
            "funnel-summary-job",
            f"{workspace_id}:{store_id}:{date_from}:{date_to}:{include_previous_days}",
        )
        try:
            if state.redis.set(key, "1", nx=True, ex=15):
                try:
                    request_funnel_summary.apply_async(
                        args=[
                            str(workspace_id),
                            str(store_id),
                            str(identity.user.id),
                            str(date_from),
                            str(date_to),
                            include_previous_days,
                        ],
                        retry=False,
                    )
                except Exception:
                    state.redis.delete(key)
                    logger.warning("Funnel summary job could not be queued")
        except Exception:
            # Keep the published report readable; log no keys or provider payloads.
            logger.warning("Funnel summary refresh could not be scheduled")
    return data


@router.get("/insights/funnel", response_model=FunnelReport, operation_id="insightsFunnel")
def funnel_report(
    workspace_id: UUID,
    store_id: UUID,
    request: Request,
    response: Response,
    db: DB,
    identity: FullIdentity,
    date_from: date | None = None,
    date_to: date | None = None,
    price_basis: Literal["customer", "seller"] = "customer",
):
    """Marketplace funnel and order-date cohorts; unavailable metrics remain unknown."""
    require_workspace(db, identity, workspace_id)
    store = find_store(db, workspace_id, store_id)
    if store.marketplace == "ozon":
        from app.modules.insights import ozon_read

        require_reporting_store(store, "analytics")
        start, end = ozon_read.period(date_from, date_to)
        ozon_read.ensure_range(db, workspace_id, store_id, start)
        db.commit()
        from app.db.session import set_actor

        set_actor(db, identity.user.id)
        data = ozon_read.report(
            db, request.app.state.vault, workspace_id, store_id, start, end, price_basis=price_basis
        )
        db.commit()
        return data
    params = compute.period_params(date_from, date_to)
    if date.fromisoformat(params["date_from"]) < moscow_today() - timedelta(days=28):
        from sqlalchemy import text

        from app.db.session import set_actor

        db.execute(
            text("SELECT perk_request_funnel_history(:wid,:sid,:start)"),
            {"wid": workspace_id, "sid": store_id, "start": params["date_from"]},
        )
        db.commit()
        set_actor(db, identity.user.id)
    from app.integrations.wildberries.data import Source
    from app.modules.sync.models import SyncRun

    readable(db, identity, workspace_id, store_id)
    start, end = compute.dates(params)
    active = db.scalar(
        select(SyncRun.id)
        .where(
            *scope(SyncRun, workspace_id, store_id),
            SyncRun.source == Source.FUNNEL,
            SyncRun.status.in_(["queued", "running"]),
            SyncRun.date_from <= end,
            SyncRun.date_to >= start,
        )
        .limit(1)
    )
    long_period = (end - start).days >= 28
    if long_period:
        from app.modules.insights import funnel

        data, fresh = served(
            request,
            response,
            db,
            identity,
            workspace_id,
            store_id,
            "funnel",
            params,
            cold_start=lambda: funnel.preparing(start, end),
        )
    elif active:
        from app.modules.insights import funnel

        data = funnel.report(
            db, request.app.state.vault, workspace_id, store_id, start, end, include_labels=False
        )
        fresh = {"computed_at": now(), "stale": True}
    else:
        data, fresh = served(
            request, response, db, identity, workspace_id, store_id, "funnel", params
        )
    if fresh is None:
        return data
    if not long_period and not active and fresh["stale"] and data.get("is_loading"):
        from app.modules.insights import funnel

        data = funnel.report(
            db, request.app.state.vault, workspace_id, store_id, start, end, include_labels=False
        )
    from app.integrations.wildberries.data import Source
    from app.modules.insights.product_labels import enrich
    from app.modules.sync.schemas import history_limits

    native_floor = history_limits()[Source.FUNNEL]["date_from"]
    available = [
        day
        for day in data.get("daily", [])
        if date.fromisoformat(day["day"]) >= native_floor or day.get("orders") is not None
    ]
    data = {
        **data,
        "history_available_from": min((d["day"] for d in available), default=str(native_floor)),
        "available_days": len(available),
        "is_loading": bool(
            data.get("is_loading") and any(d.get("orders") is None for d in available)
        ),
        "products": enrich(
            data.get("products", []),
            db,
            request.app.state.vault,
            workspace_id,
            store_id,
            "wildberries",
            start,
            end,
        ),
    }
    return {
        **data,
        "date_from": params["date_from"],
        "date_to": params["date_to"],
        "freshness": fresh,
    }


@router.get("/insights/returns", response_model=ReturnsReport, operation_id="insightsReturns")
def returns_report(
    workspace_id: UUID,
    store_id: UUID,
    request: Request,
    response: Response,
    db: DB,
    identity: FullIdentity,
    date_from: date | None = None,
    date_to: date | None = None,
):
    """Returns to the seller by type, status and SKU, plus items waiting at pickup points."""
    params = compute.period_params(date_from, date_to)
    data, fresh = served(request, response, db, identity, workspace_id, store_id, "returns", params)
    if fresh is None:
        return data
    return {
        **data,
        "date_from": params["date_from"],
        "date_to": params["date_to"],
        "freshness": fresh,
    }


@router.get("/insights/seasonality", response_model=Seasonality, operation_id="insightsSeasonality")
def seasonality(
    workspace_id: UUID,
    store_id: UUID,
    request: Request,
    response: Response,
    db: DB,
    identity: FullIdentity,
    nm_id: Annotated[str | None, Query(pattern=r"^[1-9][0-9]{0,18}$")] = None,
):
    """Monthly demand index from at least a year of the store's own report history."""
    params = {"nm_id": nm_id}
    data, fresh = served(
        request, response, db, identity, workspace_id, store_id, "seasonality", params
    )
    return data if fresh is None else {**data, "freshness": fresh}


def event_aad(workspace_id, store_id, event_id):
    return f"perk-event:v1:{workspace_id}:{store_id}:{event_id}"


def event_view(vault, row):
    value = json.loads(
        vault.open(row.ciphertext, event_aad(row.workspace_id, row.store_id, row.id))
    )
    return EventView(
        id=row.id,
        day=row.day,
        kind=row.kind,
        nm_id=row.nm_id,
        created_at=row.created_at,
        **value,
    )


@router.get("/events", response_model=list[EventView], operation_id="storeEventsList")
def events(
    workspace_id: UUID,
    store_id: UUID,
    date_from: date,
    date_to: date,
    request: Request,
    db: DB,
    identity: FullIdentity,
    nm_id: Annotated[str | None, Query(pattern=r"^[1-9][0-9]{0,18}$")] = None,
):
    """Journal for chart annotations. Store-wide events are included for every SKU."""
    readable(db, identity, workspace_id, store_id)
    if date_from > date_to or date_to - date_from > timedelta(days=1100):
        raise HTTPException(422, "Выберите период не длиннее трёх лет.")
    query = (
        select(StoreEvent)
        .where(
            *scope(StoreEvent, workspace_id, store_id), StoreEvent.day.between(date_from, date_to)
        )
        .order_by(StoreEvent.day, StoreEvent.created_at)
        .limit(1000)
    )
    if nm_id:
        query = query.where((StoreEvent.nm_id == nm_id) | StoreEvent.nm_id.is_(None))
    return [event_view(request.app.state.vault, row) for row in db.scalars(query)]


@router.post("/events", response_model=EventView, status_code=201, operation_id="storeEventsCreate")
def create_event(
    workspace_id: UUID,
    store_id: UUID,
    data: EventInput,
    request: Request,
    db: DB,
    identity: FullIdentity,
):
    owner_store(db, identity, workspace_id, store_id)
    row = StoreEvent(
        workspace_id=workspace_id,
        store_id=store_id,
        id=uuid4(),
        day=data.day,
        kind=data.kind,
        nm_id=data.nm_id,
        created_by=identity.user.id,
    )
    row.ciphertext = request.app.state.vault.seal(
        json.dumps({"title": data.title, "note": data.note.strip()}, ensure_ascii=False),
        event_aad(workspace_id, store_id, row.id),
    )
    db.add(row)
    db.flush()
    result = event_view(request.app.state.vault, row)
    audit_event(
        db,
        "store.event_created",
        user_id=identity.user.id,
        workspace_id=workspace_id,
        target_id=row.id,
    )
    db.commit()
    return result


@router.delete("/events/{event_id}", status_code=204, operation_id="storeEventsDelete")
def delete_event(
    workspace_id: UUID, store_id: UUID, event_id: UUID, db: DB, identity: FullIdentity
):
    owner_store(db, identity, workspace_id, store_id)
    row = db.get(StoreEvent, (workspace_id, store_id, event_id))
    if not row:
        raise HTTPException(404, "Событие не найдено.")
    db.delete(row)
    db.commit()


@router.put("/goals", response_model=GoalMetricView, operation_id="storeGoalSave")
def save_goal(
    workspace_id: UUID,
    store_id: UUID,
    data: GoalInput,
    request: Request,
    db: DB,
    identity: FullIdentity,
):
    owner_store(db, identity, workspace_id, store_id)
    month = month_start(data.month)
    row = db.get(StoreGoal, (workspace_id, store_id, month, data.metric))
    if not row:
        row = StoreGoal(
            workspace_id=workspace_id,
            store_id=store_id,
            month=month,
            metric=data.metric,
            created_by=identity.user.id,
        )
        db.add(row)
    row.updated_at = now()
    row.ciphertext = request.app.state.vault.seal(
        json.dumps({"target": format(data.target, "f")}),
        goal_aad(workspace_id, store_id, month, data.metric),
    )
    db.commit()
    return GoalMetricView(
        metric=data.metric,
        target=format(data.target, "f"),
        actual=None,
        forecast=None,
        percent_of_target=None,
        forecast_percent_of_target=None,
    )


@router.delete("/goals/{month}/{metric}", status_code=204, operation_id="storeGoalDelete")
def delete_goal(
    workspace_id: UUID,
    store_id: UUID,
    month: date,
    metric: GoalMetric,
    db: DB,
    identity: FullIdentity,
):
    owner_store(db, identity, workspace_id, store_id)
    row = db.get(StoreGoal, (workspace_id, store_id, month_start(month), metric))
    if row:
        db.delete(row)
        db.commit()


@router.get("/goals", response_model=GoalProgress, operation_id="storeGoalProgress")
def goal_progress(
    workspace_id: UUID,
    store_id: UUID,
    request: Request,
    response: Response,
    db: DB,
    identity: FullIdentity,
    month: date | None = None,
):
    """Plan/fact for a month: actual to yesterday and a linear forecast to month end."""
    params = {"month": month_start(month or moscow_today()).isoformat()}
    data, fresh = served(request, response, db, identity, workspace_id, store_id, "goals", params)
    return data if fresh is None else {**data, "freshness": fresh}


@router.get(
    "/insights/funnel/progress",
    response_model=FunnelLoadProgress,
    operation_id="insightsFunnelProgress",
)
def funnel_load_progress(
    workspace_id: UUID,
    store_id: UUID,
    request: Request,
    db: DB,
    identity: FullIdentity,
    date_from: date,
    date_to: date,
):
    from app.modules.insights.funnel_progress import read

    readable(db, identity, workspace_id, store_id)
    start, end = compute.validated_period(date_from, date_to)
    store = find_store(db, workspace_id, store_id)
    if store.marketplace != "wildberries":
        raise HTTPException(422, "Этот прогресс загрузки относится к WB.")
    return read(db, request.app.state.vault, workspace_id, store_id, start, end)


@router.get(
    "/insights/funnel/availability",
    response_model=Period,
    operation_id="insightsFunnelAvailability",
)
def funnel_availability(
    workspace_id: UUID, store_id: UUID, response: Response, db: DB, identity: FullIdentity
):
    from app.modules.accounts.access import allows
    from app.modules.insights.funnel_history import availability

    member = require_workspace(db, identity, workspace_id)
    store = find_store(db, workspace_id, store_id)
    if not allows(member, "analytics.read"):
        raise HTTPException(403, "Нет доступа к аналитике.")
    if store.marketplace != "wildberries":
        raise HTTPException(422, "Границы истории относятся к WB.")
    response.headers["Cache-Control"] = "no-store"
    return availability(db, workspace_id, store_id)
