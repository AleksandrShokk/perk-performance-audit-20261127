from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, File, HTTPException, Query, Request, Response, UploadFile
from sqlalchemy import func, select

from app.modules.accounts.reporting import require_reporting_store
from app.modules.accounts.router import find_store, require_workspace
from app.modules.audit.service import audit
from app.modules.auth.dependencies import DB, FullIdentity
from app.modules.supplies import plan_products, plans
from app.modules.supplies.export import plan_csv, plan_items_csv
from app.modules.supplies.models import SupplyPlan
from app.modules.supplies.plan_schemas import (
    PlanCandidates,
    PlanCreate,
    PlanList,
    PlanProductsAdd,
    PlanUpdate,
    PlanVariantsLoad,
    PlanView,
)
from app.modules.supplies.router import selected_stores

router = APIRouter(prefix="/workspaces/{workspace_id}", tags=["Supply plans"])


def plan_store(db, workspace_id, store_id):
    return require_reporting_store(find_store(db, workspace_id, store_id), "supplies")


@router.get("/inventory/plans", response_model=PlanList, operation_id="supplyPlansList")
def list_plans(
    workspace_id: UUID,
    request: Request,
    db: DB,
    identity: FullIdentity,
    store_id: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0, le=50000)] = 0,
):
    stores = {s.id: s for s in selected_stores(db, identity, workspace_id, store_id)}
    query = select(SupplyPlan).where(
        SupplyPlan.workspace_id == workspace_id, SupplyPlan.store_id.in_(stores)
    )
    count = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.scalars(
        query.order_by(SupplyPlan.updated_at.desc(), SupplyPlan.id).limit(limit).offset(offset)
    )
    return PlanList(
        items=[
            plans.summary(row, plans.snapshot(request.app.state.vault, row), stores[row.store_id])
            for row in rows
        ],
        count=count,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/stores/{store_id}/inventory/plans",
    response_model=PlanView,
    operation_id="supplyPlanCreate",
    status_code=201,
)
def create_plan(
    workspace_id: UUID,
    store_id: UUID,
    data: PlanCreate,
    request: Request,
    db: DB,
    identity: FullIdentity,
):
    require_workspace(db, identity, workspace_id, owner=True)
    store = plan_store(db, workspace_id, store_id)
    row = plans.create(db, request.app.state.vault, store, identity.user.id, data)
    result = plans.view(request.app.state.vault, row, store)
    audit(
        db,
        "supply.plan_created",
        user_id=identity.user.id,
        workspace_id=workspace_id,
        target_id=row.id,
    )
    db.commit()
    return result


@router.get("/inventory/plans/{plan_id}", response_model=PlanView, operation_id="supplyPlanGet")
def get_plan(workspace_id: UUID, plan_id: UUID, request: Request, db: DB, identity: FullIdentity):
    require_workspace(db, identity, workspace_id)
    row = plans.find(db, workspace_id, plan_id)
    return plans.view(request.app.state.vault, row, plan_store(db, workspace_id, row.store_id))


@router.put("/inventory/plans/{plan_id}", response_model=PlanView, operation_id="supplyPlanSave")
def save_plan(
    workspace_id: UUID,
    plan_id: UUID,
    data: PlanUpdate,
    request: Request,
    db: DB,
    identity: FullIdentity,
):
    require_workspace(db, identity, workspace_id, owner=True)
    row = plans.find(db, workspace_id, plan_id, lock=True)
    store = plan_store(db, workspace_id, row.store_id)
    plans.update(db, request.app.state.vault, row, identity.user.id, data)
    result = plans.view(request.app.state.vault, row, store)
    audit(
        db,
        "supply.plan_saved",
        user_id=identity.user.id,
        workspace_id=workspace_id,
        target_id=row.id,
    )
    db.commit()
    return result


@router.get(
    "/inventory/plans/{plan_id}/export",
    operation_id="supplyPlanExport",
    response_class=Response,
    responses={200: {"content": {"text/csv": {"schema": {"type": "string", "format": "binary"}}}}},
)
def export_plan(
    workspace_id: UUID, plan_id: UUID, request: Request, db: DB, identity: FullIdentity
):
    require_workspace(db, identity, workspace_id)
    row = plans.find(db, workspace_id, plan_id)
    data = plans.view(request.app.state.vault, row, plan_store(db, workspace_id, row.store_id))
    return Response(
        plan_csv(data),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="perk-supply-plan.csv"',
            "Cache-Control": "no-store",
        },
    )


@router.post(
    "/inventory/plans/{plan_id}/variants",
    response_model=PlanView,
    operation_id="supplyPlanVariantsLoad",
)
def load_plan_variants(
    workspace_id: UUID,
    plan_id: UUID,
    data: PlanVariantsLoad,
    request: Request,
    db: DB,
    identity: FullIdentity,
):
    require_workspace(db, identity, workspace_id, owner=True)
    row = plans.find(db, workspace_id, plan_id, lock=True)
    store = plan_store(db, workspace_id, row.store_id)
    plans.load_variants(db, request.app.state.vault, row, store, identity.user.id, data.revision)
    result = plans.view(request.app.state.vault, row, store)
    audit(
        db,
        "supply.plan_variants_loaded",
        user_id=identity.user.id,
        workspace_id=workspace_id,
        target_id=row.id,
    )
    db.commit()
    return result


