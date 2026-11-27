"""Fresh data first, resumable backfill, and periodic delta refreshes."""

from datetime import datetime, timedelta
from uuid import uuid4

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.db.session import set_actor
from app.integrations.wildberries.data import CHANGE_FEEDS, DATED, Source
from app.modules.accounts.models import Store, StoreCredential
from app.modules.auth.dependencies import now
from app.modules.auth.models import Membership, User
from app.modules.sync.capabilities import sync_capabilities
from app.modules.sync.models import SyncRun, SyncSchedule
from app.modules.sync.schemas import ConfigureSchedule, history_limits, moscow_today

REFRESH = {
    Source.BALANCE: timedelta(minutes=15),
    Source.CATALOG: timedelta(hours=6),
    Source.PRICES: timedelta(hours=6),
    Source.FBS: timedelta(hours=1),
    Source.STOCK_HISTORY: timedelta(hours=6),
    Source.SUPPLY_DEMAND: timedelta(hours=6),
    Source.SUPPLY_DEMAND_FBS: timedelta(hours=6),
    Source.SUPPLIES: timedelta(hours=1),
    Source.SALES: timedelta(minutes=15),
    # WB refreshes the orders report every 30 minutes.
    Source.ORDERS: timedelta(minutes=30),
    Source.FINANCE: timedelta(hours=6),
    Source.STOCKS: timedelta(hours=1),
    # WB updates the funnel every 2 hours; each refresh re-reads the last 30 days.
    Source.FUNNEL: timedelta(hours=6),
    # Statuses and pickup deadlines change; each refresh re-reads the last 30 days.
    Source.RETURNS: timedelta(hours=6),
}

# Each history chunk is published separately, newest first: recent months appear in minutes and
# one publication stays well inside the page task time limit. A long funnel history takes one
# request per day; returns are limited to 31-day windows by WB.
BACKFILL_CHUNK_DAYS = {Source.FUNNEL: 7, Source.RETURNS: 31, Source.FINANCE: 31}


def chunk_days(plan):
    """Older plans may store a larger chunk; sync_size_limit may only make it smaller."""
    return min(plan.backfill_chunk_days, BACKFILL_CHUNK_DAYS.get(Source(plan.source), 3650))


def recent_period(schedule):
    end = moscow_today() - timedelta(days=1)
    return end - timedelta(days=schedule.recent_days - 1), end


def initial_period(schedule):
    start, end = recent_period(schedule)
    return (end - timedelta(days=6), end) if schedule.source == Source.FUNNEL else (start, end)


def configure_initial(db, store, user_id, settings, vault):
    """Start imports once when WB is connected, independent of the client platform."""
    existing = db.scalar(
        select(SyncSchedule.source)
        .where(SyncSchedule.workspace_id == store.workspace_id, SyncSchedule.store_id == store.id)
        .limit(1)
    )
    if existing is not None:
        return []  # Keep the user's existing schedule and history progress.
    credential = db.scalar(
        select(StoreCredential).where(
            StoreCredential.workspace_id == store.workspace_id, StoreCredential.store_id == store.id
        )
    )
    capabilities = sync_capabilities(credential, vault, settings, store.workspace_id, store.id)
    return configure(
        db, store, user_id, ConfigureSchedule(sources=list(Source)), capabilities, vault
    )


