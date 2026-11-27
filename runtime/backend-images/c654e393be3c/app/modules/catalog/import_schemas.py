from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class CatalogImportLine(BaseModel):
    row: int
    product_id: str = ""
    vendor_code: str = ""
    barcode: str = ""
    box_multiple: int = 1
    left_variant_id: str = ""
    right_variant_id: str = ""
    right_vendor_code: str = ""
    right_barcode: str = ""


class CatalogImportError(BaseModel):
    row: int
    message: str


class CatalogImportResult(BaseModel):
    preview_id: UUID | None = None
    rows_count: int
    valid_count: int
    errors: list[CatalogImportError] = Field(default_factory=list)
    items: list[CatalogImportLine] = Field(default_factory=list)
    can_apply: bool


class CatalogApplyResult(BaseModel):
    applied: int


class MatchPair(BaseModel):
    left_store_id: UUID
    right_store_id: UUID


class ProductMatchView(BaseModel):
    id: UUID
    left_store_id: UUID
    right_store_id: UUID
    left_vendor_code: str
    right_vendor_code: str
    left_barcode: str
    right_barcode: str
    source: Literal["barcode", "manual"]


class ProductMatchPage(BaseModel):
    items: list[ProductMatchView]
    count: int
    limit: int
    offset: int
