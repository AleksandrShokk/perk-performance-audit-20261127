from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request

from app.core.response_cache import SEARCH_CACHE_SECONDS, respond, wb_fingerprint
from app.modules.accounts.access import allows
from app.modules.accounts.models import Workspace
from app.modules.accounts.reporting import reporting_stores
from app.modules.accounts.router import require_workspace
from app.modules.auth.dependencies import DB, FullIdentity
from app.modules.inventory.overview import INVENTORY_SOURCES, overview
from app.modules.inventory.overview_schemas import CoverageChannel, InventoryOverview

router = APIRouter(prefix="/workspaces/{workspace_id}", tags=["Inventory"])


@router.get(
    "/inventory/overview", response_model=InventoryOverview, operation_id="inventoryOverview"
)
def inventory_overview(
    workspace_id: UUID,
    request: Request,
    db: DB,
    identity: FullIdentity,
    store_id: UUID | None = None,
    coverage_channel: CoverageChannel = CoverageChannel.FBO,
    q: Annotated[str, Query(max_length=100)] = "",
    in_stock: bool = False,
    limit: Annotated[int, Query(ge=0, le=100)] = 0,
    offset: Annotated[int, Query(ge=0, le=50000)] = 0,
):
    member = require_workspace(db, identity, workspace_id)
    if not allows(member, "inventory.read"):
        raise HTTPException(403, "Нет доступа к остаткам.")
    stores = reporting_stores(db, workspace_id, store_id, feature="inventory")
    workspace = db.get(Workspace, workspace_id)
    can_cost, query = allows(member, "profit.read"), q.strip()

    def build():
        return overview(
            db,
            request.app.state.vault,
            workspace_id,
            stores,
            workspace.currency,
            can_cost,
            query,
            in_stock,
            limit,
            offset,
            coverage_channel,
            redis=request.app.state.redis,
        )

    # The full stock model decrypts and assembles every SKU (~1.3 s); every parameter
    # combination is cached until one of its inputs changes.
    return respond(
        request,
        "inventory-overview",
        wb_fingerprint(db, workspace_id, stores, INVENTORY_SOURCES),
        {
            "currency": workspace.currency,
            "can_cost": can_cost,
            "q": query,
            "in_stock": in_stock,
            "limit": limit,
            "offset": offset,
            "channel": str(coverage_channel),
        },
        build,
        SEARCH_CACHE_SECONDS if query else None,
    )
