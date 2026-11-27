"""One bounded WB request per task. Publish only complete, rechecked supplies."""

from datetime import UTC, datetime, timedelta

from app.integrations.wildberries.data import Page, Source, WBError, object_rows
from app.modules.sync.normalize import integer, string
from app.modules.sync.schemas import moscow_today

PAGE_SIZE = 1000
HEADER = (
    "supplyID",
    "preorderID",
    "statusID",
    "createDate",
    "supplyDate",
    "factDate",
    "updatedDate",
)
DETAIL = (
    "statusID",
    "createDate",
    "supplyDate",
    "factDate",
    "updatedDate",
    "warehouseName",
    "warehouseID",
    "transitWarehouseName",
    "quantity",
    "acceptedQuantity",
    "readyForSaleQuantity",
    "unloadingQuantity",
)


def safe_details(value):
    if not isinstance(value, dict):
        raise WBError("wb_invalid_response")
    return {**{key: value.get(key) for key in DETAIL}, "rejected": bool(value.get("rejectReason"))}


def supply_page(client, token, cursor):
    phase = cursor.get("phase", "active")
    offset, manifest = cursor.get("offset", 0), cursor.get("manifest", [])
    if type(offset) is not int or offset < 0 or not isinstance(manifest, list):
        raise WBError("wb_invalid_cursor")
    if phase in {"active", "recent"}:
        today = moscow_today()
        rows = object_rows(
            client.request(
                Source.SUPPLIES,
                token,
                params={"limit": PAGE_SIZE, "offset": offset},
                body={
                    "statusIDs": [1, 2, 3, 4, 6] if phase == "active" else [5],
                    "dates": []
                    if phase == "active"
                    else [
                        {
                            "from": (today - timedelta(days=30)).isoformat(),
                            "till": today.isoformat(),
                            "type": "factDate",
                        }
                    ],
                },
            )
        )
        if len(rows) > PAGE_SIZE:
            raise WBError("wb_invalid_response")
        manifest = manifest + [{key: row.get(key) for key in HEADER} for row in rows]
        if len(manifest) > 10000:
            raise WBError("wb_response_too_large")
        following = (
            {"phase": phase, "offset": offset + len(rows), "manifest": manifest}
            if len(rows) == PAGE_SIZE
            else {"phase": "recent" if phase == "active" else "details", "manifest": manifest}
        )
        return Page(
            [], following, following["phase"] == "details" and not manifest, client.cooldown_seconds
        )
    if phase not in {"details", "goods", "verify"}:
        raise WBError("wb_invalid_cursor")
    index = cursor.get("index", 0)
    if type(index) is not int or not 0 <= index < len(manifest):
        raise WBError("wb_invalid_cursor")
    header = manifest[index]
    preorder = header.get("supplyID") is None
    external = header.get("preorderID") if preorder else header.get("supplyID")
    if type(external) is not int or external <= 0:
        raise WBError("wb_invalid_response")
    params = {"isPreorderID": str(preorder).lower()}
    base = {"phase": "details", "manifest": manifest, "index": index}

    def pending(**values):
        return Page([], {**base, **values}, False, client.cooldown_seconds)

    def complete(details, goods=None):
        row = {**header, "details": details, "checked_at": datetime.now(UTC).isoformat()}
        if goods is not None:
            row["goods"] = goods
        return Page(
            [row], {**base, "index": index + 1}, index + 1 == len(manifest), client.cooldown_seconds
        )

    if phase == "goods":
        rows = object_rows(
            client.request(
                Source.SUPPLIES,
                token,
                supply=external,
                supply_goods=True,
                params={**params, "limit": PAGE_SIZE, "offset": offset},
            )
        )
        if len(rows) > PAGE_SIZE:
            raise WBError("wb_invalid_response")
        goods = cursor.get("goods", [])
        seen = {row["barcode"] for row in goods}
        for row in rows:
            barcode = string(row["barcode"], 100)
            nm_id = integer(row["nmID"])
            if not barcode or not nm_id or barcode in seen:
                raise WBError("wb_invalid_response")
            seen.add(barcode)
            # If receiving has started, do not subtract anything from available stock.
            received = any(
                integer(row.get(key) or 0)
                for key in ("acceptedQuantity", "readyForSaleQuantity", "unloadingQuantity")
            )
            goods.append(
                {
                    "barcode": barcode,
                    "product_key": str(nm_id),
                    "quantity": integer(row["quantity"]),
                    "received": received,
                }
            )
        if len(goods) > 50000:
            raise WBError("wb_response_too_large")
        return pending(
            phase="goods" if len(rows) == PAGE_SIZE else "verify",
            offset=offset + len(rows),
            goods=goods,
            details=cursor["details"],
            restarts=cursor.get("restarts", 0),
        )

    details = safe_details(client.request(Source.SUPPLIES, token, supply=external, params=params))
    if phase == "verify":
        if details != cursor["details"]:
            if cursor.get("restarts", 0) >= 2:
                raise WBError("wb_invalid_response", retryable=True, retry_after=60)
            return pending(restarts=cursor.get("restarts", 0) + 1)
        goods = cursor["goods"]
        if details.get("quantity") != sum(row["quantity"] for row in goods):
            raise WBError("wb_invalid_response")
        return complete(details, goods)
    if (
        details.get("statusID") in {2, 3}
        and not details.get("factDate")
        and not details["rejected"]
    ):
        return pending(phase="goods", details=details, goods=[], restarts=cursor.get("restarts", 0))
    return complete(details)
