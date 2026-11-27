from uuid import UUID, uuid4

from cryptography.exceptions import InvalidTag
from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.integrations.wildberries.client import inspect_token
from app.modules.accounts.access import FULL_ROLES, effective
from app.modules.accounts.models import Store, StoreCredential, Workspace
from app.modules.accounts.schemas import (
    AuditResponse,
    ConnectionResponse,
    ConnectStoreInput,
    PermissionCatalogue,
    RenameStoreInput,
    RotateCredentialInput,
    StoreResponse,
    SyncResponse,
    WorkspaceResponse,
)
from app.modules.audit.models import AuditEvent
from app.modules.audit.service import audit
from app.modules.auth.dependencies import DB, FullIdentity, StrongIdentity, now
from app.modules.auth.models import Membership
from app.modules.auth.schemas import MessageResponse
from app.modules.sync.models import SyncRun
from app.modules.sync.planner import configure_initial
from app.modules.sync.quota import credential_changed
from app.security.limits import rate_limit

router = APIRouter(prefix="/workspaces", tags=["Stores"])


def require_workspace(db, identity, workspace_id, owner=False):
    membership = db.scalar(
        select(Membership).where(
            Membership.user_id == identity.user.id, Membership.workspace_id == workspace_id
        )
    )
    if not membership or (owner and membership.role not in FULL_ROLES):
        raise HTTPException(404, "Кабинет не найден.")
    return membership


def find_store(db, workspace_id, store_id):
    store = db.scalar(select(Store).where(Store.id == store_id, Store.workspace_id == workspace_id))
    if not store:
        raise HTTPException(404, "Магазин не найден.")
    return store


@router.post(
    "/{workspace_id}/stores/{store_id}/refresh",
    response_model=MessageResponse,
    status_code=202,
    operation_id="storeRefreshData",
)
def refresh_data(
    workspace_id: UUID, store_id: UUID, request: Request, db: DB, identity: FullIdentity
):
    require_workspace(db, identity, workspace_id, owner=True)
    store = db.scalar(
        select(Store)
        .where(Store.workspace_id == workspace_id, Store.id == store_id)
        .with_for_update(key_share=True)
    )
    if not store:
        raise HTTPException(404, "Магазин не найден.")
    if not store.is_active or store.connection_status != "connected":
        raise HTTPException(409, "Проверьте подключение магазина.")
    rate_limit(
        request.app.state.redis, request.app.state.vault, "store-refresh", str(store_id), 2, 60
    )
    from app.modules.accounts.refresh import request_refresh

    request_refresh(
        db, store, identity.user.id, request.app.state.settings, request.app.state.vault
    )
    audit(
        db,
        "store.refresh_requested",
        user_id=identity.user.id,
        workspace_id=workspace_id,
        target_id=store_id,
    )
    db.commit()
    return MessageResponse(message="Обновление запущено.")


def verify_wb(request, token, workspace_id):
    settings = request.app.state.settings
    metadata = inspect_token(
        token,
        production=settings.app_env == "production",
        service_id=settings.wb_service_id,
        allow_personal=settings.allows_personal_wb_token(workspace_id),
    )
    rate_limit(request.app.state.redis, request.app.state.vault, "wb-token-check", token, 1, 60)
    return request.app.state.wb_client.verify(token, metadata)


@router.get("", response_model=list[WorkspaceResponse], operation_id="workspacesList")
def workspaces(db: DB, identity: FullIdentity):
    rows = db.execute(
        select(Workspace, Membership)
        .join(Membership, Membership.workspace_id == Workspace.id)
        .where(Membership.user_id == identity.user.id)
    ).all()
    return [
        WorkspaceResponse(
            id=workspace.id,
            name=workspace.name,
            role=member.role,
            permissions=effective(member),
            store_ids=member.store_ids,
        )
        for workspace, member in rows
    ]


@router.get("/{workspace_id}/stores", response_model=list[StoreResponse], operation_id="storesList")
def stores(workspace_id: UUID, db: DB, identity: FullIdentity):
    require_workspace(db, identity, workspace_id)
    return db.scalars(
        select(Store)
        .where(Store.workspace_id == workspace_id)
        .order_by(Store.created_at)
        .limit(100)
    ).all()


