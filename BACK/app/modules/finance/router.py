import json
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, File, HTTPException, Query, Request, Response, UploadFile
from pydantic import BaseModel
from sqlalchemy import delete, select, text
from sqlalchemy.dialects.postgresql import insert

from app.integrations.wildberries.data import Source
from app.modules.accounts.access import (
    allows,
    hide_profit,
    member_for,
    require_permission,
)
from app.modules.accounts.models import Store, Workspace
from app.modules.accounts.reporting import require_reporting_store
from app.modules.accounts.router import find_store, require_workspace
from app.modules.audit.service import audit
from app.modules.auth.dependencies import DB, FullIdentity, now
from app.modules.finance import jobs, service
from app.modules.finance import report as reports
from app.modules.finance.models import (
    CostImport,
    ExternalExpense,
    FinanceProjection,
    ProductCost,
)
from app.modules.finance.projection import FORMAT
from app.modules.finance.schemas import (
    CostInput,
    CostView,
    Currency,
    ExpenseInput,
    ExpenseSummary,
    ExpenseView,
    ImportPreview,
    ImportResult,
    ProfitABC,
    ProfitReport,
    UnitCostResult,
)
from app.modules.finance.xlsx import (
    HEADERS,
    MAX_UPLOAD,
    InvalidWorkbook,
    build_template,
    read_rows,
)
from app.modules.sync.models import WBRecord
from app.modules.sync.schemas import moscow_today
from app.modules.sync.service import context
from app.security.limits import rate_limit

router = APIRouter(prefix="/workspaces/{workspace_id}/stores/{store_id}", tags=["Finance"])
XLSX_MEDIA = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class SellerBalance(BaseModel):
    currency: str | None = None
    current: str | None = None
    for_withdraw: str | None = None
    updated_at: datetime | None = None


def balance_snapshot(db, vault, workspace_id, store_id):
    row = db.get(WBRecord, (workspace_id, store_id, Source.BALANCE, "current"))
    if row is None:
        return SellerBalance()
    data = json.loads(
        vault.open(row.ciphertext, context(workspace_id, store_id, Source.BALANCE, "current"))
    )
    return SellerBalance(**data, updated_at=row.updated_at)


@router.get("/finance/balance", response_model=SellerBalance, operation_id="financeBalance")
def seller_balance(
    workspace_id: UUID, store_id: UUID, request: Request, db: DB, identity: FullIdentity
):
    """Read the stored WB balance. No provider calls on the request path."""
    require_workspace(db, identity, workspace_id)
    require_reporting_store(find_store(db, workspace_id, store_id))
    return balance_snapshot(db, request.app.state.vault, workspace_id, store_id)


def owner_store(
    db,
    identity,
    workspace_id,
    store_id,
    *,
    lock=False,
    permission=None,
    feature="reports",
):
    if permission:
        require_permission(db, identity, workspace_id, permission)
    else:
        require_workspace(db, identity, workspace_id, owner=True)
    if lock and permission:
        locked = db.scalar(
            text("SELECT perk_lock_store(:ws,:sid,:permission)"),
            {"ws": workspace_id, "sid": store_id, "permission": permission},
        )
        if not locked:
            raise HTTPException(404, "Магазин не найден.")
        lock = False  # The scoped SQL function holds the same key-share lock for this transaction.
    store = (
        db.scalar(
            select(Store)
            .where(Store.workspace_id == workspace_id, Store.id == store_id)
            .with_for_update(key_share=True)
        )
        if lock
        else (find_store(db, workspace_id, store_id))
    )
    if not store or not store.is_active:
        raise HTTPException(404, "Магазин не найден.")
    return require_reporting_store(store, feature)


