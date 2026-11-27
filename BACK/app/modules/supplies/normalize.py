"""Retain only identifiers, dates, status and quantities, never phones or costs."""

from datetime import date

from app.integrations.wildberries.data import WBError
from app.modules.sync.normalize import integer, string

STATUSES = {
    1: "draft",
    2: "planned",
    3: "ready_to_ship",
    4: "accepting",
    5: "accepted",
    6: "shipped",
}


def normalize_supply(row):
    details = row["details"]
    status = STATUSES.get(integer(details["statusID"]))
    if status is None:
        raise WBError("wb_invalid_record")
    supply = str(integer(row["supplyID"])) if row.get("supplyID") is not None else None
    preorder = str(integer(row["preorderID"])) if row.get("preorderID") is not None else None
    if not supply and not preorder:
        raise WBError("wb_invalid_record")
    identity = "p:" + preorder if preorder else "s:" + supply

    def day(key):
        value = details.get(key) or row.get(key)
        return date.fromisoformat(string(value, 64)[:10]).isoformat() if value else None

    return identity, {
        "external_id": identity,
        "supply_id": supply,
        "preorder_id": preorder,
        "status": status,
        "planned_date": day("supplyDate"),
        "actual_date": day("factDate"),
        "created_date": day("createDate"),
        "destination": string(
            details.get("transitWarehouseName") or details.get("warehouseName") or ""
        ),
        "warehouse_id": str(integer(details["warehouseID"]))
        if details.get("warehouseID") is not None
        else None,
        "quantity": integer(details["quantity"]) if details.get("quantity") is not None else None,
        "accepted_quantity": integer(details["acceptedQuantity"])
        if details.get("acceptedQuantity") is not None
        else None,
        "rejected": bool(details.get("rejectReason") or details.get("rejected")),
        "checked_at": string(row["checked_at"], 64) if row.get("checked_at") else None,
        "goods_complete": "goods" in row
        and not any(good["received"] for good in row.get("goods", []))
        and not any(
            details.get(key)
            for key in ("acceptedQuantity", "readyForSaleQuantity", "unloadingQuantity")
        ),
        "goods": [
            {"product_key": string(good["product_key"], 100), "quantity": integer(good["quantity"])}
            for good in row.get("goods", [])
        ],
    }
