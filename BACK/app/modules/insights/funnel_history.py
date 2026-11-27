"""Provider history plus retained published days, independent of the selected period."""

from datetime import timedelta

from sqlalchemy import func, select

from app.db.tenant import scope
from app.integrations.wildberries.data import Source
from app.modules.sync.models import SyncRun
from app.modules.sync.schemas import FINANCE_START, history_limits, moscow_today


def availability(db, workspace_id, store_id):
    earliest = db.scalar(
        select(func.min(SyncRun.date_from)).where(
            *scope(SyncRun, workspace_id, store_id),
            SyncRun.source == Source.FUNNEL,
            SyncRun.status == "succeeded",
            SyncRun.date_to.is_not(None),
        )
    )
    provider = history_limits()[Source.FUNNEL]["date_from"]
    # Successful empty imports also prove coverage. Never drop retained history as time passes.
    first = min(provider, earliest) if earliest else provider
    return {"date_from": max(FINANCE_START, first), "date_to": moscow_today() - timedelta(days=1)}
