"""Versioned, resumable upgrades of saved finance imports for any store."""

from datetime import timedelta
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.modules.accounts.models import Store, StoreCredential
from app.modules.auth.dependencies import now
from app.modules.auth.models import Membership, User
from app.modules.finance.fields import DATA_VERSION
from app.modules.sync.models import SyncRun, SyncSchedule

UPGRADE_MODE = f"fields_v{DATA_VERSION}"
WINDOW_RECORDS = 200_000


def next_window(day_counts, legacy_days):
    """Bound by records, not a fixed month: large and small stores use the same rules."""
    if not legacy_days:
        return None, None
    start, last = min(legacy_days), max(legacy_days)
    end, records = start, 0
    for day, count in sorted(day_counts.items()):
        if not start <= day <= last:
            continue
        if records and records + count > WINDOW_RECORDS:
            break
        records += count
        end = day
    return start, end


def enqueue(db, workspace_id, store_id, actor_id):
    """Only create an outbox task. The ordinary sync worker enforces WB quotas and retries."""
    from app.modules.finance.models import FinanceProjection
    from app.modules.finance.projection import FORMAT, source_run

    state = db.get(FinanceProjection, (workspace_id, store_id))
    if (
        state is None
        or state.format_version != FORMAT
        or state.legacy_date_from is None
        or state.source_run_id != source_run(db, workspace_id, store_id)
    ):
        return False
    eligible = db.scalar(
        select(Store.id)
        .join(Membership, Membership.workspace_id == Store.workspace_id)
        .join(User, User.id == Membership.user_id)
        .where(
            Store.workspace_id == workspace_id,
            Store.id == store_id,
            Store.is_active.is_(True),
            Store.connection_status == "connected",
            Membership.user_id == actor_id,
            Membership.role.in_(["owner", "admin"]),
            User.is_active.is_(True),
            User.email_verified_at.is_not(None),
        )
    )
    if eligible is None:
        return False
    plan = db.get(SyncSchedule, (workspace_id, store_id, "finance"))
    if plan is not None and not plan.enabled:
        return False
    credential = db.scalar(
        select(StoreCredential).where(
            StoreCredential.workspace_id == workspace_id, StoreCredential.store_id == store_id
        )
    )
    if (
        credential is None
        or credential.expires_at <= now()
        or "finance" not in credential.scopes.split(",")
    ):
        return False
    base = (
        SyncRun.workspace_id == workspace_id,
        SyncRun.store_id == store_id,
        SyncRun.source == "finance",
    )
    if db.scalar(
        select(SyncRun.id).where(*base, SyncRun.status.in_(["queued", "running"])).limit(1)
    ):
        return False
    attempts = db.scalars(
        select(SyncRun)
        .where(
            *base,
            SyncRun.sync_mode == UPGRADE_MODE,
            SyncRun.date_from <= state.legacy_date_from,
            SyncRun.date_to >= state.legacy_date_to,
        )
        .order_by(SyncRun.created_at.desc())
    ).all()
    if any(
        run.status == "succeeded" or run.created_at > now() - timedelta(hours=6) for run in attempts
    ):
        return False
    try:
        with db.begin_nested():
            db.add(
                SyncRun(
                    id=uuid4(),
                    workspace_id=workspace_id,
                    store_id=store_id,
                    source="finance",
                    requested_by=actor_id,
                    sync_mode=UPGRADE_MODE,
                    date_from=state.legacy_date_from,
                    date_to=state.legacy_date_to,
                    cursor={"page_size": 100000},
                )
            )
            db.flush()
    except IntegrityError:
        # Another process won the unique active-source constraint; preserve the prepared report.
        return False
    return True
