import logging
from datetime import timedelta
from uuid import UUID, uuid4

from app.core.config import get_settings
from app.db.session import set_actor
from app.integrations.wildberries.data import DATED, Source, WBError
from app.modules.accounts.access import allows
from app.modules.accounts.models import Store
from app.modules.accounts.reporting import REPORTING_MARKETPLACES
from app.modules.auth.dependencies import now
from app.modules.auth.models import Membership, User
from app.modules.finance import jobs as finance_jobs
from app.modules.finance.projection import prepare as prepare_finance_projection
from app.modules.insights import compute as insight_compute
from app.modules.insights import snapshots as insight_snapshots
from app.modules.inventory.projection import build_snapshot as build_inventory_snapshot
from app.modules.sync import funnel_summary
from app.modules.sync.analytics import ensure_preview, rebuild_store, warm_store
from app.modules.sync.models import SyncRun, SyncSchedule
from app.modules.sync.planner import schedule_due
from app.modules.sync.service import defer_error, run_page
from app.security.crypto import SecretVault
from app.workers.celery_app import HEAVY_QUEUE, celery_app
from app.workers.database import release_engine
from app.workers.database import worker_engine as build_engine
from app.workers.outbox import actors
from redis import Redis
from sqlalchemy import case, select
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


@celery_app.task(name="perk.sync.schedule", ignore_result=True, soft_time_limit=50, time_limit=60)
def plan_sync():
    settings = get_settings()
    engine = build_engine(settings)
    try:
        schedule_due(engine, SecretVault(settings.security_file), settings)
    except Exception:
        logger.error("sync_planner_unavailable")
    finally:
        release_engine(engine)


@celery_app.task(
    name="perk.analytics.warm", ignore_result=True, soft_time_limit=110, time_limit=120
)
def warm_analytics():
    settings = get_settings()
    engine = build_engine(settings)
    redis = Redis.from_url(
        settings.redis_broker_url, socket_connect_timeout=3, socket_timeout=3, decode_responses=True
    )
    try:
        vault = SecretVault(settings.security_file)
        with Session(engine) as db:
            from sqlalchemy import text

            if db.scalar(
                text("SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname=current_user")
            ):
                raise RuntimeError("unsafe_worker_database_role")
            from sqlalchemy import text

            actors = db.scalars(text("SELECT perk_queue_actors('warm')")).all()
        for actor in actors:
            finance_stores = []
            with Session(engine) as db, db.begin():
                set_actor(db, actor)
                stores = db.scalars(
                    select(Store)
                    .join(Membership, Membership.workspace_id == Store.workspace_id)
                    .join(User, User.id == Membership.user_id)
                    .where(
                        Membership.user_id == actor,
                        Membership.role.in_(["owner", "admin"]),
                        User.is_active.is_(True),
                        User.email_verified_at.is_not(None),
                        Store.marketplace.in_(REPORTING_MARKETPLACES),
                        Store.is_active.is_(True),
                        Store.connection_status == "connected",
                    )
                    .with_for_update(of=Store, skip_locked=True, key_share=True)
                ).all()
                for store in stores:
                    rebuild_store(db, vault, store.workspace_id, store.id)
                    for run in db.scalars(
                        select(SyncRun).where(
                            SyncRun.workspace_id == store.workspace_id,
                            SyncRun.store_id == store.id,
                            SyncRun.source.in_(list(DATED)),
                            SyncRun.status.in_(["queued", "running"]),
                        )
                    ):
                        ensure_preview(db, vault, run)
                    warm_store(db, redis, vault, store.workspace_id, store.id)
                    finance_stores.append((store.workspace_id, store.id))
            for workspace_id, store_id in finance_stores:
                finance_jobs.enqueue(redis, vault, workspace_id, store_id, actor)
    except Exception:
        logger.error("analytics_warm_unavailable")
    finally:
        redis.close()
        release_engine(engine)


@celery_app.task(name="perk.health.ping")
def ping() -> dict[str, str]:
    """Diagnostic task only; does not fetch or fabricate marketplace data."""
    return {"status": "ok", "service": "perk-worker"}


