"""Cheap live progress from confirmed days and the active import, without report decryption."""

from datetime import timedelta

from sqlalchemy import select

from app.db.tenant import scope
from app.integrations.wildberries.data import Source
from app.modules.insights.funnel_days import datasets
from app.modules.sync.models import SyncRun, SyncSchedule, WBMetricVersion
from app.modules.sync.schemas import history_limits


def read(db, vault, wid, sid, start, end):
    known = set(datasets(db, wid, sid, start, end))
    floor = history_limits()[Source.FUNNEL]["date_from"]
    available = {
        start + timedelta(days=i)
        for i in range((end - start).days + 1)
        if start + timedelta(days=i) >= floor
    } | known
    run = db.scalar(
        select(SyncRun)
        .where(
            *scope(SyncRun, wid, sid),
            SyncRun.source == Source.FUNNEL,
            SyncRun.status.in_(["queued", "running"]),
            SyncRun.date_from <= end,
            SyncRun.date_to >= start,
        )
        .order_by(SyncRun.created_at.desc())
        .limit(1)
    )
    plan = db.get(SyncSchedule, (wid, sid, Source.FUNNEL))
    version = db.get(WBMetricVersion, (wid, sid))
    pending = bool(
        run
        or plan
        and plan.enabled
        and not plan.error_code
        and (
            not plan.recent_completed
            or plan.history_from
            and plan.backfill_to
            and plan.backfill_to >= max(start, plan.history_from)
        )
    )
    marker = ":".join(
        str(value)
        for value in (
            version.version if version else "",
            run.id if run else "",
            run.pages_processed if run else 0,
            run.records_processed if run else 0,
            len(known),
        )
    )
    return {
        "revision": vault.digest("funnel-live-progress", marker),
        "known_days": len(known),
        "available_days": len(available),
        "is_loading": bool(available - known and pending),
        "records_processed": run.records_processed if run else 0,
        "pages_processed": run.pages_processed if run else 0,
        "next_attempt_at": run.next_attempt_at
        if run
        else plan.next_attempt_at
        if pending and plan
        else None,
        "error_code": run.error_code if run else plan.error_code if plan else None,
    }
