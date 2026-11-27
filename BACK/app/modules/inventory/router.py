from datetime import date, datetime, timedelta
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from app.modules.accounts.reporting import require_reporting_store
from app.modules.accounts.router import find_store, require_workspace
from app.modules.auth.dependencies import DB, FullIdentity
from app.modules.insights.router import Freshness, served
from app.modules.inventory import service

router = APIRouter(prefix="/workspaces/{workspace_id}/stores/{store_id}", tags=["Inventory"])
Status = Literal["ok", "low", "critical", "out_of_stock", "no_sales", "inactive"]


class StockForecastItem(BaseModel):
    nm_id: str
    stock: int
    in_way_to_client: int
    in_way_from_client: int
    warehouses: dict[str, int]
    sizes: dict[str, int]
    sold_units: int = Field(description="WB buyouts in the window.")
    in_stock_days: int
    out_of_stock_days: int = Field(description="Days with a recorded zero stock and no sales.")
    daily_rate: str = Field(description="Buyouts per in-stock day, decimal string.")
    days_of_cover: int | None
    stockout_date: date | None
    average_price: str | None
    lost_revenue_estimate: str | None = Field(
        description="Rate × recorded out-of-stock days × average price. Estimate, not a loss."
    )
    status: Status
    demand_by_warehouse: dict[str, int]
    demand_by_size: dict[str, int]


class StockSource(BaseModel):
    stock_as_of: datetime | None = Field(description="When WB stock data was actually imported.")
    observed_days: int = Field(description="Days with a recorded stock observation in the window.")
    source_stale: bool = Field(description="Stock data is older than two days: refresh stocks.")
    demand_basis: Literal["orders", "buyouts"] = Field(
        default="buyouts",
        description="orders: non-cancelled orders cover the window; otherwise WB buyouts.",
    )


class StockForecast(StockSource):
    status: Literal["ready", "no_data"]
    snapshot_day: date | None
    window_days: int
    items: list[StockForecastItem]
    counts: dict[str, int]
    freshness: Freshness


class SupplyPlanInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lead_time_days: int = Field(default=7, ge=0, le=90)
    cover_days: int = Field(default=30, ge=1, le=180)
    safety_days: int = Field(default=3, ge=0, le=60)
    nm_ids: list[str] | None = Field(default=None, max_length=1000)


class SupplyPlanItem(BaseModel):
    nm_id: str
    quantity: int
    daily_rate: str
    stock: int
    horizon_days: int
    stockout_before_arrival: bool
    by_warehouse: dict[str, int] = Field(description="Split by where buyers ordered from.")
    by_size: dict[str, int]
    explanation: str


class SupplyPlan(StockSource):
    status: Literal["ready", "no_data"]
    snapshot_day: date | None
    items: list[SupplyPlanItem]
    freshness: Freshness


class StockHistoryDay(BaseModel):
    day: date
    stock: int
    to_client: int
    from_client: int


def readable(db, identity, workspace_id, store_id):
    require_workspace(db, identity, workspace_id)
    require_reporting_store(find_store(db, workspace_id, store_id))


def forecast_snapshot(
    request, response, db, identity, workspace_id, store_id, window, conditional=True
):
    data, fresh = served(
        request,
        response,
        db,
        identity,
        workspace_id,
        store_id,
        "forecast",
        {"window": window},
        conditional=conditional,
    )
    if fresh is None:
        return data, None, None, None
    day = date.fromisoformat(data["snapshot_day"]) if data["snapshot_day"] else None
    source = {key: data.get(key) for key in ("stock_as_of", "observed_days", "source_stale")}
    source["demand_basis"] = data.get("demand_basis") or "buyouts"
    source["observed_days"] = source["observed_days"] or 0
    source["source_stale"] = source["source_stale"] is not False
    return day, data["items"], fresh, source


@router.get("/inventory/forecast", response_model=StockForecast, operation_id="inventoryForecast")
def stock_forecast(
    workspace_id: UUID,
    store_id: UUID,
    request: Request,
    response: Response,
    db: DB,
    identity: FullIdentity,
    status: Status | None = None,
    window_days: Annotated[int, Query(ge=7, le=90)] = service.WINDOW,
):
    """Days of cover per SKU, most urgent first. Served from a precomputed snapshot."""
    day, items, fresh, source = forecast_snapshot(
        request, response, db, identity, workspace_id, store_id, window_days
    )
    if fresh is None:
        return day
    counts = {}
    for item in items:
        counts[item["status"]] = counts.get(item["status"], 0) + 1
    if status:
        items = [item for item in items if item["status"] == status]
    order = {"out_of_stock": 0, "critical": 1, "low": 2, "ok": 3, "no_sales": 4, "inactive": 5}
    items.sort(key=lambda item: (order[item["status"]], item["days_of_cover"] or 0))
    return StockForecast(
        status="ready" if day else "no_data",
        snapshot_day=day,
        window_days=window_days,
        items=items,
        counts=counts,
        freshness=fresh,
        **source,
    )


@router.post(
    "/inventory/supply-plan", response_model=SupplyPlan, operation_id="inventorySupplyPlan"
)
def plan_supply(
    workspace_id: UUID,
    store_id: UUID,
    data: SupplyPlanInput,
    request: Request,
    response: Response,
    db: DB,
    identity: FullIdentity,
):
    """Quantity per SKU, split by warehouse demand and size. Instant: uses the forecast snapshot."""
    day, items, fresh, source = forecast_snapshot(
        request, response, db, identity, workspace_id, store_id, service.WINDOW, conditional=False
    )
    return SupplyPlan(
        status="ready" if day else "no_data",
        snapshot_day=day,
        freshness=fresh,
        **source,
        items=service.supply_plan(
            items,
            lead_time_days=data.lead_time_days,
            cover_days=data.cover_days,
            safety_days=data.safety_days,
            nm_ids=set(data.nm_ids) if data.nm_ids else None,
        ),
    )


@router.get(
    "/inventory/history", response_model=list[StockHistoryDay], operation_id="inventoryHistory"
)
def stock_history(
    workspace_id: UUID,
    store_id: UUID,
    request: Request,
    db: DB,
    identity: FullIdentity,
    date_from: date,
    date_to: date,
    nm_id: Annotated[str | None, Query(pattern=r"^[1-9][0-9]{0,18}$")] = None,
):
    readable(db, identity, workspace_id, store_id)
    if date_from > date_to or date_to - date_from > timedelta(days=731):
        raise HTTPException(422, "Выберите период не длиннее двух лет.")
    return service.history(
        db, request.app.state.vault, workspace_id, store_id, date_from, date_to, nm_id
    )