@router.get(
    "/costs/template",
    operation_id="costsDownloadTemplate",
    response_class=Response,
    responses={200: {"content": {XLSX_MEDIA: {"schema": {"type": "string", "format": "binary"}}}}},
)
def cost_template(
    workspace_id: UUID, store_id: UUID, request: Request, db: DB, identity: FullIdentity
):
    store = owner_store(
        db,
        identity,
        workspace_id,
        store_id,
        permission="costs.write",
        feature="catalog",
    )
    if store.marketplace == "ozon":
        from app.modules.finance import variant_import
        from app.modules.sync.schemas import moscow_today

        workspace = db.get(Workspace, workspace_id)
        return Response(
            variant_import.template(
                db, request.app.state.vault, store, workspace.currency, moscow_today()
            ),
            media_type=XLSX_MEDIA,
        )
    return Response(
        build_template(HEADERS),
        media_type=XLSX_MEDIA,
        headers={"Content-Disposition": 'attachment; filename="perk-cost-template.xlsx"'},
    )


@router.post("/cost-imports", response_model=ImportPreview, operation_id="costsPreviewImport")
def preview_costs(
    workspace_id: UUID,
    store_id: UUID,
    file: Annotated[UploadFile, File()],
    request: Request,
    db: DB,
    identity: FullIdentity,
):
    store = owner_store(
        db,
        identity,
        workspace_id,
        store_id,
        permission="costs.write",
        feature="catalog",
    )
    rate_limit(
        request.app.state.redis,
        request.app.state.vault,
        "cost-import",
        str(store_id),
        5,
        60,
    )
    legacy = False
    try:
        payload = file.file.read(MAX_UPLOAD + 1)
        if store.marketplace == "ozon":
            from app.modules.finance.variant_import import OZON_HEADERS

            raw_rows = read_rows(payload, headers=OZON_HEADERS)
        else:
            try:
                raw_rows = read_rows(payload)
            except InvalidWorkbook:
                from app.modules.finance.xlsx import LEGACY_HEADERS

                raw_rows = read_rows(payload, headers=LEGACY_HEADERS)
                legacy = True
    except InvalidWorkbook as exc:
        raise HTTPException(422, str(exc)) from None
    finally:
        file.file.close()
    if store.marketplace == "wildberries" and not legacy:
        from app.modules.finance.vendor_import import resolve_rows

        raw_rows, resolution_errors = resolve_rows(
            db, request.app.state.vault, workspace_id, store_id, raw_rows
        )
        if resolution_errors:
            return ImportPreview(
                preview_id=None,
                expires_at=None,
                rows_count=len(raw_rows) + len(resolution_errors),
                valid_count=0,
                error_count=len(resolution_errors),
                errors=resolution_errors,
                items=[],
                can_apply=False,
            )
    workspace = db.get(Workspace, workspace_id)
    db.execute(
        delete(CostImport).where(
            *service.scope(CostImport, workspace_id, store_id),
            CostImport.expires_at < now(),
        )
    )
    if (
        len(
            db.scalars(
                select(CostImport.id)
                .where(
                    *service.scope(CostImport, workspace_id, store_id),
                )
                .limit(20)
            ).all()
        )
        >= 20
    ):
        raise HTTPException(429, "Слишком много предпросмотров. Повторите через 30 минут.")
    from app.modules.finance import variant_import

    result = (
        variant_import.preview(
            db,
            request.app.state.vault,
            store,
            identity.user.id,
            raw_rows,
            workspace.currency,
            now(),
        )
        if store.marketplace == "ozon"
        else service.create_preview(
            db,
            request.app.state.vault,
            workspace_id,
            store_id,
            identity.user.id,
            raw_rows,
            workspace.currency,
            now(),
        )
    )
    if result.can_apply:
        audit(
            db,
            "cost.import.previewed",
            user_id=identity.user.id,
            workspace_id=workspace_id,
            target_id=result.preview_id,
        )
    db.commit()
    return result


@router.post(
    "/cost-imports/{preview_id}/apply",
    response_model=ImportResult,
    operation_id="costsApplyImport",
)
def apply_costs(
    workspace_id: UUID,
    store_id: UUID,
    preview_id: UUID,
    request: Request,
    db: DB,
    identity: FullIdentity,
):
    store = owner_store(
        db,
        identity,
        workspace_id,
        store_id,
        lock=True,
        permission="costs.write",
        feature="catalog",
    )
    preview = db.scalar(
        select(CostImport)
        .where(
            *service.scope(CostImport, workspace_id, store_id),
            CostImport.id == preview_id,
        )
        .with_for_update()
    )
    if not preview:
        raise HTTPException(404, "Предпросмотр не найден.")
    if store.marketplace == "ozon":
        from app.modules.finance import variant_import

        result = variant_import.apply(
            db, request.app.state.vault, store, identity.user.id, preview, now()
        )
    else:
        result = service.apply_preview(
            db,
            request.app.state.vault,
            workspace_id,
            store_id,
            identity.user.id,
            preview,
            now(),
        )
    audit(
        db,
        "cost.import.applied",
        user_id=identity.user.id,
        workspace_id=workspace_id,
        target_id=preview_id,
    )
    db.commit()
    return result


