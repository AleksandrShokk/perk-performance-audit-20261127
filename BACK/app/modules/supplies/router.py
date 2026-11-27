from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request, Response

from app.modules.accounts.access import allows
from app.modules.accounts.reporting import reporting_stores
from app.modules.accounts.router import require_workspace
from app.modules.auth.dependencies import DB, FullIdentity
from app.modules.supplies import service
from app.modules.supplies.export import requirements_csv, requirements_xlsx
from app.modules.supplies.schemas import ReplenishmentOverview, SupplyList

router = APIRouter(prefix="/workspaces/{workspace_id}/inventory", tags=["Inventory"])


def selected_stores(db, identity, workspace_id, store_id, feature="supplies"):
    member = require_workspace(db, identity, workspace_id)
    if not allows(member, "inventory.read"):
        raise HTTPException(403, "Нет доступа к остаткам.")
    return reporting_stores(db, workspace_id, store_id, feature=feature)


@router.get(
    "/replenishment",
    response_model=ReplenishmentOverview,
    operation_id="inventoryReplenishment",
)
def inventory_replenishment(
    workspace_id: UUID,
    request: Request,
    db: DB,
    identity: FullIdentity,
    store_id: UUID | None = None,
    destination_id: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
    urgent_only: bool = False,
    include_fbs: bool = False,
    target_days: Annotated[int, Query(ge=1, le=180)] = 30,
    lead_time_days: Annotated[int, Query(ge=0, le=90)] = 7,
    limit: Annotated[int, Query(ge=0, le=100)] = 3,
    offset: Annotated[int, Query(ge=0, le=50000)] = 0,
):
    return service.replenishment(
        db,
        request.app.state.vault,
        workspace_id,
        selected_stores(db, identity, workspace_id, store_id),
        urgent_only=urgent_only,
        destination_id=destination_id,
        include_fbs=include_fbs,
        target_days=target_days,
        lead_time_days=lead_time_days,
        limit=limit,
        offset=offset,
    )


@router.get("/supplies", response_model=SupplyList, operation_id="inventorySupplies")
def inventory_supplies(
    workspace_id: UUID,
    request: Request,
    db: DB,
    identity: FullIdentity,
    store_id: UUID | None = None,
    limit: Annotated[int, Query(ge=0, le=100)] = 3,
    offset: Annotated[int, Query(ge=0, le=50000)] = 0,
):
    return service.supplies(
        db,
        request.app.state.vault,
        workspace_id,
        selected_stores(db, identity, workspace_id, store_id, feature="supply_history"),
        limit=limit,
        offset=offset,
    )


@router.get(
    "/replenishment/export",
    operation_id="inventoryReplenishmentExport",
    response_class=Response,
    responses={200: {"content": {"text/csv": {"schema": {"type": "string", "format": "binary"}}}}},
)
def export_replenishment(
    workspace_id: UUID,
    request: Request,
    db: DB,
    identity: FullIdentity,
    store_id: UUID | None = None,
    format: Literal["csv", "xlsx"] = "csv",
    destination_id: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
    urgent_only: bool = False,
    include_fbs: bool = False,
    target_days: Annotated[int, Query(ge=1, le=180)] = 30,
    lead_time_days: Annotated[int, Query(ge=0, le=90)] = 7,
):
    data = service.replenishment(
        db,
        request.app.state.vault,
        workspace_id,
        selected_stores(db, identity, workspace_id, store_id),
        urgent_only=urgent_only,
        destination_id=destination_id,
        include_fbs=include_fbs,
        target_days=target_days,
        lead_time_days=lead_time_days,
        limit=None,
    )
    if data.recommended_units is None:
        raise HTTPException(409, "Дождитесь расчёта потребности.")
    return Response(
        requirements_xlsx(data) if format == "xlsx" else requirements_csv(data),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        if format == "xlsx"
        else "text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="perk-supply-requirements.{format}"',
            "Cache-Control": "no-store",
        },
    )
