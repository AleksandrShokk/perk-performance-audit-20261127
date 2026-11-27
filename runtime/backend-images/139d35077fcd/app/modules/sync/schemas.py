from datetime import UTC, date, datetime, timedelta
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.integrations.wildberries.data import DATED, Source
from app.modules.finance.fields import FinanceDetails
from app.modules.supplies.schemas import ImportedSupply


def moscow_today():
    return (datetime.now(UTC) + timedelta(hours=3)).date()


FINANCE_START = date(2024, 1, 29)
FUNNEL_DAYS = 360
RETURNS_DAYS = 180
SalesBasis = Literal["auto", "operational", "reports"]


def history_limits():
    today = moscow_today()
    return {
        Source.SALES: {"date_from": today - timedelta(days=89), "date_to": today},
        Source.ORDERS: {"date_from": today - timedelta(days=89), "date_to": today},
        Source.FINANCE: {"date_from": FINANCE_START, "date_to": today},
        # WB serves 365 days; a margin keeps a long backfill inside it past midnight.
        Source.FUNNEL: {"date_from": today - timedelta(days=FUNNEL_DAYS - 1), "date_to": today},
        # WB documents no depth for returns to the seller: stay with a conservative window.
        Source.RETURNS: {"date_from": today - timedelta(days=RETURNS_DAYS - 1), "date_to": today},
    }