@celery_app.task(
    name="perk.analytics.warm_store", ignore_result=True, soft_time_limit=50, time_limit=60
)
def warm_store_analytics(workspace_id: str, store_id: str, actor_id: str):
    """Prepare popular charts after commit; all queue arguments are identifiers."""
    settings = get_settings()
    engine = build_engine(settings)
    redis = Redis.from_url(
        settings.redis_broker_url, socket_connect_timeout=3, socket_timeout=3, decode_responses=True
    )
    try:
        prepared = False
        with Session(engine) as db, db.begin():
            from sqlalchemy import text

            if db.scalar(
                text("SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname=current_user")
            ):
                raise RuntimeError("unsafe_worker_database_role")
            set_actor(db, UUID(actor_id))
            store = db.scalar(
                select(Store)
                .join(Membership, Membership.workspace_id == Store.workspace_id)
                .join(User, User.id == Membership.user_id)
                .where(
                    Store.workspace_id == UUID(workspace_id),
                    Store.id == UUID(store_id),
                    Membership.user_id == UUID(actor_id),
                    Membership.role.in_(["owner", "admin"]),
                    User.is_active.is_(True),
                    User.email_verified_at.is_not(None),
                    Store.marketplace.in_(REPORTING_MARKETPLACES),
                    Store.is_active.is_(True),
                    Store.connection_status == "connected",
                )
                .with_for_update(of=Store, skip_locked=True, key_share=True)
            )
            if store:
                vault = SecretVault(settings.security_file)
                warm_store(db, redis, vault, store.workspace_id, store.id)
                try:
                    with db.begin_nested():
                        build_inventory_snapshot(db, vault, store.workspace_id, store.id)
                except Exception:
                    logger.error("inventory_snapshot_unavailable")
                prepared = True
        if prepared:
            vault = SecretVault(settings.security_file)
            finance_jobs.enqueue(redis, vault, workspace_id, store_id, actor_id)
            warm_insights(redis, vault, workspace_id, store_id, actor_id)
    except Exception:
        logger.error("analytics_warm_store_unavailable")
    finally:
        redis.close()
        release_engine(engine)


@celery_app.task(
    name="perk.finance.prepare", ignore_result=True, soft_time_limit=600, time_limit=660
)
def prepare_finance(workspace_id: str, store_id: str, actor_id: str, lease_token: str):
    settings = get_settings()
    engine = build_engine(settings)
    redis = Redis.from_url(
        settings.redis_broker_url, socket_connect_timeout=3, socket_timeout=3, decode_responses=True
    )
    vault = SecretVault(settings.security_file)
    changed = False
    try:
        with Session(engine) as db, db.begin():
            from sqlalchemy import text

            if db.scalar(
                text("SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname=current_user")
            ):
                raise RuntimeError("unsafe_worker_database_role")
            set_actor(db, UUID(actor_id))
            store = db.scalar(
                select(Store)
                .join(Membership, Membership.workspace_id == Store.workspace_id)
                .join(User, User.id == Membership.user_id)
                .where(
                    Store.workspace_id == UUID(workspace_id),
                    Store.id == UUID(store_id),
                    Membership.user_id == UUID(actor_id),
                    Membership.role.in_(["owner", "admin"]),
                    User.is_active.is_(True),
                    User.email_verified_at.is_not(None),
                    Store.marketplace.in_(REPORTING_MARKETPLACES),
                    Store.is_active.is_(True),
                    Store.connection_status == "connected",
                )
                .with_for_update(of=Store, skip_locked=True, key_share=True)
            )
            if store:
                changed = prepare_finance_projection(db, vault, store.workspace_id, store.id)
                from app.modules.finance.history import enqueue as upgrade_finance_history

                try:
                    with db.begin_nested():
                        upgrade_finance_history(db, store.workspace_id, store.id, UUID(actor_id))
                except Exception:
                    logger.error("finance_history_upgrade_unavailable")
        if changed:
            # New published finance facts: refresh what users open first.
            warm_insights(redis, vault, workspace_id, store_id, actor_id)
    except Exception:
        logger.error("finance_prepare_unavailable")
    finally:
        try:
            redis.eval(
                finance_jobs.RELEASE,
                1,
                finance_jobs.job_key(vault, workspace_id, store_id),
                lease_token,
            )
        except Exception:
            logger.error("finance_prepare_lease_unavailable")
        redis.close()
        release_engine(engine)


