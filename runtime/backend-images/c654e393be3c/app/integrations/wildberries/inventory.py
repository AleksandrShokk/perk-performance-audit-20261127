"""Current seller prices and FBS stocks, read-only and independently resumable."""

from app.integrations.wildberries.data import Page, Source, WBError, object_rows


def inventory_page(client, source, token, cursor):
    if source == Source.PRICES:
        offset = cursor.get("offset", 0)
        result = client.request(source, token, params={"limit": 1000, "offset": offset})
        rows = object_rows(result["data"]["listGoods"])
        if len(rows) > 1000:
            raise WBError("wb_invalid_response")
        return Page(rows, {"offset": offset + 1000}, not rows, client.cooldown_seconds)
    if "warehouses" not in cursor:
        result = object_rows(client.request(source, token))
        if len(result) > 1000:
            raise WBError("wb_size_limit")
        warehouses = []
        for row in result:
            if (
                type(row.get("id")) is not int
                or row["id"] <= 0
                or row.get("deliveryType") not in {1, 2, 3, 5, 6}
            ):
                raise WBError("wb_invalid_response")
            if row["deliveryType"] == 1:
                warehouses.append({"id": row["id"], "name": row.get("name", "")})
        return Page(
            [],
            {"warehouses": warehouses, "warehouse": 0, "offset": 0},
            not warehouses,
            client.cooldown_seconds,
        )
    sizes = cursor["_sizes"]  # Injected from the published catalog; never persisted in the cursor.
    offset = cursor.get("offset", 0)
    batch = sizes[offset : offset + 1000]
    if not batch:
        return Page([], {}, True)
    index = cursor["warehouse"]
    warehouse = cursor["warehouses"][index]
    requested = {int(row["chrt_id"]): row for row in batch}
    result = client.request(
        source, token, warehouse=warehouse["id"], body={"chrtIds": list(requested)}
    )
    rows = object_rows(result["stocks"])
    if len(rows) > len(requested):
        raise WBError("wb_invalid_response")
    amounts = {}
    for row in rows:
        chrt = row.get("chrtId")
        if type(chrt) is not int or chrt not in requested or chrt in amounts:
            raise WBError("wb_invalid_response")
        amounts[chrt] = row["amount"]
    values = [
        dict(
            nmId=int(row["nm_id"]),
            chrtId=chrt,
            warehouseId=warehouse["id"],
            warehouseName=warehouse["name"],
            quantity=amounts.get(chrt, 0),
            inWayToClient=0,
            inWayFromClient=0,
        )
        for chrt, row in requested.items()
    ]
    offset += len(batch)
    if offset >= len(sizes):
        index, offset = index + 1, 0
    return Page(
        values,
        {
            "warehouses": cursor["warehouses"],
            "warehouse": index,
            "offset": offset,
            "catalog_version": cursor.get("catalog_version"),
        },
        index >= len(cursor["warehouses"]),
        client.cooldown_seconds,
    )
