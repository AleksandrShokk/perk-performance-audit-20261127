"""The WB stock-history report already contains past orders and time out of stock.

One rolling report, not 28 days of local observations. The current stock and
historical demand use the same product and warehouse scope (FBO + FBS).
"""

from app.integrations.wildberries.data import Page, Source, WBError, object_rows

PAGE_SIZE = 1000


def history_page(client, token, cursor, start, end, *, source=Source.STOCK_HISTORY, stock_type=""):
    offset = cursor.get("offset", 0)
    if type(offset) is not int or offset < 0 or start is None or end is None or start > end:
        raise WBError("wb_invalid_cursor")
    result = client.request(
        source,
        token,
        body={
            "nmIDs": [],
            "currentPeriod": {"start": start.isoformat(), "end": end.isoformat()},
            "stockType": stock_type,
            "skipDeletedNm": False,
            "orderBy": {"field": "avgOrders", "mode": "asc"},
            "availabilityFilters": [],
            "limit": PAGE_SIZE,
            "offset": offset,
        },
    )
    items = object_rows(result["data"]["items"])
    if len(items) > PAGE_SIZE or len({item.get("nmID") for item in items}) != len(items):
        raise WBError("wb_invalid_response")
    # Period metadata comes from our request, never from an untrusted provider row.
    rows = [
        {**item, "periodStart": start.isoformat(), "periodEnd": end.isoformat()} for item in items
    ]
    return Page(
        rows, {"offset": offset + len(items)}, len(items) < PAGE_SIZE, client.cooldown_seconds
    )
