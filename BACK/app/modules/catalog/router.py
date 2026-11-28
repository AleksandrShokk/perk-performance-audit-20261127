from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import select

from app.core.response_cache import SEARCH_CACHE_SECONDS, respond, wb_fingerprint
from app.integrations.wildberries.data import Source
from app.modules.accounts.access import allows
from app.modules.accounts.models import Store, Workspace
from app.modules.accounts.reporting import reporting_stores, require_reporting_store
from app.modules.accounts.router import require_workspace
from app.modules.audit.service import audit
from app.modules.auth.dependencies import DB, FullIdentity
from app.modules.catalog.model_service import assign, model_page
from app.modules.catalog.schemas import GroupingInput, ProductModelsPage, ProductPage
from app.modules.catalog.service import products

router = APIRouter(prefix="/workspaces/{workspace_id}", tags=["Catalog"])


@router.get("/products", response_model=ProductPage, operation_id="catalogProducts")
def list_products(
    workspace_id: UUID,
    request: Request,
    db: DB,
    identity: FullIdentity,
    store_id: UUID | None = None,
    q: Annotated[str, Query(max_length=100)] = "",
    in_stock: bool = False,
    missing_cost: bool = False,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
    offset: Annotated[int, Query(ge=0, le=50000)] = 0,
):
    member = require_workspace(db, identity, workspace_id)
    can_stock, can_cost = (
        allows(member, "inventory.read"),
        allows(member, "profit.read"),
    )
    if (
        not (can_stock or can_cost)
        or (in_stock and not can_stock)
        or (missing_cost and not can_cost)
    ):
        raise HTTPException(403, "Нет доступа к этому разделу.")
    visible = reporting_stores(db, workspace_id, store_id, feature="catalog")
    workspace = db.get(Workspace, workspace_id)
    query = q.strip()

    def build():
        return products(
            db,
            request.app.state.vault,
            workspace_id,
            visible,
            workspace.currency,
            query,
            in_stock,
            missing_cost,
            can_stock,
            can_cost,
            limit,
            offset,
            redis=request.app.state.redis,
        )

    return respond(
        request,
        "catalog-products",
        wb_fingerprint(db, workspace_id, visible, [Source.CATALOG, Source.STOCKS]),
        {
            "currency": workspace.currency,
            "q": query,
            "in_stock": in_stock,
            "missing_cost": missing_cost,
            "can_stock": can_stock,
            "can_cost": can_cost,
            "limit": limit,
            "offset": offset,
        },
        build,
        SEARCH_CACHE_SECONDS if query else None,
    )


@router.get("/product-models", response_model=ProductModelsPage, operation_id="catalogModels")
def list_models(
    workspace_id: UUID,
    request: Request,
    db: DB,
    identity: FullIdentity,
    store_id: UUID | None = None,
    q: Annotated[str, Query(max_length=100)] = "",
    in_stock: bool = False,
    missing_cost: bool = False,
    combine_marketplaces: bool = False,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
    offset: Annotated[int, Query(ge=0, le=50000)] = 0,
):
    member = require_workspace(db, identity, workspace_id)
    can_stock, can_cost = (
        allows(member, "inventory.read"),
        allows(member, "profit.read"),
    )
    if (
        not (can_stock or can_cost)
        or (in_stock and not can_stock)
        or (missing_cost and not can_cost)
    ):
        raise HTTPException(403, "Нет доступа к этому разделу.")
    stores = reporting_stores(db, workspace_id, store_id, feature="catalog")
    workspace = db.get(Workspace, workspace_id)
    return model_page(
        db,
        request.app.state.vault,
        workspace_id,
        stores,
        workspace.currency,
        q.strip(),
        in_stock,
        missing_cost,
        can_stock,
        can_cost,
        limit,
        offset,
        combine_marketplaces=combine_marketplaces and store_id is None,
    )


@router.post(
    "/stores/{store_id}/product-grouping",
    response_model=dict[str, str],
    operation_id="catalogGroupSave",
)
def save_group(
    workspace_id: UUID,
    store_id: UUID,
    data: GroupingInput,
    request: Request,
    db: DB,
    identity: FullIdentity,
):
    require_workspace(db, identity, workspace_id, owner=True)
    store = db.scalar(
        select(Store)
        .where(
            Store.id == store_id,
            Store.workspace_id == workspace_id,
            Store.is_active.is_(True),
        )
        .with_for_update()
    )
    if not store:
        raise HTTPException(404, "Магазин не найден.")
    require_reporting_store(store, "catalog")
    key = assign(db, request.app.state.vault, workspace_id, store_id, identity.user.id, data)
    audit(
        db,
        "catalog.group.changed",
        user_id=identity.user.id,
        workspace_id=workspace_id,
        target_id=store_id,
    )
    db.commit()
    return {"id": key}


class CatalogSyncStatus(BaseModel):
    status: str
    records_processed: int
    updated_at: datetime | None
    error_code: str | None


@router.get(
    "/stores/{store_id}/catalog-sync",
    response_model=CatalogSyncStatus,
    operation_id="catalogSyncStatus",
)
def catalog_sync_status(
    workspace_id: UUID, store_id: UUID, request: Request, db: DB, identity: FullIdentity
):
    member = require_workspace(db, identity, workspace_id)
    if not (allows(member, "inventory.read") or allows(member, "profit.read")):
        raise HTTPException(403, "Нет доступа к товарам.")
    store = reporting_stores(db, workspace_id, store_id, feature="catalog")[0]
    if store.marketplace != "ozon":
        raise HTTPException(400, "Выберите магазин Ozon.")
    from app.modules.catalog.ozon_read import state

    return state(db, workspace_id, store_id)


@router.post(
    "/stores/{store_id}/catalog-refresh",
    response_model=CatalogSyncStatus,
    operation_id="catalogSyncRefresh",
)
def catalog_sync_refresh(
    workspace_id: UUID, store_id: UUID, request: Request, db: DB, identity: FullIdentity
):
    require_workspace(db, identity, workspace_id, owner=True)
    store = reporting_stores(db, workspace_id, store_id, feature="catalog")[0]
    if store.marketplace != "ozon" or store.connection_status != "connected":
        raise HTTPException(400, "Проверьте подключение Ozon.")
    from app.modules.catalog.ozon_jobs import configure
    from app.modules.catalog.ozon_read import state
    from app.security.limits import rate_limit

    rate_limit(
        request.app.state.redis,
        request.app.state.vault,
        "ozon-catalog-refresh",
        str(store_id),
        3,
        60,
    )
    configure(db, store, identity.user.id)
    db.commit()
    return state(db, workspace_id, store_id)