@celery_app.task(name="perk.sync.dispatch", ignore_result=True)
def dispatch_sync():
    """PostgreSQL is the outbox; a lost message is picked up again in three minutes."""
    engine = build_engine(get_settings())
    try:
        with Session(engine) as db, db.begin():
            messages = []
            for actor in actors(db, "sync"):
                runs = db.scalars(
                    select(SyncRun)
                    .where(
                        SyncRun.source.in_([*Source, funnel_summary.SOURCE]),
                        SyncRun.requested_by.is_not(None),
                        SyncRun.status.in_(["queued", "running"]),
                        SyncRun.requested_by == actor,
                        SyncRun.next_attempt_at <= now(),
                    )
                    .order_by(
                        case(
                            (SyncRun.source == funnel_summary.SOURCE, 0),
                            (SyncRun.source == Source.FUNNEL, 1),
                            (SyncRun.sync_mode == "backfill", 3),
                            else_=2,
                        ),
                        SyncRun.next_attempt_at,
                        SyncRun.created_at,
                    )
                    .limit(20)
                    .with_for_update(skip_locked=True)
                ).all()
                for run in runs:
                    run.task_id = str(uuid4())
                    # Finance publication uses the projection time budget.
                    run.next_attempt_at = now() + timedelta(
                        minutes=12 if run.source == Source.FINANCE else 3
                    )
                    messages.append((str(run.id), run.task_id, run.source))
        for run_id, task_id, source in messages:
            options = (
                {"queue": HEAVY_QUEUE, "soft_time_limit": 600, "time_limit": 660}
                if source == Source.FINANCE
                else {}
            )
            sync_page.apply_async(args=[run_id], task_id=task_id, retry=False, **options)
    except Exception:
        # SQL/HTTP/broker exception messages can contain credentials or seller data.
        logger.error("sync_dispatch_unavailable")
    finally:
        release_engine(engine)


@celery_app.task(
    bind=True, name="perk.sync.page", ignore_result=True, soft_time_limit=110, time_limit=120
)
def sync_page(self, run_id: str):
    settings = get_settings()
    engine = build_engine(settings)
    redis = None
    try:
        run_uuid = UUID(run_id)
        redis = Redis.from_url(
            settings.redis_broker_url,
            socket_connect_timeout=3,
            socket_timeout=3,
            decode_responses=True,
        )
        published = run_page(
            engine, redis, SecretVault(settings.security_file), settings, run_uuid, self.request.id
        )
        if published:
            with Session(engine) as db:
                set_actor(db, UUID(published[2]))
                source = db.scalar(select(SyncRun.source).where(SyncRun.id == run_uuid))
            if source == Source.CATALOG:
                from app.modules.catalog.tasks import queue_schemas

                queue_schemas.apply_async(args=list(published), retry=False)
            # Queue only after the publication transaction has committed successfully.
            warm_store_analytics.apply_async(args=list(published), retry=False)
    except Exception:
        logger.error("sync_page_failed")
        try:
            with Session(engine) as db, db.begin():
                from app.workers.outbox import bind_sync

                bind_sync(db, UUID(run_id), self.request.id)
                run = db.scalar(
                    select(SyncRun)
                    .where(
                        SyncRun.id == UUID(run_id),
                        SyncRun.task_id == self.request.id,
                        SyncRun.status.in_(["queued", "running"]),
                    )
                    .with_for_update(skip_locked=True)
                )
                if run:
                    set_actor(db, run.requested_by)
                    defer_error(db, run, WBError("sync_internal_error", retryable=True))
        except Exception:
            logger.error("sync_state_update_unavailable")
    finally:
        if redis:
            redis.close()
        release_engine(engine)


def warm_insights(redis, vault, workspace_id, store_id, actor_id):
    """Queue refreshes of the screens users open first; each one is deduplicated."""
    for kind, params in [*insight_compute.warm_defaults(), ("reports", {})]:
        insight_snapshots.schedule(redis, vault, workspace_id, store_id, actor_id, kind, params)


