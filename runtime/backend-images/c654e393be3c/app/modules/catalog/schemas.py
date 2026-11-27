from datetime import datetime
from typing import Annotated, Literal
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, Field, model_validator


class WarehouseStock(BaseModel):
    name: str
    quantity: int


class ProductVariant(BaseModel):
    id: str = ""
    external_id: str = ""
    chrt_id: str = Field(description="WB-only legacy identifier; empty for Ozon.")
    size: str
    barcodes: list[str]
    stock: int | None
    to_client: int | None
    from_client: int | None
    warehouses: list[WarehouseStock]
    unit_cost: str | None


class ProductItem(BaseModel):
    store_id: UUID
    store_name: str
    id: str = ""
    external_id: str = ""
    marketplace_code: str = ""
    nm_id: str = Field(description="WB-only legacy identifier; empty for Ozon.")
    vendor_code: str
    title: str
    brand: str
    subject: str
    colors: list[str]
    photos: list[str] = Field(default_factory=list)
    marketplace: str = "wildberries"
    variants: list[ProductVariant]
    stock: int | None
    stock_updated_at: datetime | None
    stock_stale: bool
    missing_cost_variants: int | None

    @model_validator(mode="after")
    def neutral_identity(self):
        # Stable listing/variant identity, NOT a cross-market canonical product match.
        if self.marketplace == "wildberries":
            self.external_id = self.external_id or self.nm_id
            self.marketplace_code = self.marketplace_code or self.nm_id
        if not self.external_id:
            raise ValueError("Укажите артикул товара на маркетплейсе.")
        self.id = str(
            uuid5(
                NAMESPACE_URL,
                f"perk:{self.store_id}:{self.marketplace}:{self.external_id}",
            )
        )
        for variant in self.variants:
            variant.external_id = variant.external_id or variant.chrt_id
            if not variant.external_id:
                raise ValueError("Укажите артикул варианта товара.")
            variant.id = str(uuid5(NAMESPACE_URL, f"{self.id}:variant:{variant.external_id}"))
        return self


class ProductPage(BaseModel):
    error_code: str | None = None
    items: list[ProductItem]
    total: int
    total_variants: int
    missing_cost_variants: int | None
    stock_units: int | None
    currency: str
    limit: int
    offset: int
    is_loading: bool
    is_partial: bool


class ProductModel(BaseModel):
    id: str
    combined: bool = False
    store_id: UUID
    store_name: str
    marketplace: str
    title: str
    brand: str
    grouping: Literal["marketplace", "manual", "single", "matched"]
    products: list[ProductItem]
    stock: int | None
    missing_cost_variants: int | None


class ProductModelsPage(BaseModel):
    error_code: str | None = None
    items: list[ProductModel]
    total: int
    total_products: int
    total_variants: int
    currency: str
    limit: int
    offset: int
    is_loading: bool
    is_partial: bool


class GroupingInput(BaseModel):
    action: Literal["merge", "split", "reset"] = "merge"
    articles: list[Annotated[str, Field(pattern=r"^[1-9][0-9]{0,31}$")]] = Field(
        min_length=1, max_length=200
    )
    title: str = Field(default="", max_length=200)