def configure(db, store, user_id, data, capabilities, vault=None):
    result = []
    for source in Source:
        plan = db.get(SyncSchedule, (store.workspace_id, store.id, source))
        enabled = data.enabled and source in data.effective_sources()
        error = capabilities["sources"][source]["error_code"] if enabled else None
        if plan is None and not enabled:
            continue
        if plan is None:
            plan = SyncSchedule(
                workspace_id=store.workspace_id,
                store_id=store.id,
                source=source,
                requested_by=user_id,
                recent_days=data.recent_days,
                recent_completed=False,
                backfill_chunk_days=BACKFILL_CHUNK_DAYS.get(source, 3650),
                next_attempt_at=now(),
                next_refresh_at=now(),
                reconcile_at=now(),
            )
            db.add(plan)
            # A recent complete dataset can immediately serve the screen.
            latest = db.scalar(
                select(SyncRun)
                .where(
                    SyncRun.workspace_id == store.workspace_id,
                    SyncRun.store_id == store.id,
                    SyncRun.source == source,
                    SyncRun.status == "succeeded",
                )
                .order_by(SyncRun.finished_at.desc())
                .limit(1)
            )
            start, end = recent_period(plan)
            if latest and (
                source not in DATED or latest.date_from <= start and latest.date_to >= end
            ):
                plan.recent_completed = True
                plan.last_completed_at = latest.finished_at
                plan.next_refresh_at = latest.finished_at + REFRESH[source]
        plan.requested_by = user_id
        plan.enabled = enabled and not error
        plan.error_code = error
        if plan.recent_days != data.recent_days and source in DATED:
            plan.recent_completed = False
        plan.recent_days = data.recent_days
        if source in DATED and data.load_history:
            floor = history_limits()[source]["date_from"]
            if source == Source.FUNNEL:
                floor = max(floor, moscow_today() - timedelta(days=28))
            if plan.history_from is None:
                plan.history_from = floor
                plan.backfill_to = initial_period(plan)[0] - timedelta(days=1)
        else:
            plan.history_from, plan.backfill_to = None, None
        # Disabled plans retain their cursor; enabling again does not redownload history.
        plan.next_attempt_at = now()
        result.append(plan)
    db.flush()
    enqueue_store(db, store, capabilities, vault)
    return result


def next_run(plan):
    source = Source(plan.source)
    start, end = recent_period(plan)
    mode = "recent"
    cursor = {"direction": "desc"} if source == Source.FUNNEL else {}
    if source in DATED and plan.history_from:
        # Rolling provider windows (sales/orders 90 days, funnel 360): never ask for older.
        plan.history_from = max(plan.history_from, history_limits()[source]["date_from"])
    if source not in DATED:
        if plan.recent_completed and plan.next_refresh_at > now():
            return None
        if source in {Source.STOCK_HISTORY, Source.SUPPLY_DEMAND, Source.SUPPLY_DEMAND_FBS}:
            return "snapshot", end - timedelta(days=27), end, cursor
        return "snapshot", None, None, cursor
    if not plan.recent_completed:
        start, end = initial_period(plan)
        return mode, start, end, cursor
    pending = plan.history_from and plan.backfill_to and plan.backfill_to >= plan.history_from
    if pending and (plan.history_turn or plan.next_refresh_at > now()):
        end = plan.backfill_to
        start = (
            plan.history_from
            if source in CHANGE_FEEDS
            else max(
                plan.history_from,
                end - timedelta(days=chunk_days(plan) - 1),
            )
        )
        # One history chunk between refreshes prevents starvation with a 12-hour Basic quota.
        return "backfill", start, end, cursor
    if plan.next_refresh_at <= now():
        mode = "incremental"
        if source in CHANGE_FEEDS:
            start, end = history_limits()[source]["date_from"], moscow_today()
            if plan.sales_cursor:
                changed = datetime.fromisoformat(plan.sales_cursor)
                floor = datetime.combine(start, datetime.min.time())
                changed = max(floor, changed.replace(tzinfo=None) - timedelta(days=3))
                cursor = {"last_change": changed.isoformat(), "initial": True}
        else:
            days = 90 if plan.reconcile_at <= now() else 30
            start = max(history_limits()[source]["date_from"], end - timedelta(days=days - 1))
            if days == 90:
                mode = "reconcile"
        return mode, start, end, cursor
    return None