class StartSync(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sources: list[Source] = Field(
        default_factory=lambda: list(Source), min_length=1, max_length=len(Source)
    )
    date_from: date = Field(default_factory=lambda: moscow_today() - timedelta(days=30))
    date_to: date = Field(default_factory=lambda: moscow_today() - timedelta(days=1))

    @model_validator(mode="after")
    def valid_period(self):
        today = moscow_today()
        if self.date_from > self.date_to or self.date_to > today or self.date_from < FINANCE_START:
            raise ValueError("Выберите период с 29.01.2024 по сегодняшний день.")
        if len(set(self.sources)) != len(self.sources):
            raise ValueError("Источники данных не должны повторяться.")
        return self

    def effective_sources(self):
        sources = list(self.sources)
        if Source.SALES in sources and self.date_from < history_limits()[Source.SALES]["date_from"]:
            if Source.FINANCE not in sources:
                sources.append(Source.FINANCE)
            if self.date_to < history_limits()[Source.SALES]["date_from"]:
                sources.remove(Source.SALES)
        # Orders have no report fallback: an older period fails as wb_history_unavailable.
        return sources

    def period_for(self, source: Source):
        if source in {Source.STOCK_HISTORY, Source.SUPPLY_DEMAND, Source.SUPPLY_DEMAND_FBS}:
            end = moscow_today() - timedelta(days=1)
            return end - timedelta(days=27), end
        if source not in DATED:
            return None, None
        return max(self.date_from, history_limits()[source]["date_from"]), self.date_to


class RunStatus(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    source: str
    status: str
    date_from: date | None
    date_to: date | None
    records_processed: int
    pages_processed: int
    attempts: int
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    next_attempt_at: datetime
    error_code: str | None
    sync_mode: str = "manual"


class ConfigureSchedule(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = True
    sources: list[Source] = Field(
        default_factory=lambda: [
            Source.CATALOG,
            Source.PRICES,
            Source.FBS,
            Source.STOCK_HISTORY,
            Source.SUPPLY_DEMAND,
            Source.SUPPLY_DEMAND_FBS,
            Source.SUPPLIES,
            Source.SALES,
            Source.ORDERS,
            Source.FINANCE,
            Source.FUNNEL,
            Source.RETURNS,
            Source.BALANCE,
        ],
        min_length=1,
        max_length=len(Source),
    )
    recent_days: int = Field(default=30, ge=7, le=30)
    load_history: bool = True

    @model_validator(mode="after")
    def unique_sources(self):
        if len(set(self.sources)) != len(self.sources):
            raise ValueError("Источники данных не должны повторяться.")
        return self

    def effective_sources(self):
        sources = list(self.sources)
        if self.load_history and Source.SALES in sources and Source.FINANCE not in sources:
            sources.append(Source.FINANCE)
        if {Source.STOCKS, Source.FUNNEL} & set(sources) and Source.STOCK_HISTORY not in sources:
            sources.append(Source.STOCK_HISTORY)
        if Source.STOCK_HISTORY in sources:
            sources.extend(
                source
                for source in (Source.SUPPLY_DEMAND, Source.SUPPLY_DEMAND_FBS, Source.SUPPLIES)
                if source not in sources
            )
        return sources


class ScheduleStatus(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    source: str
    enabled: bool
    recent_days: int
    recent_completed: bool
    history_from: date | None
    backfill_to: date | None
    next_refresh_at: datetime
    next_attempt_at: datetime
    last_completed_at: datetime | None
    error_code: str | None


class CatalogSize(BaseModel):
    chrt_id: str
    size: str
    barcodes: list[str]


class CatalogAttribute(BaseModel):
    variable: bool | None = None
    id: str
    name: str
    values: list[str]


class CatalogItem(BaseModel):
    nm_id: str
    vendor_code: str
    title: str
    brand: str
    subject: str
    colors: list[str] = Field(default_factory=list)
    sizes: list[CatalogSize]
    marketplace: str = "wildberries"
    category_id: str = ""
    type_id: str = ""
    group_id: str = ""
    photos: list[str] = Field(default_factory=list)
    attributes: list[CatalogAttribute] = Field(default_factory=list)


class StockItem(BaseModel):
    nm_id: str
    chrt_id: str
    warehouse_id: str
    warehouse_name: str
    quantity: int
    in_way_to_client: int
    in_way_from_client: int


class SaleItem(BaseModel):
    sale_id: str
    nm_id: str
    kind: str
    date: str
    last_change_date: str
    vendor_code: str
    barcode: str
    warehouse_name: str
    price_with_discount: str | None
    finished_price: str | None
    for_pay: str | None
    preliminary: bool


class OrderItem(BaseModel):
    srid: str
    nm_id: str
    date: str
    last_change_date: str
    vendor_code: str
    barcode: str
    size: str
    warehouse_name: str
    warehouse_type: str
    region: str
    total_price: str | None
    discount_percent: str | None
    spp: str | None
    price_with_discount: str | None
    finished_price: str | None
    is_cancel: bool
    cancel_date: str | None
    preliminary: bool


class FunnelItem(BaseModel):
    day: str
    nm_id: str
    vendor_code: str
    currency: str
    open_count: int
    cart_count: int
    order_count: int
    buyout_count: int
    cancel_count: int
    wishlist_count: int
    order_sum: str | None
    buyout_sum: str | None
    cancel_sum: str | None


class ReturnItem(BaseModel):
    srid: str
    shk_id: str
    nm_id: str
    barcode: str
    size: str
    subject: str
    brand: str
    return_type: str
    return_status: str
    return_reason: str
    order_date: str | None
    ready_at: str | None
    completed_at: str | None
    expires_at: str | None
    office_id: str | None
    office_address: str


class FinanceItem(FinanceDetails):
    rrd_id: str
    report_id: str
    nm_id: str
    document_type: str
    operation: str
    quantity: int
    report_date: str
    currency: str
    retail_amount: str | None
    for_pay: str | None
    acquiring_fee: str | None


class SellerPriceItem(BaseModel):
    nm_id: str
    currency: str
    prices: dict[str, str | None]


class StockHistoryItem(BaseModel):
    nm_id: str
    date_from: date
    date_to: date
    stock: int | None
    orders: int | None
    missing_hours: int | None


class DataPage(BaseModel):
    source: Source
    total: int
    last_successful_run: RunStatus | None
    latest_run: RunStatus | None
    is_partial: bool = False
    updated_at: datetime | None = None
    limit: int
    offset: int
    items: list[
        CatalogItem
        | StockItem
        | SellerPriceItem
        | StockHistoryItem
        | ImportedSupply
        | SaleItem
        | OrderItem
        | FunnelItem
        | ReturnItem
        | FinanceItem
    ]


class SourceCapability(BaseModel):
    available: bool
    error_code: str | None


class HistoryLimit(BaseModel):
    date_from: date
    date_to: date


class SyncCapabilities(BaseModel):
    token_type: Literal["unavailable", "basic", "personal", "service"]
    sources: dict[str, SourceCapability]
    history_limits: dict[str, HistoryLimit]


class StoreAnalytics(BaseModel):
    model_config = ConfigDict(extra="allow")
    date_from: date
    date_to: date
    coverage: dict[str, list[dict[str, str]]]
    period_complete: dict[str, bool]
    available: dict[str, bool]
    revision: str | None
