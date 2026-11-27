"""Period totals from the WB funnel; they never become daily chart points.

The existing encrypted staging area and sync outbox handle pagination and retries.
Only a complete period replaces its cached totals. The provider quota is the same
as for daily funnel requests, regardless of which screen requested the period.
"""

import json
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import delete, select, text

from app.integrations.wildberries.data import Source
from app.modules.auth.dependencies import now
from app.modules.finance.precision import money_precision
from app.modules.sync.analytics import FUNNEL_FIELDS, record_context
from app.modules.sync.models import SyncRun, WBStagedRecord
from app.modules.sync.normalize import normalize

SOURCE = "funnel_summary"  # Internal outbox job, not another WB method or sync schedule.
KIND = "funnel_summary"
MAX_AGE = timedelta(hours=6)


def params(start, end):
    return {"date_from": start.isoformat(), "date_to": end.isoformat()}


def previous(start, end):
    return start - (end - start) - timedelta(days=1), start - timedelta(days=1)


def address(vault, start, end):
    from app.modules.insights import snapshots

    return snapshots.params_key(vault, KIND, params(start, end))


def enqueue(db, vault, workspace_id, store_id, owner_id, start, end):
    """Called with the configured owner's RLS identity, after checking store access."""
    from app.modules.insights import snapshots

    key = address(vault, start, end)
    locked = db.scalar(
        text("SELECT pg_try_advisory_xact_lock(:key)"),
        {"key": snapshots.lock_id(vault, workspace_id, store_id, KIND, key)},
    )
    if not locked:
        return
    current = snapshots.meta(db, workspace_id, store_id, KIND, key)
    if current and current.computed_at > now() - MAX_AGE:
        return
    latest = db.scalar(
        select(SyncRun)
        .where(
            SyncRun.workspace_id == workspace_id,
            SyncRun.store_id == store_id,
            SyncRun.source == SOURCE,
            SyncRun.date_from == start,
            SyncRun.date_to == end,
        )
        .order_by(SyncRun.created_at.desc())
        .limit(1)
    )
    if latest and (
        latest.status in {"queued", "running"}
        or latest.status == "failed"
        and latest.finished_at > now() - timedelta(minutes=5)
    ):
        return
    db.add(
        SyncRun(
            id=uuid4(),
            workspace_id=workspace_id,
            store_id=store_id,
            requested_by=owner_id,
            source=SOURCE,
            sync_mode="summary",
            date_from=start,
            date_to=end,
            cursor={"summary": True},
        )
    )
    db.flush()


def normalize_row(row):
    """Reuse funnel field validation, keeping period totals out of daily aggregates."""
    try:
        start, end = row["period_from"], row["period_to"]
    except KeyError, TypeError:
        from app.integrations.wildberries.data import WBError

        raise WBError("wb_invalid_record") from None
    key, values = normalize(Source.FUNNEL, {**row, "day": start})
    del values["day"]
    values.update(period_from=start, period_to=end)
    return key, values


@money_precision()
def publish(db, vault, run):
    from app.modules.insights import snapshots
    from app.modules.insights.funnel import SUMS, view

    before_start, before_end = previous(run.date_from, run.date_to)
    totals = {
        str(run.date_from): defaultdict(Decimal),
        str(before_start): defaultdict(Decimal),
    }
    currencies = set()
    rows = db.scalars(
        select(WBStagedRecord)
        .where(
            WBStagedRecord.workspace_id == run.workspace_id,
            WBStagedRecord.store_id == run.store_id,
            WBStagedRecord.run_id == run.id,
        )
        .execution_options(yield_per=500)
    )
    for row in rows:
        data = json.loads(
            vault.open(
                row.ciphertext,
                record_context(run.workspace_id, run.store_id, SOURCE, row.record_key),
            )
        )
        currencies.add(data["currency"])
        target = totals[data["period_from"]]
        for field in (*FUNNEL_FIELDS, *SUMS):
            target[field] += Decimal(data[field])
    # Even an empty, successful WB response confirms zeros and its currency.
    currency = run.cursor.get("currency")
    if currency:
        currencies.add(currency)
    single = len(currencies) == 1
    data = {
        **params(run.date_from, run.date_to),
        "status": "ready",
        "currency": next(iter(currencies)) if single else None,
        "totals": view(totals[str(run.date_from)], single),
        "previous": {
            **params(before_start, before_end),
            "totals": view(totals[str(before_start)], single),
        },
    }
    snapshots.save(
        db,
        vault,
        run.workspace_id,
        run.store_id,
        KIND,
        address(vault, run.date_from, run.date_to),
        str(uuid4()),
        data,
    )
    db.execute(delete(WBStagedRecord).where(WBStagedRecord.run_id == run.id))


def read(db, vault, workspace_id, store_id, start, end):
    from app.modules.insights import snapshots
    from app.modules.insights.funnel import unknown

    cached, data = snapshots.load(
        db, vault, workspace_id, store_id, KIND, address(vault, start, end)
    )
    latest = db.scalar(
        select(SyncRun)
        .where(
            SyncRun.workspace_id == workspace_id,
            SyncRun.store_id == store_id,
            SyncRun.source == SOURCE,
            SyncRun.date_from == start,
            SyncRun.date_to == end,
        )
        .order_by(SyncRun.created_at.desc())
        .limit(1)
    )
    stale = cached is None or cached.computed_at <= now() - MAX_AGE
    failed = latest is not None and latest.status == "failed"
    if data is None:
        before_start, before_end = previous(start, end)
        data = {
            **params(start, end),
            "status": "error" if failed else "preparing",
            "currency": None,
            "totals": unknown(),
            "previous": {**params(before_start, before_end), "totals": unknown()},
        }
    return {
        **data,
        "error_code": latest.error_code if failed else None,
        "freshness": {
            "computed_at": cached.computed_at if cached else now(),
            "stale": stale,
        },
    }