@router.patch(
    "/{workspace_id}/stores/{store_id}", response_model=StoreResponse, operation_id="storeRename"
)
def rename_store(
    workspace_id: UUID, store_id: UUID, data: RenameStoreInput, db: DB, identity: FullIdentity
):
    require_workspace(db, identity, workspace_id, owner=True)
    store = find_store(db, workspace_id, store_id)
    store.name = data.name
    audit(
        db, "store.renamed", user_id=identity.user.id, workspace_id=workspace_id, target_id=store_id
    )
    db.commit()
    return store


@router.post(
    "/{workspace_id}/stores/wildberries",
    response_model=StoreResponse,
    status_code=201,
    operation_id="storeConnectWildberries",
)
def connect(
    workspace_id: UUID, data: ConnectStoreInput, request: Request, db: DB, identity: StrongIdentity
):
    require_workspace(db, identity, workspace_id, owner=True)
    token = data.token.get_secret_value()
    metadata = verify_wb(request, token, workspace_id)
    existing = db.scalar(
        select(Store.id).where(
            Store.workspace_id == workspace_id,
            Store.marketplace == "wildberries",
            Store.external_seller_id == metadata.seller_id,
        )
    )
    if existing:
        raise HTTPException(409, "Этот магазин уже подключён к кабинету.")
    store = Store(
        id=uuid4(),
        workspace_id=workspace_id,
        name=data.name,
        marketplace="wildberries",
        external_seller_id=metadata.seller_id,
        connection_status="connected",
        last_checked_at=now(),
    )
    db.add(store)
    try:
        db.flush()
    except IntegrityError:
        # A concurrent request connected the same seller between the check and the insert.
        db.rollback()
        raise HTTPException(409, "Этот магазин уже подключён к кабинету.") from None
    db.add(
        StoreCredential(
            workspace_id=workspace_id,
            store_id=store.id,
            ciphertext=request.app.state.vault.seal(token, f"wb:{workspace_id}:{store.id}"),
            scopes=",".join(metadata.scopes),
            expires_at=metadata.expires_at,
        )
    )
    audit(
        db,
        "store.connected",
        user_id=identity.user.id,
        workspace_id=workspace_id,
        target_id=store.id,
    )
    configure_initial(
        db, store, identity.user.id, request.app.state.settings, request.app.state.vault
    )
    db.commit()
    return store


@router.get(
    "/{workspace_id}/stores/{store_id}/connection",
    response_model=ConnectionResponse,
    operation_id="storeConnectionStatus",
)
def connection(workspace_id: UUID, store_id: UUID, db: DB, identity: FullIdentity):
    require_workspace(db, identity, workspace_id)
    store = find_store(db, workspace_id, store_id)
    credential = db.scalar(
        select(StoreCredential).where(
            StoreCredential.store_id == store_id, StoreCredential.workspace_id == workspace_id
        )
    )
    return ConnectionResponse(
        client_id=store.external_seller_id if store.marketplace == "ozon" else None,
        status=(
            "expired" if credential and credential.expires_at <= now() else store.connection_status
        ),
        scopes=credential.scopes.split(",") if credential else [],
        expires_at=credential.expires_at if credential else None,
        checked_at=store.last_checked_at,
    )


@router.post(
    "/{workspace_id}/stores/{store_id}/check",
    response_model=ConnectionResponse,
    operation_id="storeCheckConnection",
)
def check_connection(
    workspace_id: UUID, store_id: UUID, request: Request, db: DB, identity: StrongIdentity
):
    require_workspace(db, identity, workspace_id, owner=True)
    store = find_store(db, workspace_id, store_id)
    credential = db.scalar(
        select(StoreCredential).where(
            StoreCredential.store_id == store_id, StoreCredential.workspace_id == workspace_id
        )
    )
    if not credential:
        raise HTTPException(400, "Магазин отключён. Подключите его заново.")
    if store.marketplace == "ozon":
        from app.modules.accounts.ozon_connection import check

        return check(request, db, identity, store)
    token = request.app.state.vault.open(credential.ciphertext, f"wb:{workspace_id}:{store_id}")
    try:
        metadata = verify_wb(request, token, workspace_id)
    except HTTPException as exc:
        if exc.status_code == 400:
            store.connection_status = "invalid_token"
            store.last_checked_at = now()
            audit(
                db,
                "store.check_failed",
                user_id=identity.user.id,
                workspace_id=workspace_id,
                target_id=store_id,
                success=False,
            )
            db.commit()
        raise
    store.connection_status = "connected"
    store.last_checked_at = now()
    audit(
        db, "store.checked", user_id=identity.user.id, workspace_id=workspace_id, target_id=store_id
    )
    db.commit()
    return ConnectionResponse(
        status="connected",
        scopes=metadata.scopes,
        expires_at=metadata.expires_at,
        checked_at=store.last_checked_at,
    )


