"""Ozon connection lifecycle and automatic read-only catalog import."""

from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.modules.accounts import ozon_connection
from app.modules.accounts.models import Store, StoreCredential
from app.modules.accounts.router import find_store, require_workspace
from app.modules.accounts.schemas import ConnectOzonInput, OzonCredentialInput, StoreResponse
from app.modules.audit.service import audit
from app.modules.auth.dependencies import DB, StrongIdentity, now
from app.modules.catalog.ozon_jobs import configure
from app.modules.insights.ozon_jobs import configure as configure_analytics

router = APIRouter(prefix="/workspaces", tags=["Stores"])


@router.post(
    "/{workspace_id}/stores/ozon",
    response_model=StoreResponse,
    status_code=201,
    operation_id="storeConnectOzon",
)
def connect_ozon(
    workspace_id: UUID, data: ConnectOzonInput, request: Request, db: DB, identity: StrongIdentity
):
    require_workspace(db, identity, workspace_id, owner=True)
    existing = db.scalar(
        select(Store.id).where(
            Store.workspace_id == workspace_id,
            Store.marketplace == "ozon",
            Store.external_seller_id == data.client_id,
        )
    )
    if existing:
        raise HTTPException(409, "Этот магазин уже подключён к кабинету.")
    api_key = data.api_key.get_secret_value()
    access = ozon_connection.verify(request, data.client_id, api_key)
    store = Store(
        id=uuid4(),
        workspace_id=workspace_id,
        name=data.name,
        marketplace="ozon",
        external_seller_id=data.client_id,
        connection_status="connected",
        last_checked_at=now(),
    )
    db.add(store)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Этот магазин уже подключён к кабинету.") from None
    db.add(
        StoreCredential(
            workspace_id=workspace_id,
            store_id=store.id,
            ciphertext=ozon_connection.seal(
                request.app.state.vault, store, data.client_id, api_key, access
            ),
            scopes="seller_api",
            expires_at=access.expires_at,
        )
    )
    audit(
        db,
        "store.connected",
        user_id=identity.user.id,
        workspace_id=workspace_id,
        target_id=store.id,
    )
    configure(db, store, identity.user.id)
    configure_analytics(db, store, identity.user.id)
    db.commit()
    return store


@router.put(
    "/{workspace_id}/stores/{store_id}/ozon-credential",
    response_model=StoreResponse,
    operation_id="storeReplaceOzonCredential",
)
def replace_ozon(
    workspace_id: UUID,
    store_id: UUID,
    data: OzonCredentialInput,
    request: Request,
    db: DB,
    identity: StrongIdentity,
):
    require_workspace(db, identity, workspace_id, owner=True)
    store = find_store(db, workspace_id, store_id)
    if store.marketplace != "ozon":
        raise HTTPException(400, "Выберите кабинет Ozon.")
    if store.external_seller_id != data.client_id:
        raise HTTPException(400, "Client ID относится к другому кабинету Ozon.")
    api_key = data.api_key.get_secret_value()
    access = ozon_connection.verify(request, data.client_id, api_key)
    db.refresh(store, with_for_update=True)
    if not store.is_active:
        raise HTTPException(409, "Магазин отключён. Подключите его заново.")
    row = ozon_connection.credential_row(db, store)
    row.ciphertext = ozon_connection.seal(
        request.app.state.vault, store, data.client_id, api_key, access
    )
    row.scopes, row.expires_at = "seller_api", access.expires_at
    store.connection_status, store.last_checked_at = "connected", now()
    audit(
        db,
        "store.credential_replaced",
        user_id=identity.user.id,
        workspace_id=workspace_id,
        target_id=store.id,
    )
    configure(db, store, identity.user.id)
    configure_analytics(db, store, identity.user.id)
    db.commit()
    return store
