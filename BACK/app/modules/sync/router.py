import json
from datetime import date, datetime, timedelta
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import func, select

from app.integrations.wildberries.data import Source
from app.modules.accounts.access import allows
from app.modules.accounts.models import Store, StoreCredential
from app.modules.accounts.reporting import require_reporting_store
from app.modules.accounts.router import find_store, require_workspace
from app.modules.audit.service import audit
from app.modules.auth.dependencies import DB, FullIdentity, now
from app.modules.sync import analytics, planner
from app.modules.sync.capabilities import sync_capabilities
from app.modules.sync.models import SyncRun, SyncSchedule, WBRecord, WBStagedRecord
from app.modules.sync.schemas import (
    ConfigureSchedule,
    DataPage,
    RunStatus,
    SalesBasis,
    ScheduleStatus,
    StartSync,
    StoreAnalytics,
    SyncCapabilities,
    moscow_today,
)
from app.modules.sync.service import context
from app.security.limits import rate_limit

router = APIRouter(prefix="/workspaces/{workspace_id}/stores/{store_id}", tags=["Synchronization"])


@router.get("/sync-schedule", response_model=list[ScheduleStatus], operation_id="storeSyncSchedule")
def sync_schedule(workspace_id: UUID, store_id: UUID, db: DB, identity: FullIdentity):
    require_workspace(db, identity, workspace_id)
    require_reporting_store(find_store(db, workspace_id, store_id))
    return db.scalars(
        select(SyncSchedule)
        .where(
            SyncSchedule.workspace_id == workspace_id,
            SyncSchedule.store_id == store_id,
        )
        .order_by(SyncSchedule.source)
    ).all()


@router.put(
    "/sync-schedule", response_model=list[ScheduleStatus], operation_id="storeConfigureSync"
)
def configure_sync(
    workspace_id: UUID,
    store_id: UUID,
    data: ConfigureSchedule,
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
        )
        .with_for_update(key_share=True)
    )
    if not store:
        raise HTTPException(404, "Магазин не найден.")
    if (
        store.marketplace != "wildberries"
        or not store.is_active
        or store.connection_status != "connected"
    ):
        raise HTTPException(409, "Сначала подключите действующий магазин Wildberries.")
    credential = db.scalar(
        select(StoreCredential).where(
            StoreCredential.workspace_id == workspace_id,
            StoreCredential.store_id == store_id,
        )
    )
    rate_limit(request.app.state.redis, request.app.state.vault, "wb-plan", str(store_id), 3, 60)
    caps = sync_capabilities(
        credential, request.app.state.vault, request.app.state.settings, workspace_id, store_id
    )
    plans = planner.configure(db, store, identity.user.id, data, caps, request.app.state.vault)
    audit(
        db,
        "sync.schedule.changed",
        user_id=identity.user.id,
        workspace_id=workspace_id,
        target_id=store_id,
    )
    db.commit()
    return plans


@router.get("/analytics", response_model=StoreAnalytics, operation_id="storeAnalytics")
def store_analytics(
    workspace_id: UUID,
    store_id: UUID,
    request: Request,
    db: DB,
    identity: FullIdentity,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    sales_basis: SalesBasis = "auto",
):
    require_workspace(db, identity, workspace_id)
    require_reporting_store(find_store(db, workspace_id, store_id))
    start, end = date_from or moscow_today() - timedelta(days=29), date_to or moscow_today()
    if start > end or end > moscow_today():
        raise HTTPException(
            422, "Дата начала должна быть не позже даты окончания. Будущие даты недоступны."
        )
    result, version = analytics.cached_metrics(
        db,
        request.app.state.redis,
        request.app.state.vault,
        workspace_id,
        store_id,
        start,
        end,
        limit,
        sales_basis,
    )
    windows = analytics.coverage(db, workspace_id, store_id)
    complete = {
        source: result.get("snapshot_stable", True)
        and source not in result["partial_sources"]
        and any(
            date.fromisoformat(window["date_from"]) <= start
            and date.fromisoformat(window["date_to"]) >= end
            for window in periods
        )
        for source, periods in windows.items()
    }
    available = {}
    for source in (Source.SALES, Source.FINANCE):
        available[source] = bool(
            db.scalar(
                select(SyncRun.id)
                .where(
                    SyncRun.workspace_id == workspace_id,
                    SyncRun.store_id == store_id,
                    SyncRun.source == source,
                    (SyncRun.status == "succeeded")
                    | (SyncRun.status.in_(["queued", "running"]) & (SyncRun.records_processed > 0)),
                )
                .limit(1)
            )
        )
    sales_source = Source.FINANCE if result["sales_basis"] == "reports" else Source.SALES
    complete["operational_sales"] = complete[Source.SALES]
    available["operational_sales"] = available[Source.SALES]
    complete[Source.SALES] = complete[sales_source] and result["sales_metrics_ready"]
    available[Source.SALES] = available[sales_source] and result["sales_metrics_ready"]
    return {
        **result,
        "date_from": start,
        "date_to": end,
        "coverage": windows,
        "sales_coverage": windows[sales_source],
        "period_complete": complete,
        "available": available,
        "revision": str(version.version) if version else None,
        "updated_at": version.updated_at if version else None,
    }


