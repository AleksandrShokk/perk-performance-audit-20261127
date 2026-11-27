"""Request fresh marketplace data without duplicating active imports or losing history."""

from sqlalchemy import select

from app.modules.accounts.models import StoreCredential
from app.modules.auth.dependencies import now
from app.modules.sync import planner
from app.modules.sync.capabilities import sync_capabilities
from app.modules.sync.models import SyncSchedule


def request_refresh(db, store, actor, settings, vault):
    if store.marketplace == "ozon":
        refresh_ozon(db, store, actor)
        return
    planner.configure_initial(db, store, actor, settings, vault)
    plans = db.scalars(
        select(SyncSchedule)
        .where(
            SyncSchedule.workspace_id == store.workspace_id,
            SyncSchedule.store_id == store.id,
            SyncSchedule.enabled.is_(True),
        )
        .with_for_update()
    ).all()
    for plan in plans:
        plan.requested_by = actor
        plan.next_refresh_at = plan.next_attempt_at = now()
    credential = db.scalar(
        select(StoreCredential).where(
            StoreCredential.workspace_id == store.workspace_id,
            StoreCredential.store_id == store.id,
        )
    )
    caps = sync_capabilities(credential, vault, settings, store.workspace_id, store.id)
    db.flush()
    planner.enqueue_store(db, store, caps, vault)


def refresh_ozon(db, store, actor):
    from app.modules.catalog.marketplace_models import OzonCatalogSync
    from app.modules.catalog.ozon_jobs import configure as configure_catalog
    from app.modules.insights.marketplace_models import OzonAnalyticsSync
    from app.modules.insights.ozon_jobs import configure as configure_analytics

    scope = (store.workspace_id, store.id)
    catalog = db.get(OzonCatalogSync, scope, with_for_update=True)
    if catalog is None:
        configure_catalog(db, store, actor)
    else:
        refresh_job(catalog, actor)
    jobs = db.scalars(
        select(OzonAnalyticsSync)
        .where(
            OzonAnalyticsSync.workspace_id == store.workspace_id,
            OzonAnalyticsSync.store_id == store.id,
        )
        .with_for_update()
    ).all()
    if not jobs:
        configure_analytics(db, store, actor)
    for job in jobs:
        refresh_job(job, actor)


def refresh_job(job, actor):
    if job.status in {"pending", "queued", "running"}:
        return
    job.requested_by = actor
    job.status, job.run_id, job.error_code = "pending", None, None
    job.next_attempt_at = now()