@router.post("/costs", response_model=CostView, operation_id="costsSave")
def save_cost(
    workspace_id: UUID,
    store_id: UUID,
    data: CostInput,
    request: Request,
    db: DB,
    identity: FullIdentity,
):
    owner_store(db, identity, workspace_id, store_id, lock=True, permission="costs.write")
    values = service.barcode_cost_inputs(db, request.app.state.vault, workspace_id, store_id, data)
    errors, _, existing = service.validate_costs(
        db, request.app.state.vault, workspace_id, store_id, list(enumerate(values, 1))
    )
    if errors:
        raise HTTPException(409, errors[0].message)
    for value in values:
        if service.price_key(value) in existing:
            continue
        db.execute(
            insert(ProductCost)
            .values(
                workspace_id=workspace_id,
                store_id=store_id,
                created_by=identity.user.id,
                **value.model_dump(exclude={"amount"}),
                ciphertext=request.app.state.vault.seal(
                    str(value.amount), service.price_aad(workspace_id, store_id, value)
                ),
            )
            .on_conflict_do_nothing()
        )
    saved = service.existing_prices(db, workspace_id, store_id, [data])[service.price_key(data)]
    if service.unit_amount(request.app.state.vault, saved) != data.amount:
        raise HTTPException(
            409, "На эту дату уже сохранена другая себестоимость. Обновите историю."
        )
    audit(
        db,
        "cost.created",
        user_id=identity.user.id,
        workspace_id=workspace_id,
        target_id=store_id,
    )
    result = CostView(**data.model_dump(), created_at=saved.created_at)
    db.commit()
    return result


@router.get("/costs", response_model=list[CostView], operation_id="costsList")
def costs(
    workspace_id: UUID,
    store_id: UUID,
    request: Request,
    db: DB,
    identity: FullIdentity,
    nm_id: Annotated[str | None, Query(pattern=r"^[1-9][0-9]{0,18}$")] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0, le=50000)] = 0,
):
    require_workspace(db, identity, workspace_id)
    require_reporting_store(find_store(db, workspace_id, store_id))
    rows = db.scalars(
        select(ProductCost)
        .where(
            *service.scope(ProductCost, workspace_id, store_id),
            *([ProductCost.nm_id == nm_id] if nm_id else []),
        )
        .order_by(
            ProductCost.effective_from.desc() if nm_id else ProductCost.nm_id,
            ProductCost.nm_id,
            ProductCost.barcode,
            ProductCost.currency,
            ProductCost.effective_from,
        )
        .limit(limit)
        .offset(offset)
    ).all()
    return [
        CostView(
            nm_id=row.nm_id,
            barcode=row.barcode,
            currency=row.currency,
            effective_from=row.effective_from,
            amount=service.unit_amount(request.app.state.vault, row),
            created_at=row.created_at,
        )
        for row in rows
    ]


@router.get("/costs/calculate", response_model=UnitCostResult, operation_id="costsCalculate")
def calculate_cost(
    workspace_id: UUID,
    store_id: UUID,
    request: Request,
    db: DB,
    identity: FullIdentity,
    nm_id: Annotated[str, Query(pattern=r"^[1-9][0-9]{0,18}$")],
    at: date,
    barcode: Annotated[str, Query(max_length=100)] = "",
    quantity: Annotated[int, Query(ge=0, le=1000000)] = 1,
    currency: Currency | None = None,
):
    require_workspace(db, identity, workspace_id)
    require_reporting_store(find_store(db, workspace_id, store_id))
    currency = currency or db.get(Workspace, workspace_id).currency
    return service.resolve_cost(
        db,
        request.app.state.vault,
        workspace_id,
        store_id,
        nm_id,
        barcode,
        currency,
        at,
        quantity,
    )