@router.put(
    "/{workspace_id}/stores/{store_id}/credential",
    response_model=StoreResponse,
    operation_id="storeReplaceCredential",
)
def replace_credential(
    workspace_id: UUID,
    store_id: UUID,
    data: RotateCredentialInput,
    request: Request,
    db: DB,
    identity: StrongIdentity,
):
    require_workspace(db, identity, workspace_id, owner=True)
    store = find_store(db, workspace_id, store_id)
    token = data.token.get_secret_value()
    if store.marketplace != "wildberries":
        raise HTTPException(409, "Замена токена доступна только для Wildberries.")
    metadata = verify_wb(request, token, workspace_id)
    if metadata.seller_id != store.external_seller_id:
        raise HTTPException(400, "Токен относится к другому продавцу WB.")
    credential = db.scalar(
        select(StoreCredential)
        .where(StoreCredential.store_id == store_id, StoreCredential.workspace_id == workspace_id)
        .with_for_update()
    )
    if not credential:
        credential = StoreCredential(workspace_id=workspace_id, store_id=store_id)
        db.add(credential)
    previous = None
    if credential.ciphertext:
        try:
            previous = inspect_token(
                request.app.state.vault.open(credential.ciphertext, f"wb:{workspace_id}:{store_id}")
            )
        except HTTPException, InvalidTag, ValueError, KeyError:
            pass  # Expired previous tokens keep conservative legacy cooldowns.
    credential.ciphertext = request.app.state.vault.seal(token, f"wb:{workspace_id}:{store_id}")
    credential.scopes = ",".join(metadata.scopes)
    credential.expires_at = metadata.expires_at
    store.connection_status = "connected"
    store.last_checked_at = now()
    credential_changed(
        db,
        request.app.state.redis,
        request.app.state.vault,
        store,
        previous,
        metadata,
        actor_id=identity.user.id,
    )
    audit(
        db,
        "store.credential_replaced",
        user_id=identity.user.id,
        workspace_id=workspace_id,
        target_id=store_id,
    )
    db.commit()
    return store


@router.delete(
    "/{workspace_id}/stores/{store_id}/credential",
    response_model=MessageResponse,
    operation_id="storeDisconnect",
)
def disconnect(workspace_id: UUID, store_id: UUID, db: DB, identity: StrongIdentity):
    require_workspace(db, identity, workspace_id, owner=True)
    store = find_store(db, workspace_id, store_id)
    credential = db.scalar(
        select(StoreCredential)
        .where(StoreCredential.store_id == store_id, StoreCredential.workspace_id == workspace_id)
        .with_for_update()
    )
    if credential:
        db.delete(credential)
    store.connection_status = "disconnected"
    audit(
        db,
        "store.disconnected",
        user_id=identity.user.id,
        workspace_id=workspace_id,
        target_id=store_id,
    )
    db.commit()
    return MessageResponse(
        message="Токен удалён из PERK. Отзовите его также в кабинете Wildberries."
    )


@router.get(
    "/{workspace_id}/stores/{store_id}/sync-runs",
    response_model=list[SyncResponse],
    operation_id="storeSyncHistory",
)
def sync_history(workspace_id: UUID, store_id: UUID, db: DB, identity: FullIdentity):
    require_workspace(db, identity, workspace_id)
    find_store(db, workspace_id, store_id)
    return db.scalars(
        select(SyncRun)
        .where(SyncRun.workspace_id == workspace_id, SyncRun.store_id == store_id)
        .order_by(SyncRun.created_at.desc())
        .limit(100)
    ).all()


@router.get(
    "/{workspace_id}/audit",
    response_model=list[AuditResponse],
    operation_id="workspaceAuditHistory",
)
def audit_history(workspace_id: UUID, db: DB, identity: FullIdentity):
    require_workspace(db, identity, workspace_id, owner=True)
    return db.scalars(
        select(AuditEvent)
        .where(AuditEvent.workspace_id == workspace_id)
        .order_by(AuditEvent.created_at.desc())
        .limit(100)
    ).all()


@router.get("/permissions", response_model=PermissionCatalogue, operation_id="permissionCatalogue")
def permission_catalogue(identity: FullIdentity):
    from app.modules.accounts.access import PERMISSIONS, ROLE_DEFAULTS

    return PermissionCatalogue(permissions=PERMISSIONS, role_defaults=ROLE_DEFAULTS)
