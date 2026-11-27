"""A saved recommendation snapshot, never a submitted marketplace shipment."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.modules.supplies.schemas import ReplenishmentItem

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
Destination = Annotated[str, StringConstraints(strip_whitespace=True, max_length=160)]
PlanStatus = Literal["draft", "ready", "archived"]


class PlanCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: Name
    destination: Destination = ""
    destination_id: str = Field(default="", max_length=100)
    target_days: int = Field(default=30, ge=1, le=180, strict=True)
    lead_time_days: int = Field(default=7, ge=0, le=90, strict=True)
    urgent_only: bool = False
    include_fbs: bool = False


class PlanVariantInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    variant_id: str = Field(min_length=1, max_length=100)
    quantity: int = Field(ge=0, le=2147483647, strict=True)
    barcode: str = Field(default="", max_length=200)


class PlanVariant(PlanVariantInput):
    external_id: str
    size: str
    barcodes: list[str]
    quantity: int = 0


class PlanVariantsLoad(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=1, strict=True)


class PlanQuantity(BaseModel):
    model_config = ConfigDict(extra="forbid")
    product_key: str = Field(min_length=1, max_length=100)
    quantity: int = Field(ge=0, le=2147483647, strict=True)
    variants: list[PlanVariantInput] | None = Field(default=None, max_length=1000)


class PlanUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=1, strict=True)
    title: Name
    destination: Destination = ""
    status: PlanStatus = "draft"
    items: list[PlanQuantity] = Field(max_length=5000)

    @model_validator(mode="after")
    def unique_products(self):
        if len({row.product_key for row in self.items}) != len(self.items):
            raise ValueError("Товар повторяется в плане.")
        return self


class PlanLine(ReplenishmentItem):
    product_key: str
    recommended_quantity: int
    variants: list[PlanVariant] = Field(default_factory=list)


class PlanSnapshot(BaseModel):
    include_fbs: bool = False
    destination_id: str = ""
    title: str
    destination: str
    status: PlanStatus
    target_days: int
    lead_time_days: int
    source_updated_at: datetime | None
    source_partial: bool
    items: list[PlanLine]


class PlanSummary(BaseModel):
    destination_id: str = ""
    id: UUID
    store_id: UUID
    store_name: str
    marketplace: str
    title: str
    destination: str
    status: PlanStatus
    revision: int
    quantity: int
    product_count: int
    allocated_quantity: int
    allocation_complete: bool
    allocation_error: str | None
    created_at: datetime
    updated_at: datetime


class PlanView(PlanSummary):
    include_fbs: bool = False
    target_days: int
    lead_time_days: int
    source_updated_at: datetime | None
    source_partial: bool
    items: list[PlanLine]


class PlanList(BaseModel):
    items: list[PlanSummary]
    count: int
    limit: int
    offset: int


class PlanProductsAdd(PlanVariantsLoad):
    product_keys: list[Annotated[str, Field(min_length=1, max_length=100)]] = Field(
        min_length=1, max_length=5000
    )


class PlanCandidates(BaseModel):
    items: list[PlanLine]
    count: int
