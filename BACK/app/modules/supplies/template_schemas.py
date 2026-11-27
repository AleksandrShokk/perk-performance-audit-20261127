from typing import Literal

from pydantic import BaseModel, Field

IdentifierType = Literal["barcode", "vendor_code", "fbo_sku"]


class TemplateMapping(BaseModel):
    sheet: str = Field(min_length=1, max_length=120)
    header_row: int = Field(ge=1, le=50)
    first_row: int = Field(ge=2, le=100)
    identifier_column: str = Field(pattern=r"^[A-Z]{1,3}$")
    quantity_column: str = Field(pattern=r"^[A-Z]{1,3}$")
    identifier_type: IdentifierType
    mode: Literal["append", "match"] = "append"


class TemplateFillParams(TemplateMapping):
    revision: int = Field(ge=1)
    digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    data_digest: str = Field(pattern=r"^[a-f0-9]{64}$")


class TemplateColumn(BaseModel):
    key: str
    label: str


class TemplateHeader(BaseModel):
    row: int
    columns: list[TemplateColumn]


class TemplateSheet(BaseModel):
    name: str
    headers: list[TemplateHeader]


class TemplatePosition(BaseModel):
    identifier: str
    quantity: int


class TemplateChoice(BaseModel):
    value: IdentifierType
    label: str
    count: int
    units: int
    data_digest: str
    error: str | None
    preview: list[TemplatePosition]


class TemplateInspection(BaseModel):
    digest: str
    revision: int
    sheets: list[TemplateSheet]
    choices: list[TemplateChoice]
    suggested: TemplateMapping | None
