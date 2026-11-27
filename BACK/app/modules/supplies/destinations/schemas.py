from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class SupplyDestination(BaseModel):
    id: str
    name: str
    store_id: UUID
    store_name: str
    marketplace: str
    recommended_units: int | None
    product_count: int
    urgent_count: int
    partial: bool
    updated_at: datetime | None


class SupplyDestinations(BaseModel):
    items: list[SupplyDestination]
    loading: bool
    loaded_products: int
    total_products: int
    failed_products: int


class SupplyDestinationsRefresh(BaseModel):
    queued: int