@router.post(
    "/sync", response_model=list[RunStatus], status_code=202, operation_id="storeStartSync"
)
def start_sync(
    workspace_id: UUID,
    store_id: UUID,
    data: StartSync,
    request: Request,
    db: DB,
    identity: FullIdentity,
):
    require_workspace(db, identity, workspace_id, owner=True)
    # A store lock serializes competing requests; the DB unique index is the second defence.
    store = db.scalar(
        select(Store)
        .where(Store.id == store_id, Store.workspace_id == workspace_id)
        .with_for_update(key_share=True)
    )
    if not store:
        raise HTTPException(404, "Магазин не найден.")
    if (
        store.marketplace != "wildberries"
        or not store.is_active
        or store.connection_status != "connected"
    ):
        raise HTTPException(409, "Сначала подключите действующий магазин Wildberries.")
    credential = db.scalar(
        select(StoreCredential).where(
            StoreCredential.store_id == store_id, StoreCredential.workspace_id == workspace_id
        )
    )
    if not credential or credential.expires_at <= now():
        raise HTTPException(409, "Токен магазина отсутствует или истёк. Обновите подключение.")
    capabilities = sync_capabilities(
        credential, request.app.state.vault, request.app.state.settings, workspace_id, store_id
    )
    sources = data.effective_sources()
    active = db.scalars(
        select(SyncRun).where(
            SyncRun.workspace_id == workspace_id,
            SyncRun.store_id == store_id,
            SyncRun.source.in_(sources),
            SyncRun.status.in_(["queued", "running"]),
        )
    ).all()
    if active:
        raise HTTPException(
            409, {"code": "sync_already_active", "run_ids": [str(r.id) for r in active]}
        )
    rate_limit(
        request.app.state.redis, request.app.state.vault, "wb-sync-start", str(store_id), 2, 60
    )
    runs = []
    for source in sources:
        start, end = data.period_for(source)
        error = capabilities["sources"][source]["error_code"]
        if start and start > end:
            error = "wb_history_unavailable"
            start = data.date_from
        runs.append(
            SyncRun(
                id=uuid4(),
                workspace_id=workspace_id,
                store_id=store_id,
                source=source,
                requested_by=identity.user.id,
                date_from=start,
                date_to=end,
                status="failed" if error else "queued",
                error_code=error,
                finished_at=now() if error else None,
            )
        )
    db.add_all(runs)
    audit(
        db,
        "sync.requested",
        user_id=identity.user.id,
        workspace_id=workspace_id,
        target_id=store_id,
    )
    # Durable outbox: beat picks up committed runs, including after a Redis outage/restart.
    db.commit()
    return runs


@router.get(
    "/sync-capabilities", response_model=SyncCapabilities, operation_id="storeSyncCapabilities"
)
def capabilities(
    workspace_id: UUID, store_id: UUID, request: Request, db: DB, identity: FullIdentity
):
    require_workspace(db, identity, workspace_id)
    require_reporting_store(find_store(db, workspace_id, store_id))
    credential = db.scalar(
        select(StoreCredential).where(
            StoreCredential.store_id == store_id, StoreCredential.workspace_id == workspace_id
        )
    )
    return sync_capabilities(
        credential, request.app.state.vault, request.app.state.settings, workspace_id, store_id
    )