@router.get(
    "/inventory/plans/{plan_id}/items-export",
    operation_id="supplyPlanItemsExport",
    response_class=Response,
    responses={200: {"content": {"text/csv": {"schema": {"type": "string", "format": "binary"}}}}},
)
def export_plan_items(
    workspace_id: UUID, plan_id: UUID, request: Request, db: DB, identity: FullIdentity
):
    require_workspace(db, identity, workspace_id)
    row = plans.find(db, workspace_id, plan_id)
    data = plans.view(request.app.state.vault, row, plan_store(db, workspace_id, row.store_id))
    return Response(
        plan_items_csv(data),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="perk-supply-variants.csv"',
            "Cache-Control": "no-store",
        },
    )


@router.get(
    "/inventory/plans/{plan_id}/products",
    response_model=PlanCandidates,
    operation_id="supplyPlanProducts",
)
def plan_products_list(
    workspace_id: UUID,
    plan_id: UUID,
    request: Request,
    db: DB,
    identity: FullIdentity,
    query: str = "",
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    offset: Annotated[int, Query(ge=0, le=5000)] = 0,
):
    require_workspace(db, identity, workspace_id)
    row = plans.find(db, workspace_id, plan_id)
    store = plan_store(db, workspace_id, row.store_id)
    saved = plans.snapshot(request.app.state.vault, row)
    needle = query.strip().casefold()
    existing = {item.product_key for item in saved.items}
    rows = [
        item
        for item in plan_products.candidates(db, request.app.state.vault, store, saved)
        if item.product_key not in existing
        and (
            not needle
            or needle
            in " ".join(
                [
                    item.title,
                    item.vendor_code,
                    item.marketplace_code,
                    *item.barcodes,
                ]
            ).casefold()
        )
    ]
    return PlanCandidates(items=rows[offset : offset + limit], count=len(rows))


@router.post(
    "/inventory/plans/{plan_id}/products",
    response_model=PlanView,
    operation_id="supplyPlanProductsAdd",
)
def add_plan_products(
    workspace_id: UUID,
    plan_id: UUID,
    data: PlanProductsAdd,
    request: Request,
    db: DB,
    identity: FullIdentity,
):
    require_workspace(db, identity, workspace_id, owner=True)
    row = plans.find(db, workspace_id, plan_id, lock=True)
    store = plan_store(db, workspace_id, row.store_id)
    plan_products.add(db, request.app.state.vault, row, store, identity.user.id, data)
    result = plans.view(request.app.state.vault, row, store)
    audit(
        db,
        "supply.plan_products_added",
        user_id=identity.user.id,
        workspace_id=workspace_id,
        target_id=row.id,
    )
    db.commit()
    return result


@router.delete("/inventory/plans/{plan_id}", operation_id="supplyPlanDelete", status_code=204)
def delete_plan(
    workspace_id: UUID,
    plan_id: UUID,
    revision: Annotated[int, Query(ge=1)],
    db: DB,
    identity: FullIdentity,
):
    require_workspace(db, identity, workspace_id, owner=True)
    row = plans.find(db, workspace_id, plan_id, lock=True)
    plan_store(db, workspace_id, row.store_id)
    if row.revision != revision:
        raise HTTPException(409, "План уже изменён. Откройте его заново.")
    audit(
        db,
        "supply.plan_deleted",
        user_id=identity.user.id,
        workspace_id=workspace_id,
        target_id=row.id,
    )
    db.delete(row)
    db.commit()
    return Response(status_code=204)


@router.post(
    "/inventory/plans/{plan_id}/import", response_model=PlanView, operation_id="supplyPlanImport"
)
def import_plan_products(
    workspace_id: UUID,
    plan_id: UUID,
    revision: Annotated[int, Query(ge=1)],
    file: Annotated[UploadFile, File()],
    request: Request,
    db: DB,
    identity: FullIdentity,
):
    from app.modules.supplies import plan_import
    from app.modules.supplies.template_router import workbook
    from app.modules.supplies.template_workbook import InvalidTemplate
    from app.security.limits import rate_limit

    book = None
    try:
        require_workspace(db, identity, workspace_id, owner=True)
        row = plans.find(db, workspace_id, plan_id, lock=True)
        store = plan_store(db, workspace_id, row.store_id)
        rate_limit(
            request.app.state.redis,
            request.app.state.vault,
            "supply-plan-import",
            f"{identity.user.id}:{workspace_id}",
            12,
            60,
        )
        book = workbook(file)
        plan_import.apply(db, request.app.state.vault, row, store, identity.user.id, revision, book)
        result = plans.view(request.app.state.vault, row, store)
        audit(
            db,
            "supply.plan_imported",
            user_id=identity.user.id,
            workspace_id=workspace_id,
            target_id=row.id,
        )
        db.commit()
        return result
    except InvalidTemplate as exc:
        raise HTTPException(422, str(exc)) from None
    finally:
        file.file.close()
        if book:
            book.close()
