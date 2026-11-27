"""Choose one dataset per confirmed funnel day; never add a preview to old totals."""

from datetime import date, timedelta

from sqlalchemy import select

from app.db.tenant import scope
from app.integrations.wildberries.data import Source
from app.modules.sync.analytics import coverage
from app.modules.sync.models import SyncRun


def datasets(db, workspace_id, store_id, start, end):
    selected = {}
    for window in coverage(db, workspace_id, store_id)[Source.FUNNEL]:
        day = max(date.fromisoformat(window["date_from"]), start)
        right = min(date.fromisoformat(window["date_to"]), end)
        while day <= right:
            selected[day] = "published"
            day += timedelta(days=1)
    runs = db.scalars(
        select(SyncRun)
        .where(
            *scope(SyncRun, workspace_id, store_id),
            SyncRun.source == Source.FUNNEL,
            SyncRun.status == "running",
            SyncRun.preview_updated_at.is_not(None),
            SyncRun.date_from <= end,
            SyncRun.date_to >= start,
        )
        .order_by(SyncRun.created_at)
    )
    for run in runs:
        # offset=0 points to the NEXT day; offset>0 is still an unfinished day.
        # In both cases only days strictly behind the cursor are confirmed.
        cursor_day = run.cursor.get("day")
        if not cursor_day:
            continue
        current = date.fromisoformat(cursor_day)
        descending = run.cursor.get("direction") == "desc"
        day = max(run.date_from, start)
        while day <= min(run.date_to, end):
            if day > current if descending else day < current:
                selected[day] = str(run.id)
            day += timedelta(days=1)
    return selected
