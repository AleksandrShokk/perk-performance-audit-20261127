from datetime import date, timedelta
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select

from app.modules.accounts.router import find_store, require_workspace
from app.modules.audit.service import audit
from app.modules.auth.dependencies import DB, FullIdentity, now
from app.modules.finance import economics, service
from app.modules.finance.models import TaxSetting
from app.modules.finance.router import financial_report, owner_store
from app.modules.finance.schemas import Currency
from app.modules.insights import compute
from app.modules.insights.router import Freshness, served
from app.modules.sync.schemas import moscow_today

router = APIRouter(prefix="/workspaces/{workspace_id}/stores/{store_id}", tags=["Economics"])
Regime = Literal["none", "usn_income", "usn_income_expense", "profit"]
Rate = Annotated[Decimal, Field(ge=0, le=100, max_digits=5, decimal_places=2)]
UnitStatus = Literal["profitable", "marginal", "loss", "unknown"]


class TaxSettingInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    effective_from: date
    regime: Regime
    rate: Rate = Field(description="Tax rate, percent: 6 / 15 for USN, 25 for profit tax.")
    vat_rate: Rate = Field(default=Decimal(0), description="VAT included in prices, percent.")
    income_base: Literal["revenue", "payout"] = Field(
        default="revenue",
        description="revenue: buyer price (agent scheme); payout: WB transfer to the seller.",
    )

    @model_validator(mode="after")
    def consistent(self):
        if self.regime == "none" and (self.rate or self.vat_rate):
            raise ValueError("Без налогового режима налоговые ставки должны быть равны нулю.")
        return self


class TaxSettingView(TaxSettingInput):
    model_config = ConfigDict(from_attributes=True)


class NetProfit(BaseModel):
    date_from: date
    date_to: date
    currency: str
    status: str
    is_preliminary: bool = True
    is_partial: bool = Field(description="Snapshot of an active finance import.")
    period_covered: bool = Field(description="Successful imports confirm the whole period.")
    tax_setting: TaxSettingView | None
    tax_setting_changed_in_period: bool = Field(
        description="Another setting starts inside the period; the last one was applied."
    )
    revenue: str | None
    profit_before_tax: str | None
    vat: str | None
    tax: str | None
    net_profit: str | None
    net_margin_percent: str | None
    notes: list[str]
    freshness: Freshness


class UnitEconomicsItem(BaseModel):
    id: str = ""
    marketplace: str = "wildberries"
    marketplace_code: str = ""
    nm_id: str
    net_units: int
    sales: int
    returns: int
    price: str | None = Field(description="Average buyer price per net unit.")
    marketplace_fee: str | None = Field(description="Price minus WB payout, per unit.")
    logistics: str | None
    storage: str | None
    acceptance: str | None
    penalties: str | None
    cost_price: str | None
    tax: str | None
    profit: str | None
    margin_percent: str | None
    total_profit: str | None
    status: UnitStatus
    issues: dict[str, int]


class UnitEconomics(BaseModel):
    date_from: date
    date_to: date
    currency: str
    status: str
    is_partial: bool
    period_covered: bool
    products_truncated: bool = Field(
        description="The store has more SKUs than one calculation holds; counts are incomplete."
    )
    margin_target_percent: str
    counts: dict[str, int]
    items: list[UnitEconomicsItem]
    product_count: int
    limit: int
    offset: int
    freshness: Freshness


class SimulationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    nm_id: str = Field(pattern=r"^[1-9][0-9]{0,18}$")
    price: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    cost_price: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    units_expected: int | None = Field(default=None, ge=1, le=1_000_000)
    date_from: date | None = None
    date_to: date | None = None
    currency: Currency | None = None


class Simulation(BaseModel):
    nm_id: str
    price: str
    payout_share_percent: str = Field(description="Observed WB payout / buyer price.")
    payout: str
    wb_costs_per_unit: str = Field(description="Observed logistics, storage, acceptance per unit.")
    cost_price: str
    taxes: str
    profit_per_unit: str
    margin_percent: str | None
    break_even_price: str | None
    history_units: int
    history_price: str
    units_to_match_history_profit: int | None
    expected_profit: str | None
    history_from: date
    history_to: date


setting_at = compute.tax_setting