def finance_gap(db, plan):
    """Find a skipped interval after history catches up with a moving recent window."""
    if (
        plan.source != Source.FINANCE
        or not plan.recent_completed
        or not plan.history_from
        or not plan.backfill_to
        or plan.backfill_to >= plan.history_from
    ):
        return None
    yesterday = moscow_today() - timedelta(days=1)
    periods = db.execute(
        select(SyncRun.date_from, SyncRun.date_to)
        .where(
            SyncRun.workspace_id == plan.workspace_id,
            SyncRun.store_id == plan.store_id,
            SyncRun.source == Source.FINANCE,
            SyncRun.status == "succeeded",
            SyncRun.date_from <= yesterday,
            SyncRun.date_to >= plan.history_from,
        )
        .order_by(SyncRun.date_from)
    )
    cursor = plan.history_from
    for start, end in periods:
        if start > cursor:
            return cursor, min(
                start - timedelta(days=1), cursor + timedelta(days=chunk_days(plan) - 1)
            )
        cursor = max(cursor, end + timedelta(days=1))
    # The uncovered tail belongs to the normal refresh cadence.
    return None


def enqueue_store(db, store, capabilities, vault_for_plan=None):
    plans = db.scalars(
        select(SyncSchedule)
        .join(Membership, Membership.workspace_id == SyncSchedule.workspace_id)
        .where(
            Membership.user_id == SyncSchedule.requested_by,
            Membership.role.in_(["owner", "admin"]),
            SyncSchedule.workspace_id == store.workspace_id,
            SyncSchedule.store_id == store.id,
            SyncSchedule.enabled.is_(True),
            SyncSchedule.next_attempt_at <= now(),
        )
        .with_for_update(of=SyncSchedule)
    ).all()
    for plan in plans:
        owner = db.scalar(
            select(User.id)
            .join(Membership, Membership.user_id == User.id)
            .where(
                User.id == plan.requested_by,
                User.is_active.is_(True),
                User.email_verified_at.is_not(None),
                Membership.workspace_id == store.workspace_id,
                Membership.role.in_(["owner", "admin"]),
            )
        )
        error = capabilities["sources"][plan.source]["error_code"]
        if not owner or error:
            plan.enabled, plan.error_code = False, error or "sync_permission_revoked"
            continue
        if plan.source == Source.FUNNEL and vault_for_plan is not None:
            from app.modules.sync import funnel_summary

            end = moscow_today() - timedelta(days=1)
            periods = (7, 14, 28) if plan.recent_completed else (7,)
            for days in periods:
                funnel_summary.enqueue(
                    db,
                    vault_for_plan,
                    store.workspace_id,
                    store.id,
                    plan.requested_by,
                    end - timedelta(days=days - 1),
                    end,
                )
        if plan.source == Source.FBS and not db.scalar(
            select(SyncRun.id)
            .where(
                SyncRun.workspace_id == store.workspace_id,
                SyncRun.store_id == store.id,
                SyncRun.source == Source.CATALOG,
                SyncRun.status == "succeeded",
            )
            .limit(1)
        ):
            continue
        active = db.scalar(
            select(SyncRun.id).where(
                SyncRun.workspace_id == store.workspace_id,
                SyncRun.store_id == store.id,
                SyncRun.source == plan.source,
                SyncRun.status.in_(["queued", "running"]),
            )
        )
        if active:
            continue
        selected = next_run(plan)
        if selected is None and (gap := finance_gap(db, plan)):
            selected = "reconcile", *gap, {}
        if selected:
            mode, start, end, cursor = selected
            db.add(
                SyncRun(
                    id=uuid4(),
                    workspace_id=store.workspace_id,
                    store_id=store.id,
                    requested_by=plan.requested_by,
                    source=plan.source,
                    sync_mode=mode,
                    date_from=start,
                    date_to=end,
                    cursor=cursor,
                )
            )
        else:
            plan.next_attempt_at = plan.next_refresh_at