@router.post(
    "/expenses",
    response_model=ExpenseView,
    status_code=201,
    operation_id="expensesCreate",
)
def create_expense(
    workspace_id: UUID,
    store_id: UUID,
    data: ExpenseInput,
    request: Request,
    db: DB,
    identity: FullIdentity,
):
    owner_store(
        db,
        identity,
        workspace_id,
        store_id,
        lock=True,
        permission="expenses.write",
        feature="finance",
    )
    currency = data.currency or db.get(Workspace, workspace_id).currency
    value = {
        "amount": str(data.amount),
        "comment": data.comment.strip(),
        "category": data.category,
        "custom_category": data.custom_category.strip(),
    }
    if not value["comment"]:
        raise HTTPException(422, "Добавьте комментарий к расходу.")
    saved = db.get(ExternalExpense, (workspace_id, store_id, data.request_id))
    vault = request.app.state.vault
    aad = service.expense_aad(workspace_id, store_id, data.request_id)
    if saved:
        old = json.loads(vault.open(saved.ciphertext, aad))
        if (
            saved.deleted_at
            or saved.expense_date != data.expense_date
            or saved.currency != currency
            or old["comment"] != value["comment"]
            or old.get("category", "other") != data.category
            or old.get("custom_category", "") != data.custom_category.strip()
            or Decimal(old["amount"]) != data.amount
        ):
            raise HTTPException(409, "request_id уже использован для другого расхода.")
        return service.expense_view(vault, saved)
    row = ExternalExpense(
        workspace_id=workspace_id,
        store_id=store_id,
        id=data.request_id,
        expense_date=data.expense_date,
        currency=currency,
        created_by=identity.user.id,
        ciphertext=vault.seal(json.dumps(value), aad),
    )
    db.add(row)
    db.flush()
    result = service.expense_view(vault, row)
    audit(
        db,
        "expense.created",
        user_id=identity.user.id,
        workspace_id=workspace_id,
        target_id=row.id,
    )
    db.commit()
    return result


@router.get("/expenses", response_model=list[ExpenseView], operation_id="expensesList")
def expenses(
    workspace_id: UUID,
    store_id: UUID,
    request: Request,
    db: DB,
    identity: FullIdentity,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0, le=50000)] = 0,
):
    require_workspace(db, identity, workspace_id)
    require_reporting_store(find_store(db, workspace_id, store_id), "finance")
    rows = db.scalars(
        select(ExternalExpense)
        .where(
            *service.scope(ExternalExpense, workspace_id, store_id),
            ExternalExpense.deleted_at.is_(None),
        )
        .order_by(ExternalExpense.expense_date.desc(), ExternalExpense.id)
        .limit(limit)
        .offset(offset)
    ).all()
    return [service.expense_view(request.app.state.vault, row) for row in rows]


@router.get("/expenses/totals", response_model=ExpenseSummary, operation_id="expensesTotals")
def expenses_summary(
    workspace_id: UUID,
    store_id: UUID,
    date_from: date,
    date_to: date,
    request: Request,
    db: DB,
    identity: FullIdentity,
):
    require_workspace(db, identity, workspace_id)
    require_reporting_store(find_store(db, workspace_id, store_id), "finance")
    if date_from > date_to:
        raise HTTPException(422, "Начало периода должно быть не позже его конца.")
    return ExpenseSummary(
        date_from=date_from,
        date_to=date_to,
        totals=service.expense_totals(
            db, request.app.state.vault, workspace_id, store_id, date_from, date_to
        ),
    )


@router.delete("/expenses/{expense_id}", status_code=204, operation_id="expensesDelete")
def remove_expense(
    workspace_id: UUID, store_id: UUID, expense_id: UUID, db: DB, identity: FullIdentity
):
    owner_store(
        db,
        identity,
        workspace_id,
        store_id,
        lock=True,
        permission="expenses.write",
        feature="finance",
    )
    row = db.get(ExternalExpense, (workspace_id, store_id, expense_id))
    if not row:
        raise HTTPException(404, "Расход не найден.")
    if not row.deleted_at:
        row.deleted_at = now()
        audit(
            db,
            "expense.removed",
            user_id=identity.user.id,
            workspace_id=workspace_id,
            target_id=expense_id,
        )
    db.commit()


