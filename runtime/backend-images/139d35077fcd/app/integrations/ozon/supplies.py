"""Read FBO orders and their quantities. Never create or modify a marketplace supply."""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.integrations.ozon.transport import OzonImportError, SellerReader

COUNTER = "/v1/supply-order/status/counter"
LIST = "/v3/supply-order/list"
GET = "/v3/supply-order/get"
BUNDLE = "/v1/supply-order/bundle"
TERMINAL = {"COMPLETED", "CANCELLED", "REJECTED_AT_SUPPLY_WAREHOUSE"}
STATES = {
    "DATA_FILLING": "draft",
    "READY_TO_SUPPLY": "ready_to_ship",
    "ACCEPTED_AT_SUPPLY_WAREHOUSE": "shipped",
    "IN_TRANSIT": "shipped",
    "ACCEPTANCE_AT_STORAGE_WAREHOUSE": "accepting",
    "REPORTS_CONFIRMATION_AWAITING": "accepting",
    "REPORT_REJECTED": "accepting",
    "COMPLETED": "accepted",
    "CANCELLED": "cancelled",
    "REJECTED_AT_SUPPLY_WAREHOUSE": "cancelled",
}


def day(value, timezone="Europe/Moscow"):
    return (
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        .astimezone(ZoneInfo(timezone))
        .date()
        .isoformat()
        if value
        else None
    )