def member_store(db, workspace_id, store_id, actor_id):
    """Store readable by an active, verified member; RLS applies on top."""
    return db.scalar(
        select(Store)
        .join(Membership, Membership.workspace_id == Store.workspace_id)
        .join(User, User.id == Membership.user_id)
        .where(
            Store.workspace_id == workspace_id,
            Store.id == store_id,
            Membership.user_id == actor_id,
            User.is_active.is_(True),
            User.email_verified_at.is_not(None),
            Store.marketplace.in_(REPORTING_MARKETPLACES),
            Store.is_active.is_(True),
        )
    )


@celery_app.task(name="perk.funnel.request_summary", ignore_result=True)
def request_funnel_summary(
    workspace_id: str,
    store_id: str,
    actor_id: str,
    start: str,
    end: str,
    include_previous_days: bool = False,
):
    """A readable home report may request a read-only refresh under its configured owner.

    Recheck the requesting member and the current owner when the job executes; a
    queued request cannot retain access after membership or store access is revoked.
    """
    from datetime import date

    settings = get_settings()
    engine = build_engine(settings)
    try:
        with Session(engine) as db, db.begin():
            workspace, store_uuid, actor = UUID(workspace_id), UUID(store_id), UUID(actor_id)
            set_actor(db, actor)
            if member_store(db, workspace, store_uuid, actor) is None:
                return
            member = db.get(Membership, (actor, workspace))
            if member is None or not allows(member, "analytics.read"):
                return
            plan = db.get(SyncSchedule, (workspace, store_uuid, Source.FUNNEL))
            if plan is None or not plan.enabled:
                return
            # Read the configured actor from the scoped schedule. Employees cannot list colleagues.
            set_actor(db, plan.requested_by)
            owner = db.scalar(
                select(User.id)
                .join(Membership, Membership.user_id == User.id)
                .where(
                    Membership.workspace_id == workspace,
                    User.id == plan.requested_by,
                    Membership.role.in_(["owner", "admin"]),
                    User.is_active.is_(True),
                    User.email_verified_at.is_not(None),
                )
                .limit(1)
            )
            if owner is None:
                return
            if include_previous_days:
                from app.modules.sync.analytics import coverage

                first, _ = funnel_summary.previous(
                    date.fromisoformat(start), date.fromisoformat(end)
                )
                if plan.history_from is None:
                    windows = coverage(db, workspace, store_uuid)[Source.FUNNEL]
                    plan.backfill_to = min(
                        (date.fromisoformat(window["date_from"]) for window in windows),
                        default=date.fromisoformat(start),
                    ) - timedelta(days=1)
                plan.history_from = min(plan.history_from or first, first)
                plan.next_attempt_at = now()
            funnel_summary.enqueue(
                db,
                SecretVault(settings.security_file),
                workspace,
                store_uuid,
                owner,
                date.fromisoformat(start),
                date.fromisoformat(end),
            )
    except Exception:
        logger.error("funnel_summary_request_failed")
    finally:
        release_engine(engine)


@celery_app.task(
    name="perk.insights.compute", ignore_result=True, soft_time_limit=280, time_limit=300
)
def compute_insight(
    workspace_id: str, store_id: str, actor_id: str, kind: str, params: dict, lease_token: str
):
    """Recompute one snapshot if its inputs changed. Arguments are identifiers and periods."""
    settings = get_settings()
    engine = build_engine(settings)
    redis = Redis.from_url(
        settings.redis_broker_url, socket_connect_timeout=3, socket_timeout=3, decode_responses=True
    )
    vault = SecretVault(settings.security_file)
    workspace, store_uuid, actor = UUID(workspace_id), UUID(store_id), UUID(actor_id)
    try:
        with Session(engine) as db, db.begin():
            from sqlalchemy import text

            if db.scalar(
                text("SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname=current_user")
            ):
                raise RuntimeError("unsafe_worker_database_role")
            set_actor(db, actor)
            if not member_store(db, workspace, store_uuid, actor):
                return
            if kind == "reports":
                for start, end in insight_compute.warm_report_periods():
                    insight_compute.finance_report(
                        db, redis, vault, workspace, store_uuid, start, end, None, 100
                    )
            else:
                insight_snapshots.refresh(
                    db,
                    vault,
                    workspace,
                    store_uuid,
                    kind,
                    params,
                    lambda session: insight_compute.build(
                        kind, params, session, redis, vault, workspace, store_uuid
                    ),
                )
    except Exception:
        logger.error("insight_compute_unavailable kind=%s", kind)
    finally:
        try:
            insight_snapshots.release(
                redis, vault, workspace, store_uuid, kind, params, lease_token
            )
        except Exception:
            logger.error("insight_lease_unavailable")
        redis.close()
        release_engine(engine)


