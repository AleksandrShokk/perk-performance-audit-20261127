from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Request

from app.modules.auth.dependencies import DB, FullIdentity
from app.modules.supplies.destinations import service
from app.modules.supplies.destinations.schemas import (
    SupplyDestinations,
    SupplyDestinationsRefresh,
)
from app.modules.supplies.router import selected_stores

router = APIRouter(prefix="/workspaces/{workspace_id}/inventory", tags=["Supply destinations"])


@router.get(
    "/replenishment/destinations",
    response_model=SupplyDestinations,
    operation_id="inventoryDestinations",
)
def destinations(
    workspace_id: UUID,
    request: Request,
    db: DB,
    identity: FullIdentity,
    store_id: UUID | None = None,
    include_fbs: bool = False,
    target_days: Annotated[int, Query(ge=1, le=180)] = 30,
    lead_time_days: Annotated[int, Query(ge=0, le=90)] = 7,
):
    return service.overview(
        db,
        request.app.state.vault,
        workspace_id,
        selected_stores(db, identity, workspace_id, store_id),
        include_fbs=include_fbs,
        target_days=target_days,
        lead_time_days=lead_time_days,
    )


@router.post(
    "/replenishment/destinations/refresh",
    response_model=SupplyDestinationsRefresh,
    operation_id="inventoryDestinationsRefresh",
)
def refresh(
    workspace_id: UUID,
    request: Request,
    db: DB,
    identity: FullIdentity,
    store_id: UUID | None = None,
):
    queued = service.refresh(
        db,
        request.app.state.vault,
        workspace_id,
        selected_stores(db, identity, workspace_id, store_id),
    )
    db.commit()
    return SupplyDestinationsRefresh(queued=queued)
