from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel


class ImportedSupply(BaseModel):
    marketplace: str = "wildberries"
    display_number: str = ""
    native_status: str = ""
    external_id: str
    supply_id: str | None
    preorder_id: str | None
    status: Literal[
        "draft",
        "planned",
        "ready_to_ship",
        "accepting",
        "accepted",
        "shipped",
        "cancelled",
        "unknown",
    ]
    planned_date: date | None
    actual_date: date | None
    created_date: date | None
    destination: str
    quantity: int | None
    accepted_quantity: int | None
    rejected: bool = False


class SupplyCard(ImportedSupply):
    store_id: UUID
    store_name: str


class SupplyList(BaseModel):
    items: list[SupplyCard]
    count: int
    limit: int
    offset: int
    loading: bool
    incomplete: bool
    missing_access: bool
    updated_at: datetime | None
    stale: bool


class ReplenishmentItem(BaseModel):
    id: str = ""
    marketplace: str = "wildberries"
    marketplace_code: str = ""
    demand_basis: Literal["wb_orders", "ozon_sales", "ozon_orders"] = "wb_orders"
    store_id: UUID
    store_name: str
    nm_id: str
    vendor_code: str
    title: str
    photo: str | None
    colors: list[str]
    barcodes: list[str]
    incoming_quantity: int | None = None
    incoming_reduction: int = 0
    fbs_stock: int | None = None
    fbs_reduction: int = 0
    destination_id: str = ""
    destination_name: str = ""
    stock: int
    daily_orders: str
    days_of_stock: str
    quantity: int
    required_quantity: int = 0
    box_multiple: int = 1
    urgent: bool


class ReplenishmentOverview(BaseModel):
    include_fbs: bool = False
    destination_id: str = ""
    destination_name: str = ""
    target_days: int = 30
    lead_time_days: int = 7
    urgent_days: int = 7
    incoming_units: int | None = None
    incoming_complete: bool = False
    recommended_units: int | None
    product_count: int | None
    urgent_count: int | None
    unknown_count: int
    no_orders_count: int
    partial: bool
    loading: bool
    stale: bool
    updated_at: datetime | None
    items: list[ReplenishmentItem]
    count: int
    limit: int
    offset: int