@celery_app.task(name="perk.insights.warm", ignore_result=True, soft_time_limit=50, time_limit=60)
def warm_all_insights():
    """Periodic: snapshots depend on today's date, so they refresh after midnight too."""
    settings = get_settings()
    engine = build_engine(settings)
    redis = Redis.from_url(
        settings.redis_broker_url, socket_connect_timeout=3, socket_timeout=3, decode_responses=True
    )
    try:
        vault = SecretVault(settings.security_file)
        # users has no RLS; memberships and stores are read as each user (forced RLS).
        with Session(engine) as db:
            users = db.scalars(
                select(User.id).where(User.is_active.is_(True), User.email_verified_at.is_not(None))
            ).all()
        for user_id in users:
            with Session(engine) as db, db.begin():
                set_actor(db, user_id)
                stores = db.execute(
                    select(Store.workspace_id, Store.id)
                    .join(Membership, Membership.workspace_id == Store.workspace_id)
                    .where(
                        Membership.user_id == user_id,
                        Membership.role.in_(["owner", "admin"]),
                        Store.marketplace.in_(REPORTING_MARKETPLACES),
                        Store.is_active.is_(True),
                    )
                ).all()
            for workspace_id, store_id in stores:
                warm_insights(redis, vault, workspace_id, store_id, user_id)
    except Exception:
        logger.error("insights_warm_unavailable")
    finally:
        redis.close()
        release_engine(engine)


@celery_app.task(
    name="perk.maintenance.cleanup", ignore_result=True, soft_time_limit=110, time_limit=120
)
def cleanup_expired():
    """Remove expired codes, tokens, sessions and previews via a narrow database function."""
    from sqlalchemy import text

    engine = build_engine(get_settings())
    try:
        removed = 0
        # Small batches, each its own statement and transaction: stays under statement_timeout
        # and never holds long locks. A large backlog is finished by the next runs.
        for _ in range(50):
            with Session(engine) as db, db.begin():
                count = db.scalar(text("SELECT perk_cleanup_expired(2000)"))
            removed += count
            if not count:
                break
        logger.info("cleanup_completed removed=%s", removed)
    except Exception:
        logger.error("cleanup_unavailable")
    finally:
        release_engine(engine)


@celery_app.task(
    name="perk.notifications.dispatch", ignore_result=True, soft_time_limit=240, time_limit=270
)
def dispatch_notifications():
    """Alerts and the morning digest from snapshots, then Telegram/push delivery."""
    from app.integrations.notifications import build_messenger
    from app.modules.notifications import service as notifications
    from sqlalchemy import text

    settings = get_settings()
    engine = build_engine(settings)
    redis = Redis.from_url(settings.redis_broker_url, socket_connect_timeout=3, socket_timeout=3)
    try:
        vault = SecretVault(settings.security_file)
        telegram, push = build_messenger(settings)
        # Memberships are read inside generate() under each user's actor (forced RLS).
        with Session(engine) as db:
            users = db.scalars(text("SELECT perk_notification_users()")).all()
        for user_id in users:
            try:
                with Session(engine) as db, db.begin():
                    set_actor(db, user_id)
                    notifications.generate(db, vault, user_id, redis=redis)
                with Session(engine) as db, db.begin():
                    set_actor(db, user_id)
                    notifications.deliver(db, vault, user_id, telegram, push)
            except Exception:
                logger.error("notifications_user_unavailable")
    except Exception:
        logger.error("notifications_dispatch_unavailable")
    finally:
        redis.close()
        release_engine(engine)
