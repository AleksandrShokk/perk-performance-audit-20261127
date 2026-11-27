"""Prepare retained WB reports in a background transaction; never fetch WB on a report read."""

import json
from collections import Counter, defaultdict
from decimal import Decimal

from sqlalchemy import delete, select

from app.db.tenant import scope
from app.integrations.wildberries.data import Source
from app.modules.auth.dependencies import now
from app.modules.finance.facts import facts, original_sales
from app.modules.finance.fields import DATA_VERSION
from app.modules.finance.history import next_window
from app.modules.finance.models import FinanceDay, FinanceProjection
from app.modules.finance.precision import money_precision
from app.modules.sync.analytics import record_context
from app.modules.sync.models import SyncRun, WBRecord

FORMAT = 5
# v5 adds upgrade metadata; the accounting facts in v4 and v5 are identical.
READABLE_FORMATS = {4, 5}


def day_aad(workspace_id, store_id, day, currency):
    return f"perk-finance-day:v1:{workspace_id}:{store_id}:{day}:{currency}"


def source_run(db, workspace_id, store_id):
    return db.scalar(
        select(SyncRun.id)
        .where(
            *scope(SyncRun, workspace_id, store_id),
            SyncRun.source == Source.FINANCE,
            SyncRun.status == "succeeded",
        )
        .order_by(SyncRun.finished_at.desc(), SyncRun.id)
        .limit(1)
    )


def retained_rows(db, vault, workspace_id, store_id):
    last_key = ""
    while True:
        batch = db.execute(
            select(WBRecord.record_key, WBRecord.ciphertext)
            .where(
                *scope(WBRecord, workspace_id, store_id),
                WBRecord.source == Source.FINANCE,
                WBRecord.record_key > last_key,
            )
            .order_by(WBRecord.record_key)
            .limit(1000)
        ).all()
        if not batch:
            return
        for key, ciphertext in batch:
            yield json.loads(
                vault.open(ciphertext, record_context(workspace_id, store_id, Source.FINANCE, key))
            )
        last_key = batch[-1][0]


@money_precision()
def prepare(db, vault, workspace_id, store_id):
    """Caller holds the store lock. Replacement/version commit together or not at all."""
    source = source_run(db, workspace_id, store_id)
    current = db.get(FinanceProjection, (workspace_id, store_id))
    if source is None or (
        current and current.source_run_id == source and current.format_version == FORMAT
    ):
        return False
    links = original_sales(retained_rows(db, vault, workspace_id, store_id))
    days = defaultdict(lambda: defaultdict(lambda: defaultdict(Decimal)))
    counts, legacy = Counter(), set()
    for row in retained_rows(db, vault, workspace_id, store_id):
        day, key, values = facts(row, links)
        counts[day[0]] += 1
        if row.get("data_version", 1) < DATA_VERSION:
            legacy.add(day[0])
        for field, amount in values.items():
            # Readers use zero defaults. Avoid dozens of empty Decimals per product/day.
            if amount:
                days[day][key][field] += amount
    db.execute(delete(FinanceDay).where(*scope(FinanceDay, workspace_id, store_id)))
    for (day, currency), groups in days.items():
        payload = [
            {
                "nm_id": key[0],
                "barcode": key[1],
                "cost_day": key[2],
                "kind": key[3],
                "values": {field: format(value, "f") for field, value in values.items()},
            }
            for key, values in groups.items()
        ]
        cell = FinanceDay(
            workspace_id=workspace_id,
            store_id=store_id,
            day=day,
            currency=currency,
            ciphertext=vault.seal(
                json.dumps(payload, separators=(",", ":")),
                day_aad(workspace_id, store_id, day, currency),
            ),
        )
        db.add(cell)
        # Do not retain every encrypted daily payload in the SQLAlchemy session.
        db.flush()
        db.expunge(cell)
    if current is None:
        current = FinanceProjection(workspace_id=workspace_id, store_id=store_id)
        db.add(current)
    current.source_run_id, current.format_version, current.updated_at = source, FORMAT, now()
    current.legacy_date_from, current.legacy_date_to = next_window(counts, legacy)
    db.flush()
    return True