@router.get("/tax-settings", response_model=list[TaxSettingView], operation_id="taxSettingsList")
def tax_settings(workspace_id: UUID, store_id: UUID, db: DB, identity: FullIdentity):
    require_workspace(db, identity, workspace_id)
    find_store(db, workspace_id, store_id)
    return db.scalars(
        select(TaxSetting)
        .where(*service.scope(TaxSetting, workspace_id, store_id))
        .order_by(TaxSetting.effective_from)
    ).all()


@router.put("/tax-settings", response_model=TaxSettingView, operation_id="taxSettingsSave")
def save_tax_setting(
    workspace_id: UUID,
    store_id: UUID,
    data: TaxSettingInput,
    request: Request,
    db: DB,
    identity: FullIdentity,
):
    store = owner_store(
        db, identity, workspace_id, store_id, lock=True, permission="taxes.write", feature="finance"
    )
    row = db.get(TaxSetting, (workspace_id, store_id, data.effective_from))
    if not row:
        row = TaxSetting(
            workspace_id=workspace_id,
            store_id=store_id,
            effective_from=data.effective_from,
            created_by=identity.user.id,
        )
        db.add(row)
    row.regime, row.rate, row.vat_rate = data.regime, data.rate, data.vat_rate
    row.income_base = data.income_base
    row.updated_at = now()
    audit(db, "tax.setting_saved", user_id=identity.user.id, workspace_id=workspace_id)
    db.commit()
    refresh_dependents(request, workspace_id, store_id, identity, store.marketplace)
    return row


@router.delete("/tax-settings/{effective_from}", status_code=204, operation_id="taxSettingsDelete")
def delete_tax_setting(
    workspace_id: UUID,
    store_id: UUID,
    effective_from: date,
    request: Request,
    db: DB,
    identity: FullIdentity,
):
    store = owner_store(
        db, identity, workspace_id, store_id, lock=True, permission="taxes.write", feature="finance"
    )
    row = db.get(TaxSetting, (workspace_id, store_id, effective_from))
    if not row:
        raise HTTPException(404, "Настройка не найдена.")
    db.delete(row)
    audit(db, "tax.setting_deleted", user_id=identity.user.id, workspace_id=workspace_id)
    db.commit()
    refresh_dependents(request, workspace_id, store_id, identity, store.marketplace)


def refresh_dependents(request, workspace_id, store_id, identity, marketplace="wildberries"):
    """Recalculate default screens now instead of waiting for the next read or warm cycle."""
    from app.workers.tasks import warm_insights

    if marketplace == "ozon":
        return
    state = request.app.state
    warm_insights(state.redis, state.vault, workspace_id, store_id, identity.user.id)


@router.get("/finance/net-profit", response_model=NetProfit, operation_id="financeNetProfit")
def finance_net_profit(
    workspace_id: UUID,
    store_id: UUID,
    request: Request,
    response: Response,
    db: DB,
    identity: FullIdentity,
    date_from: date | None = None,
    date_to: date | None = None,
    currency: Currency | None = None,
):
    """Profit before tax, VAT, tax estimate and net profit. Default: last 30 days."""
    store = find_store(db, workspace_id, store_id)
    if store.marketplace == "ozon":
        params = compute.period_params(date_from, date_to, currency)
        start, end = compute.dates(params)
        report = financial_report(
            workspace_id, store_id, request, db, identity, start, end, currency, 0, 0
        )
        setting = setting_at(db, workspace_id, store_id, end)
        changed = compute.tax_changed(db, workspace_id, store_id, start, end)
        result = economics.net_profit(setting, report.summary)
        if changed:
            result.update(vat=None, tax=None, net_profit=None, net_margin_percent=None)
        return NetProfit(
            date_from=start,
            date_to=end,
            currency=report.currency,
            status=report.status,
            is_partial=report.is_partial,
            period_covered=report.period_covered,
            tax_setting=setting,
            tax_setting_changed_in_period=changed,
            revenue=report.summary.revenue,
            freshness=Freshness(
                computed_at=report.updated_at or now(), stale=report.status == "preparing"
            ),
            **result,
        )
    params = compute.period_params(date_from, date_to, currency)
    data, fresh = served(
        request, response, db, identity, workspace_id, store_id, "net_profit", params
    )
    if fresh is None:
        return data
    start, end = compute.dates(params)
    # Tax-period metadata comes from the same snapshot as the amounts (consistent view).
    return {**data, "date_from": start, "date_to": end, "freshness": fresh}