@router.get("/sync-runs/{run_id}", response_model=RunStatus, operation_id="storeSyncStatus")
def sync_status(workspace_id: UUID, store_id: UUID, run_id: UUID, db: DB, identity: FullIdentity):
    require_workspace(db, identity, workspace_id)
    require_reporting_store(find_store(db, workspace_id, store_id))
    run = db.scalar(
        select(SyncRun).where(
            SyncRun.id == run_id, SyncRun.workspace_id == workspace_id, SyncRun.store_id == store_id
        )
    )
    if not run:
        raise HTTPException(404, "Загрузка данных не найдена.")
    return run


@router.get("/data/{source}", response_model=DataPage, operation_id="storeImportedData")
def imported_data(
    workspace_id: UUID,
    store_id: UUID,
    source: Source,
    request: Request,
    db: DB,
    identity: FullIdentity,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0, le=250000)] = 0,
):
    member = require_workspace(db, identity, workspace_id)
    require_reporting_store(find_store(db, workspace_id, store_id))
    if source in {
        Source.STOCK_HISTORY,
        Source.SUPPLY_DEMAND,
        Source.SUPPLY_DEMAND_FBS,
        Source.SUPPLIES,
    } and not allows(member, "inventory.read"):
        raise HTTPException(403, "Нет доступа к остаткам.")
    # Count and rows use one SQL snapshot; reads need not wait on the import's store lock.
    scope = (
        WBRecord.workspace_id == workspace_id,
        WBRecord.store_id == store_id,
        WBRecord.source == source,
    )
    history = (
        select(SyncRun)
        .where(
            SyncRun.workspace_id == workspace_id,
            SyncRun.store_id == store_id,
            SyncRun.source == source,
        )
        .order_by(SyncRun.created_at.desc())
    )
    last_successful = db.scalar(history.where(SyncRun.status == "succeeded").limit(1))
    latest = db.scalar(history.limit(1))
    partial = bool(not last_successful and latest and latest.status in {"queued", "running"})
    model = WBRecord
    if partial:
        model = WBStagedRecord
        scope = (
            model.workspace_id == workspace_id,
            model.store_id == store_id,
            model.run_id == latest.id,
        )
    # Count and page share the same SQL snapshot, including during a staged preview.
    total_query = (
        select(func.count()).select_from(model).where(*scope).correlate(None).scalar_subquery()
    )
    result = db.execute(
        select(model, total_query)
        .where(*scope)
        .order_by(model.record_key)
        .limit(limit)
        .offset(offset)
    ).all()
    total = (
        result[0][1] if result else db.scalar(select(func.count()).select_from(model).where(*scope))
    )
    rows = [r[0] for r in result]
    return DataPage(
        source=source,
        total=total,
        last_successful_run=last_successful,
        latest_run=latest,
        is_partial=partial,
        updated_at=(
            latest.started_at
            if partial
            else last_successful.finished_at
            if last_successful
            else None
        ),
        limit=limit,
        offset=offset,
        items=[
            json.loads(
                request.app.state.vault.open(
                    row.ciphertext, context(workspace_id, store_id, source, row.record_key)
                )
            )
            for row in rows
        ],
    )


class ImportIssueView(BaseModel):
    source: str
    record_id: str
    reason: str
    created_at: datetime


@router.get(
    "/import-issues", response_model=list[ImportIssueView], operation_id="storeImportIssues"
)
def import_issues(
    workspace_id: UUID, store_id: UUID, request: Request, db: DB, identity: FullIdentity
):
    from app.modules.sync.issues import ImportIssue

    require_workspace(db, identity, workspace_id, owner=True)
    find_store(db, workspace_id, store_id)
    rows = db.scalars(
        select(ImportIssue)
        .where(ImportIssue.workspace_id == workspace_id, ImportIssue.store_id == store_id)
        .order_by(ImportIssue.created_at.desc())
        .limit(100)
    ).all()
    vault = request.app.state.vault
    return [
        ImportIssueView(
            source=row.source,
            reason=row.reason,
            created_at=row.created_at,
            record_id=vault.open(
                row.ciphertext,
                f"import-issue:{workspace_id}:{store_id}:{row.source}:{row.record_key}",
            ),
        )
        for row in rows
    ]