class SupplyClient(SellerReader):
    allowed_methods = frozenset({COUNTER, LIST, GET, BUNDLE})

    def __init__(self, *args, checkpoint=None, **options):
        super().__init__(*args, **options)
        self.checkpoint = checkpoint

    def orders(self, states):
        cursor, seen = "", set()
        while True:
            data = self.read(
                LIST,
                {
                    "filter": {"states": states},
                    "limit": 100,
                    "sort_by": "ORDER_CREATION",
                    "sort_dir": "DESC",
                    "last_id": cursor,
                },
            )
            ids = data.get("order_ids")
            next_id = data.get("last_id", "")
            if not isinstance(ids, list) or len(ids) > 100 or not isinstance(next_id, str):
                raise ValueError("list")
            if not ids:
                return
            if any(isinstance(v, bool) or not isinstance(v, int) or v <= 0 for v in ids):
                raise ValueError("id")
            if len(seen) + len(ids) > 5000:
                raise OzonImportError("ozon_import_limit")
            if set(ids) & seen:
                raise ValueError("duplicate order")
            seen.update(ids)
            for offset in range(0, len(ids), 50):
                rows = self.read(GET, {"order_ids": ids[offset : offset + 50]}).get("orders")
                if not isinstance(rows, list) or {row["order_id"] for row in rows} != set(
                    ids[offset : offset + 50]
                ):
                    raise ValueError("details")
                yield rows
            if not next_id or len(ids) < 100:
                return
            if next_id == cursor:
                raise ValueError("cursor")
            cursor = next_id

    def goods(self, bundle):
        last, seen, result = "", set(), []
        while True:
            data = self.read(BUNDLE, {"bundle_ids": [bundle], "limit": 100, "last_id": last})
            rows = data.get("items")
            more = data.get("has_next")
            if not isinstance(rows, list) or len(rows) > 100 or not isinstance(more, bool):
                raise ValueError("bundle")
            for row in rows:
                sku, qty = row["sku"], row["quantity"]
                if (
                    isinstance(sku, bool)
                    or not isinstance(sku, int)
                    or sku <= 0
                    or sku in seen
                    or isinstance(qty, bool)
                    or not isinstance(qty, int)
                    or qty < 0
                ):
                    raise ValueError("quantity")
                seen.add(sku)
                result.append({"product_key": str(sku), "quantity": qty})
            if len(seen) > 50000:
                raise OzonImportError("ozon_import_limit")
            if not more:
                return result
            next_id = data.get("last_id")
            if not rows or not next_id or next_id == last:
                raise ValueError("cursor")
            last = next_id

    def snapshot(self, today, previous=None):
        """All active orders and the last 180 days of completed/cancelled orders."""
        try:
            with self:
                counts = self.read(COUNTER, {})["items"]
                states = [
                    row["order_state"].removeprefix("ORDER_STATE_")
                    for row in counts
                    if row["count"] > 0 and row["order_state"] != "ORDER_STATE_UNSPECIFIED"
                ]
                orders = []
                for selected in (
                    [s for s in states if s not in TERMINAL],
                    [s for s in states if s in TERMINAL],
                ):
                    if not selected:
                        continue
                    for rows in self.orders(selected):
                        recent = [
                            row
                            for row in rows
                            if row["state"] not in TERMINAL
                            or date.fromisoformat(day(row["created_date"]))
                            >= today - timedelta(days=180)
                        ]
                        orders.extend(recent)
                        if len(recent) < len(rows) and all(s in TERMINAL for s in selected):
                            break
                old = {row["external_id"]: row for row in (previous or {}).get("items", [])}
                result = []
                progress = self.checkpoint.load([str(today)]) if self.checkpoint else {"rows": []}
                resumed = {row["external_id"]: row for row in progress["rows"]}
                seen = set()
                for order in orders:
                    for supply in order["supplies"] or [{}]:
                        external = f"ozon:{order['order_id']}:{supply.get('supply_id', 'draft')}"
                        if external in seen:
                            raise ValueError("duplicate supply")
                        seen.add(external)
                        state = order["state"]
                        cached = resumed.get(external) or old.get(external)
                        # Reuse immutable content only while Ozon's update marker and bundle match.
                        marker = order["state_updated_date"]
                        bundle = supply.get("bundle_id")
                        cached_current = bool(
                            cached
                            and cached.get("goods_complete") is True
                            and isinstance(cached.get("goods"), list)
                            and cached.get("source_updated_at") == marker
                            and cached.get("bundle_id") == bundle
                            and (external in resumed or state in TERMINAL)
                            and cached.get("checked_at")
                            and (
                                datetime.now().astimezone()
                                - datetime.fromisoformat(cached["checked_at"])
                            ).total_seconds()
                            < 21600
                        )
                        goods = (
                            cached["goods"]
                            if cached_current
                            else self.goods(bundle)
                            if bundle
                            else []
                        )
                        qty = sum(row["quantity"] for row in goods) if bundle else None
                        warehouse = supply.get("storage_warehouse") or {}
                        destination = warehouse.get("name") or (
                            f"Кластер {supply['macrolocal_cluster_id']}"
                            if supply.get("macrolocal_cluster_id")
                            else ""
                        )
                        timeslot = (order.get("timeslot") or {}).get("timeslot") or {}
                        result.append(
                            {
                                "external_id": external,
                                "marketplace": "ozon",
                                "display_number": order["order_number"],
                                "supply_id": str(supply["supply_id"])
                                if supply.get("supply_id")
                                else None,
                                "preorder_id": str(order["order_id"]),
                                "status": STATES.get(state, "unknown"),
                                "native_status": state,
                                "planned_date": day(
                                    timeslot.get("from"),
                                    (order.get("timeslot") or {})
                                    .get("timezone_info", {})
                                    .get("iana_name")
                                    or "Europe/Moscow",
                                ),
                                "created_date": day(order["created_date"]),
                                "actual_date": None,
                                "destination": destination,
                                "warehouse_id": str(warehouse["warehouse_id"])
                                if warehouse.get("warehouse_id") is not None
                                else None,
                                "quantity": qty,
                                "goods": goods,
                                "goods_complete": bool(bundle),
                                "accepted_quantity": None,
                                "rejected": state == "REJECTED_AT_SUPPLY_WAREHOUSE",
                                "source_updated_at": marker,
                                "bundle_id": bundle,
                                "checked_at": cached["checked_at"]
                                if cached_current
                                else datetime.now().astimezone().isoformat(),
                            }
                        )
                        if self.checkpoint and len(result) % 10 == 0:
                            self.checkpoint.save({"completed": [], "rows": result})
                return {"items": result, "history_days": 180}
        except KeyError, TypeError, ValueError, ArithmeticError:
            raise OzonImportError("ozon_invalid_response") from None