@router.get(
    "/finance/unit-economics", response_model=UnitEconomics, operation_id="financeUnitEconomics"
)
def finance_unit_economics(
    workspace_id: UUID,
    store_id: UUID,
    request: Request,
    response: Response,
    db: DB,
    identity: FullIdentity,
    date_from: date | None = None,
    date_to: date | None = None,
    currency: Currency | None = None,
    margin_target: Annotated[Decimal, Query(ge=0, le=100)] = Decimal(15),
    status: UnitStatus | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0, le=50000)] = 0,
):
    """Per-unit economics for every SKU, worst total profit first. Default: last 30 days."""
    params = compute.period_params(
        date_from, date_to, currency, margin_target=format(margin_target.normalize(), "f")
    )
    store = find_store(db, workspace_id, store_id)
    if store.marketplace == "ozon":
        start, end = compute.dates(params)
        report = financial_report(
            workspace_id, store_id, request, db, identity, start, end, currency, 50000, 0
        )
        setting = setting_at(db, workspace_id, store_id, end)
        changed = compute.tax_changed(db, workspace_id, store_id, start, end)
        rows = [
            {
                **economics.unit_row(product, setting, margin_target),
                "id": product.id,
                "marketplace": "ozon",
                "marketplace_code": product.marketplace_code,
            }
            for product in report.products
        ]
        if changed:
            for row in rows:
                row.update(
                    tax=None, profit=None, total_profit=None, margin_percent=None, status="unknown"
                )
        data = {
            "items": rows,
            "currency": report.currency,
            "status": report.status,
            "is_partial": report.is_partial,
            "period_covered": report.period_covered,
            "products_truncated": report.product_count > 50000,
        }
        fresh = Freshness(
            computed_at=report.updated_at or now(), stale=report.status == "preparing"
        )
    else:
        data, fresh = served(
            request, response, db, identity, workspace_id, store_id, "unit_economics", params
        )
    if fresh is None:
        return data
    start, end = compute.dates(params)
    rows = data["items"]
    counts = {}
    for row in rows:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    if status:
        rows = [row for row in rows if row["status"] == status]
    rows.sort(key=lambda row: (Decimal(row["total_profit"] or 0), row["nm_id"]))
    return UnitEconomics(
        date_from=start,
        date_to=end,
        currency=data["currency"],
        status=data["status"],
        is_partial=data["is_partial"],
        period_covered=data["period_covered"],
        products_truncated=data["products_truncated"],
        margin_target_percent=params["margin_target"],
        counts=counts,
        items=rows[offset : offset + limit],
        product_count=len(rows),
        limit=limit,
        offset=offset,
        freshness=fresh,
    )


@router.post("/finance/simulate", response_model=Simulation, operation_id="financeSimulatePrice")
def finance_simulate(
    workspace_id: UUID,
    store_id: UUID,
    data: SimulationInput,
    request: Request,
    db: DB,
    identity: FullIdentity,
):
    end = data.date_to or moscow_today() - timedelta(days=1)
    start, end = compute.validated_period(data.date_from or end - timedelta(days=29), end)
    report = financial_report(
        workspace_id, store_id, request, db, identity, start, end, data.currency, 50000, 0
    )
    product = next((item for item in report.products if item.nm_id == data.nm_id), None)
    if report.status != "ready" or product is None:
        raise HTTPException(
            422, "Нет финансовой истории этого товара за период. Выберите другой период."
        )
    cost = data.cost_price
    if cost is None:
        resolved = service.resolve_cost(
            db,
            request.app.state.vault,
            workspace_id,
            store_id,
            data.nm_id,
            "",
            report.currency,
            end,
        )
        if not resolved.available:
            raise HTTPException(422, "Укажите себестоимость: в истории её нет.")
        cost = Decimal(resolved.unit_cost)
    result = economics.simulate(
        product,
        setting_at(db, workspace_id, store_id, end),
        price=data.price,
        cost_price=cost,
        units_expected=data.units_expected,
    )
    if result is None:
        raise HTTPException(
            422, "В истории товара не хватает сумм для расчёта: нет продаж или расходов WB."
        )
    return Simulation(**result, history_from=start, history_to=end)
