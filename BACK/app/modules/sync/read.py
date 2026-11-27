"""Read published encrypted records and bounded status metadata; never call WB."""

import json
from contextlib import contextmanager
from dataclasses import dataclass

from sqlalchemy import select

from app.db.tenant import scope
from app.modules.sync.models import SyncRun, WBRecord
from app.modules.sync.service import context

MEMO = "perk_retained_memo"


@contextmanager
def read_once(db):
    """Within this block, each (store, source) snapshot is read and decrypted once.

    For read models that combine several helpers over the same records (the stock
    overview reads stocks through the catalog and again itself). Only active inside the
    block, so writers and later reads in the same session always see current rows.
    The cached rows are shared: callers inside the block must not modify them.
    """
    if MEMO in db.info:
        yield
        return
    db.info[MEMO] = {}
    try:
        yield
    finally:
        db.info.pop(MEMO, None)


def retained(db, vault, workspace_id, store_id, source):
    memo = db.info.get(MEMO) if isinstance(getattr(db, "info", None), dict) else None
    if memo is None:
        return read_records(db, vault, workspace_id, store_id, source)
    key = (str(workspace_id), str(store_id), str(source))
    if key not in memo:
        memo[key] = list(read_records(db, vault, workspace_id, store_id, source))
    return iter(memo[key])


def read_records(db, vault, workspace_id, store_id, source):
    # Scalar columns avoid building thousands of temporary ORM entities.
    rows = db.execute(
        select(WBRecord.record_key, WBRecord.ciphertext)
        .where(*scope(WBRecord, workspace_id, store_id), WBRecord.source == source)
        .order_by(WBRecord.record_key)
        .execution_options(yield_per=500)
    )
    for key, ciphertext in rows:
        yield json.loads(vault.open(ciphertext, context(workspace_id, store_id, source, key)))


@dataclass
class SourceState:
    success: SyncRun | None = None
    loading: bool = False


def source_states(db, workspace_id, store_id, sources):
    """At most three rows/source regardless of years of sync history.

    DISTINCT ON uses PostgreSQL: last successful run plus queued/running markers.
    A newer failed run must never hide the previous published snapshot.
    """
    states = {source: SourceState() for source in sources}
    if not states:
        return states
    runs = db.scalars(
        select(SyncRun)
        .where(
            *scope(SyncRun, workspace_id, store_id),
            SyncRun.source.in_(states),
            SyncRun.status.in_(["succeeded", "queued", "running"]),
        )
        .distinct(SyncRun.source, SyncRun.status)
        .order_by(SyncRun.source, SyncRun.status, SyncRun.created_at.desc(), SyncRun.id.desc())
    )
    for run in runs:
        state = states[run.source]
        if run.status == "succeeded":
            state.success = run
        else:
            state.loading = True
    return states
