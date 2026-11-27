"""Native supply contents, scoped to one cabinet. No internal PERK plans are read.

Booking dates are not stock availability: apply the seller's delivery/acceptance
allowance. An overdue ETA never rolls forward to invent a new arrival date.
"""

import json
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from app.integrations.wildberries.data import Source
from app.modules.auth.dependencies import now
from app.modules.sync.read import retained, source_states

MAX_AGE = timedelta(hours=2)


@dataclass(frozen=True)
class Arrival:
    day: int
    quantity: int
    checked_at: datetime | None = field(default=None, compare=False)


class Incoming:
    def __init__(self, rows, *, current, today, lead_time_days, target_days, checked_at=None):
        self.raw = rows
        self.options = dict(
            current=current,
            today=today,
            lead_time_days=lead_time_days,
            target_days=target_days,
            checked_at=checked_at,
        )
        self.checked_at = checked_at
        self.current = current
        self.complete = current
        self.quantities = defaultdict(int)
        self.arrivals = defaultdict(list)
        for row in rows:
            if row.get("status") not in {"planned", "ready_to_ship", "shipped"}:
                continue
            # WB 'shipped' means unloaded at the gate: it may already be in stock.
            if row.get("marketplace", "wildberries") != "ozon" and row["status"] == "shipped":
                continue
            if row.get("rejected") or row.get("actual_date") or row.get("accepted_quantity"):
                continue
            if not row.get("goods_complete"):
                self.complete = False
                continue
            observed = (
                datetime.fromisoformat(row["checked_at"]) if row.get("checked_at") else checked_at
            )
            if observed and now() - observed > MAX_AGE:
                self.complete = False
                continue
            booking = date.fromisoformat(row["planned_date"]) if row.get("planned_date") else None
            arrival = (booking - today).days + lead_time_days if booking else None
            # Ozon confirms movement separately from the drop-off booking.
            # A past booking may still be within the seller's transit allowance.
            moving = row.get("marketplace") == "ozon" and row["status"] == "shipped"
            scheduled = (
                booking is not None
                and (booking >= today or moving)
                and 0 <= arrival <= lead_time_days + target_days
            )
            for good in row.get("goods", []):
                key, quantity = good["product_key"], good["quantity"]
                self.quantities[key] += quantity
                if current and scheduled:
                    self.arrivals[key].append(Arrival(arrival, quantity, observed))

    def for_warehouses(self, ids, known_warehouses=None):
        rows = [row for row in self.raw if row.get("warehouse_id") in ids]
        result = Incoming(rows, **self.options)
        result.complete &= not any(
            not row.get("warehouse_id")
            and row.get("status") in {"planned", "ready_to_ship", "shipped"}
            for row in self.raw
        )
        if known_warehouses is not None:
            result.complete &= not any(
                row.get("warehouse_id") not in known_warehouses
                and row.get("status") in {"planned", "ready_to_ship", "shipped"}
                for row in self.raw
            )
        return result

    def quantity(self, keys):
        if not self.complete:
            return None
        return sum(self.quantities[key] for key in keys)

    def events(self, keys, stock_updated_at=None):
        # An older supply list could include goods already present in newer stock.
        return [
            event
            for key in keys
            for event in self.arrivals[key]
            if stock_updated_at is None
            or (event.checked_at is not None and event.checked_at >= stock_updated_at)
        ]


def read(db, vault, workspace_id, store, *, today, lead_time_days, target_days, warehouse_ids=None):
    rows, stamp = [], None
    if store.marketplace == "ozon":
        from app.modules.insights.extra_jobs import aad
        from app.modules.insights.extra_models import MarketplaceSupplySnapshot

        snapshot = db.get(MarketplaceSupplySnapshot, (workspace_id, store.id))
        if snapshot:
            stamp = snapshot.updated_at
            rows = json.loads(
                vault.open(snapshot.ciphertext, aad(workspace_id, store.id, "supplies"))
            )["items"]
    else:
        state = source_states(db, workspace_id, store.id, [Source.SUPPLIES])[Source.SUPPLIES]
        if state.success:
            # Individual supplies carry their own verification time during a long import.
            stamp = state.success.finished_at
            rows = list(retained(db, vault, workspace_id, store.id, Source.SUPPLIES))
    unmapped = False
    if warehouse_ids is not None:
        unmapped = any(
            not row.get("warehouse_id")
            and row.get("status") in {"planned", "ready_to_ship", "shipped"}
            for row in rows
        )
        rows = [row for row in rows if row.get("warehouse_id") in warehouse_ids]
    result = Incoming(
        rows,
        current=stamp is not None and now() - stamp <= MAX_AGE,
        today=today,
        lead_time_days=lead_time_days,
        target_days=target_days,
        checked_at=stamp,
    )

    result.complete &= not unmapped
    return result
