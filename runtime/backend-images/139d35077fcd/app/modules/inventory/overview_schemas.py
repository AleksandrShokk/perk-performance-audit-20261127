from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field

from app.modules.catalog.schemas import ProductItem


class CoverageChannel(StrEnum):
    FBO = "fbo"
    FBS = "fbs"
    ALL = "all"


class InventoryAmounts(BaseModel):
    units: int | None = None
    retail_value: str | None = None
    retail_complete: bool = False
    cost_value: str | None = None
    cost_complete: bool = False
    updated_at: datetime | None = None
    stale: bool = False


class FbsSizeStock(BaseModel):
    variant_id: str = ""
    chrt_id: str = ""
    quantity: int
    warehouses: dict[str, int]


class InventoryPosition(BaseModel):
    coverage_channel: CoverageChannel = CoverageChannel.FBO
    turnover_basis: Literal[
        "wb_orders_28d", "ozon_sales_28d_fbo", "ozon_orders_28d_fbs", "ozon_channels_28d"
    ] = "wb_orders_28d"
    product: ProductItem
    fbo: InventoryAmounts
    fbs: InventoryAmounts
    fbs_sizes: list[FbsSizeStock] = Field(default_factory=list)
    turnover_days: str | None = None
    turnover_status: Literal["ready", "no_orders", "no_sales", "no_data", "loading"] = "no_data"


class InventoryOverview(BaseModel):
    coverage_channel: CoverageChannel = CoverageChannel.FBO
    turnover_basis: Literal[
        "wb_orders_28d", "ozon_sales_28d_fbo", "ozon_orders_28d_fbs", "ozon_channels_28d", "mixed"
    ] = "wb_orders_28d"
    aggregation_status: Literal["ready", "warehouse_mapping_required"] = "ready"
    turnover_supported: bool = True
    error_code: str | None = None
    other_channels: list[str] = Field(default_factory=list)
    fbo: InventoryAmounts
    fbs: InventoryAmounts
    total: InventoryAmounts
    turnover_days: str | None = None
    turnover_updated_at: datetime | None = None
    turnover_loading: bool = False
    turnover_partial: bool = False
    turnover_stale: bool = False
    turnover_window_days: int = 28
    observed_days: int = 0
    items: list[InventoryPosition]
    count: int
    limit: int
    offset: int
    currency: str
    can_cost: bool
    is_loading: bool
    missing_sources: list[str]
