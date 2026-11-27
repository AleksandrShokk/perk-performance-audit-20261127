"""Returns of goods to the seller (WB "returns and item movement" report).

Two views from the same records:
  period  — returns that became ready for pickup in the period (order date when WB gives
            no readiness date), by type, status and SKU;
  pickup  — current state, independent of the period: items ready at a pickup point and
            not collected yet, soonest storage expiry first. After expiry WB may dispose
            of the item, so this list is the actionable part.
Days outside completed imports make the period partial; nothing is invented.
"""

import json
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta

from sqlalchemy import select

from app.db.tenant import scope
from app.integrations.wildberries.data import Source
from app.modules.insights.funnel import known_days
from app.modules.sync.analytics import coverage, record_context
from app.modules.sync.models import SyncRun, WBRecord
from app.modules.sync.schemas import moscow_today

PRODUCT_LIMIT = 500
PICKUP_LIMIT = 200
EXPIRING_DAYS = 3


def day_of(value):
    try:
        return date.fromisoformat(value[:10]) if value else None
    except ValueError:
        return None


def records(db, vault, workspace_id, store_id):
    rows = db.execute(
        select(WBRecord.record_key, WBRecord.ciphertext)
        .where(*scope(WBRecord, workspace_id, store_id), WBRecord.source == Source.RETURNS)
        .execution_options(yield_per=500)
    )
    for key, ciphertext in rows:
        aad = record_context(workspace_id, store_id, Source.RETURNS, key)
        yield json.loads(vault.open(ciphertext, aad))


def report(db, vault, workspace_id, store_id, start, end):
    today = moscow_today()
    known = known_days(coverage(db, workspace_id, store_id)[Source.RETURNS], start, end)
    by_type, by_status = Counter(), Counter()
    per_product = defaultdict(lambda: {"returns": 0, "types": Counter()})
    daily = Counter()
    total, in_transit = 0, 0
    pickup = []
    for item in records(db, vault, workspace_id, store_id):
        ready = day_of(item.get("ready_at"))
        event = ready or day_of(item.get("order_date"))
        if not item.get("completed_at"):
            if ready:
                expires = day_of(item.get("expires_at"))
                pickup.append(
                    {
                        "nm_id": item["nm_id"],
                        "barcode": item["barcode"],
                        "size": item["size"],
                        "return_type": item["return_type"],
                        "return_status": item["return_status"],
                        "ready_on": ready.isoformat(),
                        "expires_on": expires.isoformat() if expires else None,
                        "days_left": (expires - today).days if expires else None,
                        "office_address": item["office_address"],
                    }
                )
            else:
                in_transit += 1
        if event is None or not start <= event <= end or event not in known:
            continue
        total += 1
        daily[event] += 1
        by_type[item["return_type"] or "unknown"] += 1
        by_status[item["return_status"] or "unknown"] += 1
        product = per_product[item["nm_id"]]
        product["returns"] += 1
        product["types"][item["return_type"] or "unknown"] += 1
    pickup.sort(key=lambda row: (row["days_left"] is None, row["days_left"] or 0, row["nm_id"]))
    span = (end - start).days + 1
    as_of = db.scalar(
        select(SyncRun.finished_at)
        .where(
            *scope(SyncRun, workspace_id, store_id),
            SyncRun.source == Source.RETURNS,
            SyncRun.status == "succeeded",
        )
        .order_by(SyncRun.finished_at.desc())
        .limit(1)
    )
    ranked = sorted(per_product.items(), key=lambda item: (-item[1]["returns"], item[0]))
    days_left = [row["days_left"] for row in pickup if row["days_left"] is not None]
    return {
        "status": "ready" if len(known) == span else "partial" if known else "no_data",
        "period_days": span,
        "known_days": len(known),
        "as_of": as_of.isoformat() if isinstance(as_of, datetime) else None,
        "date_basis": "ready_for_pickup",
        "totals": {"returns": total if known else None},
        "by_type": [{"name": name, "count": count} for name, count in by_type.most_common()],
        "by_status": [{"name": name, "count": count} for name, count in by_status.most_common()],
        "daily": [
            {
                "day": (start + timedelta(days=offset)).isoformat(),
                "returns": daily[start + timedelta(days=offset)]
                if start + timedelta(days=offset) in known
                else None,
            }
            for offset in range(span)
        ],
        "products": [
            {
                "nm_id": nm_id,
                "returns": values["returns"],
                "types": [{"name": n, "count": c} for n, c in values["types"].most_common()],
            }
            for nm_id, values in ranked[:PRODUCT_LIMIT]
        ],
        "products_truncated": len(ranked) > PRODUCT_LIMIT,
        "pickup": {
            "awaiting": len(pickup),
            "expiring_soon": sum(1 for left in days_left if 0 <= left <= EXPIRING_DAYS),
            "expired": sum(1 for left in days_left if left < 0),
            "in_transit": in_transit,
            "items": pickup[:PICKUP_LIMIT],
            "items_truncated": len(pickup) > PICKUP_LIMIT,
        },
    }