def financial_report(
    workspace_id,
    store_id,
    request,
    db,
    identity,
    start,
    end,
    currency,
    limit,
    offset,
    include_product_identity=True,
):
    require_workspace(db, identity, workspace_id)
    store = find_store(db, workspace_id, store_id)
    require_reporting_store(store, "finance_details")
    if store.marketplace == "ozon":
        from app.modules.finance.ozon_report import report as ozon_report
        from app.modules.insights.ozon_read import ensure_range, period

        period(start, end)
        ensure_range(db, workspace_id, store_id, start, source="finance")
        result = ozon_report(
            db,
            request.app.state.vault,
            workspace_id,
            store,
            start,
            end,
            currency or db.get(Workspace, workspace_id).currency,
            limit,
            offset,
            can_profit=allows(member_for(db, identity.user.id, workspace_id), "profit.read"),
        )
        db.commit()
        from app.db.session import set_actor

        set_actor(db, identity.user.id)
        return result
    if start > end or end > moscow_today():
        raise HTTPException(422, "Выберите период с началом не позже конца и без будущих дат.")
    workspace = db.get(Workspace, workspace_id)
    result = reports.report(
        db,
        request.app.state.redis,
        request.app.state.vault,
        workspace_id,
        store_id,
        start,
        end,
        currency or workspace.currency,
        limit,
        offset,
    )
    if include_product_identity and result.products:
        service.identify_products(
            db, request.app.state.vault, workspace_id, store_id, result.products
        )
    state = db.get(FinanceProjection, (workspace_id, store_id))
    if result.status == "preparing" or (state and state.format_version != FORMAT):
        jobs.enqueue(
            request.app.state.redis,
            request.app.state.vault,
            workspace_id,
            store_id,
            workspace.owner_user_id,
        )
    return (
        result
        if allows(member_for(db, identity.user.id, workspace_id), "profit.read")
        else hide_profit(result)
    )


@router.get(
    "/finance/summary",
    response_model=ProfitReport,
    operation_id="financeSummary",
    description="Returns a financial snapshot from stored daily aggregates. "
    "During an active import, "
    "available preview days are returned with ready and is_partial=true, preserving published "
    "days outside the preview. Each day comes from one source only. Failed imports fall back "
    "to the previous successful report. While preparing a newer projection, the previous "
    "projection remains readable with period_covered=false. "
    "No WB requests or raw-import rebuilds are performed by this read.",
)
def finance_summary(
    workspace_id: UUID,
    store_id: UUID,
    date_from: date,
    date_to: date,
    request: Request,
    db: DB,
    identity: FullIdentity,
    currency: Currency | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0, le=50000)] = 0,
):
    return financial_report(
        workspace_id,
        store_id,
        request,
        db,
        identity,
        date_from,
        date_to,
        currency,
        limit,
        offset,
    )


@router.get("/finance/abc", response_model=ProfitABC, operation_id="financeABC")
def finance_abc(
    workspace_id: UUID,
    store_id: UUID,
    date_from: date,
    date_to: date,
    request: Request,
    db: DB,
    identity: FullIdentity,
    currency: Currency | None = None,
    metric: Literal["revenue", "contribution"] = "contribution",
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0, le=50000)] = 0,
    a_threshold: Annotated[Decimal, Query(gt=0, lt=100)] = Decimal(80),
    b_threshold: Annotated[Decimal, Query(gt=0, lt=100)] = Decimal(95),
):
    if a_threshold >= b_threshold:
        raise HTTPException(422, "Порог A должен быть меньше порога B.")
    result = financial_report(
        workspace_id,
        store_id,
        request,
        db,
        identity,
        date_from,
        date_to,
        currency,
        50000,
        0,
    )
    return reports.abc(result, metric, limit, offset, a_threshold, b_threshold)
