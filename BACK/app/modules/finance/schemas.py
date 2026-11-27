from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

Amount = Annotated[Decimal, Field(ge=0, max_digits=16, decimal_places=4, allow_inf_nan=False)]
Currency = Annotated[str, Field(pattern=r"^[A-Z]{3}$")]
Article = Annotated[str, Field(pattern=r"^[1-9][0-9]{0,18}$")]


class CostInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    nm_id: Article
    barcode: str = Field(default="", max_length=100)
    amount: Amount
    currency: Currency
    effective_from: date


class CostView(CostInput):
    created_at: datetime


class VariantCostInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    variant_id: UUID
    amount: Amount
    currency: Currency
    effective_from: date


class VariantCostView(VariantCostInput):
    created_at: datetime


class VariantPreviewItem(VariantCostInput):
    row: int
    marketplace_code: str
    product_title: str
    action: Literal["insert", "unchanged"]


class RowError(BaseModel):
    row: int
    field: str
    code: str
    message: str


class PreviewItem(CostInput):
    row: int
    product_title: str
    action: Literal["insert", "unchanged"]


class ImportPreview(BaseModel):
    preview_id: UUID | None = None
    expires_at: datetime | None = None
    rows_count: int
    valid_count: int
    error_count: int
    errors: list[RowError]
    items: list[PreviewItem | VariantPreviewItem]
    can_apply: bool
    preview_limit: int = 100


class ImportResult(BaseModel):
    preview_id: UUID
    inserted: int
    unchanged: int


class UnitCostResult(BaseModel):
    nm_id: str
    barcode: str
    currency: str
    at: date
    quantity: int
    unit_cost: str | None
    total_cost: str | None
    effective_from: date | None
    matched_by: Literal["article", "barcode"] | None
    available: bool
    size_prices_exist: bool = Field(
        default=False,
        description="No barcode given, but size-specific prices exist. The profit report treats "
        "such sales as unknown cost; pass a barcode for the exact price.",
    )


ExpenseCategory = Literal[
    "packaging", "fulfillment", "transport", "advertising", "rent", "salary", "other"
]


class ExpenseInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID = Field(default_factory=uuid4, description="Reuse for idempotent retries.")
    expense_date: date
    amount: Amount = Field(gt=0)
    currency: Currency | None = None
    comment: str = Field(min_length=1, max_length=500)
    category: ExpenseCategory = "other"
    custom_category: str = Field(default="", max_length=100)

    @model_validator(mode="after")
    def custom_article(self):
        self.custom_category = self.custom_category.strip()
        if self.custom_category:
            self.category = "other"
        return self


class ExpenseView(BaseModel):
    id: UUID
    expense_date: date
    amount: str
    currency: str
    comment: str
    category: ExpenseCategory = "other"
    custom_category: str = Field(default="", max_length=100)
    created_at: datetime


class ExpenseTotal(BaseModel):
    currency: str
    amount: str
    count: int


class ExpenseSummary(BaseModel):
    date_from: date
    date_to: date
    totals: list[ExpenseTotal]
    allocation: Literal["store_only"] = "store_only"


class ProfitValues(BaseModel):
    total_expenses: str | None = None

    @model_validator(mode="after")
    def expense_total(self):
        from app.modules.finance.precision import money

        details = self.financial_details
        total = details.get("total_expenses")
        if total is not None:
            self.total_expenses = total
        elif (
            self.cogs is None
            and details.get("wb_expenses_total") is not None
            and self.external_expenses is not None
        ):
            self.total_expenses = money(
                Decimal(details["wb_expenses_total"]) + Decimal(self.external_expenses)
            )
        return self

    records: int = 0
    sales: int = 0
    returns: int = 0
    net_units: int = 0
    revenue: str | None = Field(
        default=None,
        description="Retail amount of recognized customer sales minus returns, "
        "as a decimal string. "
        "Never for_pay. Null when required amounts or accounting rules are unconfirmed.",
    )
    for_pay: str | None = None
    financial_details: dict[str, str | None] = Field(
        default_factory=dict,
        description="Seller revenue and classified expenses. Included fees are not deducted twice.",
    )
    wb_expenses: dict[str, str | None] = Field(default_factory=dict)
    included_components: dict[str, str | None] = Field(default_factory=dict)
    unreconciled_components: dict[str, str | None] = Field(default_factory=dict)
    settlement_estimate: str | None = None
    cogs: str | None = None
    contribution_before_external_expenses: str | None = None
    external_expenses: str = "0"
    profit_before_tax: str | None = None
    margin_percent: str | None = None
    issues: dict[str, int] = Field(default_factory=dict)
    calculation_complete: bool = False


class ProfitDay(ProfitValues):
    day: date


class ProfitProduct(ProfitValues):
    id: str = ""
    marketplace: str = "wildberries"
    marketplace_code: str = ""
    title: str = ""
    nm_id: str
    vendor_code: str | None = None
    barcodes: list[str] = Field(default_factory=list)


class ProfitReport(BaseModel):
    date_from: date
    date_to: date
    currency: str
    status: Literal["ready", "preparing", "no_data"] = Field(
        description="ready means a snapshot is available, including a partial import snapshot; "
        "use sync-runs to determine import completion. preparing means no usable snapshot yet."
    )
    is_partial: bool = Field(
        description="True for a staged snapshot of an active finance import. "
        "It includes this import only, without adding previously published rows. "
        "ready does not imply that the import has finished.",
    )
    updated_at: datetime | None = Field(
        default=None,
        description="Last data/cost/expense update included in the returned snapshot.",
    )
    date_basis: Literal["report_date"] = "report_date"
    return_cost_policy: Literal["original_sale_assuming_resalable"] = (
        "original_sale_assuming_resalable"
    )
    expense_allocation: Literal["store_only"] = "store_only"
    is_preliminary: bool = Field(
        default=True,
        description="Financial estimate before reconciliation/taxes, independent of is_partial.",
    )
    period_covered: bool = Field(
        default=False,
        description="True only when successful financial imports confirm "
        "the entire requested period. "
        "Always false for a partial snapshot; missing daily dates are not zero-filled.",
    )
    summary: ProfitValues = Field(default_factory=ProfitValues)
    unassigned: ProfitValues = Field(
        default_factory=ProfitValues,
        description="WB operations without a SKU. Included in summary, excluded from product ABC.",
    )
    daily: list[ProfitDay] = Field(default_factory=list)
    products: list[ProfitProduct] = Field(default_factory=list)
    product_count: int = 0
    limit: int
    offset: int


class ABCItem(BaseModel):
    nm_id: str
    vendor_code: str | None = None
    barcodes: list[str] = Field(default_factory=list)
    amount: str
    share_percent: str
    cumulative_percent: str
    group: Literal["A", "B", "C"]


class ProfitABC(BaseModel):
    date_from: date
    date_to: date
    currency: str
    metric: Literal["revenue", "contribution"]
    status: Literal["ready", "preparing", "no_data", "incomplete"]
    expense_allocation: Literal["store_only"] = "store_only"
    is_preliminary: bool = True
    positive_total: str | None = None
    positive_count: int = 0
    negative_count: int = 0
    zero_count: int = 0
    unknown_count: int = 0
    items: list[ABCItem] = Field(default_factory=list)
    limit: int
    offset: int