def completed(db, run, success):
    # A format upgrade must never rewind or disable the regular refresh/backfill plan.
    if (run.sync_mode or "").startswith("fields_v"):
        return
    # Former owners cannot write protected plan rows; their outbox task still terminates.
    if not db.scalar(
        select(Membership.user_id).where(
            Membership.workspace_id == run.workspace_id,
            Membership.user_id == run.requested_by,
            Membership.role.in_(["owner", "admin"]),
        )
    ):
        return
    plan = db.get(SyncSchedule, (run.workspace_id, run.store_id, run.source))
    if not plan or not plan.enabled:
        return
    if not success:
        plan.error_code = run.error_code
        if run.error_code == "sync_size_limit":
            if (
                run.source == Source.FINANCE
                and run.sync_mode == "backfill"
                and run.date_from < run.date_to
            ):
                plan.backfill_chunk_days = max(1, (run.date_to - run.date_from).days // 2)
                plan.history_turn = True
            else:
                plan.enabled = False
        if run.error_code in {
            "sync_permission_revoked",
            "wb_token_policy_rejected",
            "wb_token_type_unsupported",
            "wb_scope_missing",
            "credential_unavailable",
            "store_not_connected",
            "wb_token_rejected",
            "wb_access_denied",
            "wb_subscription_required",
        }:
            plan.enabled = False
        plan.next_attempt_at = now() + max(REFRESH[run.source], timedelta(hours=1))
        return
    plan.error_code, plan.last_completed_at = None, now()
    recent_start, recent_end = (
        initial_period(plan) if run.sync_mode == "recent" else recent_period(plan)
    )
    covers_recent = run.source not in DATED or (
        run.date_from <= recent_start and run.date_to >= recent_end
    )
    if covers_recent:
        plan.recent_completed = True
        plan.next_refresh_at = now() + REFRESH[run.source]
        if run.source in CHANGE_FEEDS:
            # Initial runs exclude today's business events: re-read from yesterday on next refresh.
            changed = run.cursor.get("last_change")
            if run.sync_mode != "incremental":
                changed = run.date_to.isoformat()
            if changed:
                plan.sales_cursor = max(plan.sales_cursor or "", changed)
        if run.sync_mode == "reconcile":
            plan.reconcile_at = now() + timedelta(days=7)
    if run.sync_mode == "backfill":
        plan.backfill_to = run.date_from - timedelta(days=1)
        plan.history_turn = False
    pending = plan.history_from and plan.backfill_to and plan.backfill_to >= plan.history_from
    if run.sync_mode in {"recent", "incremental", "reconcile"} or covers_recent:
        plan.history_turn = bool(pending)
    pending = pending or finance_gap(db, plan) is not None
    plan.next_attempt_at = max(now(), run.next_attempt_at) if pending else plan.next_refresh_at


def schedule_due(engine, vault, settings):
    # Discovery reads only existing outbox owner IDs. RLS stays enabled for all plan/data access.
    with Session(engine) as db:
        if db.scalar(
            text("SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname=current_user")
        ):
            raise RuntimeError("unsafe_worker_database_role")
        actors = db.scalars(text("SELECT perk_queue_actors('warm')")).all()
    for actor in actors:
        with Session(engine) as db, db.begin():
            set_actor(db, actor)
            candidates = db.execute(
                select(SyncSchedule.workspace_id, SyncSchedule.store_id)
                .where(
                    SyncSchedule.requested_by == actor,
                    SyncSchedule.enabled.is_(True),
                    SyncSchedule.next_attempt_at <= now(),
                )
                .distinct()
            ).all()
            for workspace_id, store_id in candidates:
                store = db.scalar(
                    select(Store)
                    .where(Store.workspace_id == workspace_id, Store.id == store_id)
                    .with_for_update(skip_locked=True, key_share=True)
                )
                if not store:
                    continue
                credential = db.scalar(
                    select(StoreCredential).where(
                        StoreCredential.workspace_id == workspace_id,
                        StoreCredential.store_id == store_id,
                    )
                )
                if not store.is_active or store.connection_status != "connected":
                    for plan in db.scalars(
                        select(SyncSchedule).where(
                            SyncSchedule.workspace_id == workspace_id,
                            SyncSchedule.store_id == store_id,
                        )
                    ):
                        plan.enabled, plan.error_code = False, "store_not_connected"
                    continue
                enqueue_store(
                    db,
                    store,
                    sync_capabilities(credential, vault, settings, workspace_id, store_id),
                    vault,
                )
