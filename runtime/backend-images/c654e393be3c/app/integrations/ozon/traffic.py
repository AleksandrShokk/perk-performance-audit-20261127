"""Native daily SKU traffic, with resumable pages under Ozon's one-minute quota."""

from datetime import date, timedelta
from decimal import Decimal

from app.integrations.ozon.transport import OzonImportError, SellerReader

PATH = "/v1/analytics/data"
METRICS = ("hits_view", "hits_view_pdp", "hits_tocart")
FIELDS = ("impressions", "opens", "carts")
PAGE_SIZE = 1000
MAX_ROWS = 200000


class TrafficClient(SellerReader):
    allowed_methods = frozenset({PATH})

    def __init__(self, *args, checkpoint=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.checkpoint = checkpoint

    def days(self, start, end):
        state = (
            self.checkpoint.load([str(start), str(end), "traffic-v2"])
            if self.checkpoint
            else {"completed": [], "rows": []}
        )
        seen = {(row["day"], row["sku"]) for row in state["rows"]}
        with self:
            while not state.get("done"):
                offset = len(state["rows"])
                if offset >= MAX_ROWS:
                    raise OzonImportError("ozon_response_too_large")
                value = self.read(
                    PATH,
                    {
                        "date_from": str(start),
                        "date_to": str(end),
                        "metrics": list(METRICS),
                        "dimension": ["sku", "day"],
                        "filters": [],
                        "sort": [],
                        "limit": PAGE_SIZE,
                        "offset": offset,
                    },
                )
                try:
                    rows = value["result"]["data"]
                    if not isinstance(rows, list) or len(rows) > PAGE_SIZE:
                        raise ValueError("rows")
                    parsed = []
                    for row in rows:
                        sku, day = (
                            row["dimensions"][0]["id"],
                            date.fromisoformat(row["dimensions"][1]["id"]),
                        )
                        metrics = row["metrics"]
                        if (
                            not isinstance(sku, str)
                            or not sku.isdecimal()
                            or not 0 < len(sku) <= 32
                            or not start <= day <= end
                            or (str(day), sku) in seen
                        ):
                            raise ValueError("identity")
                        if len(metrics) != len(FIELDS) or any(
                            isinstance(v, bool)
                            or not isinstance(v, (int, Decimal))
                            or v < 0
                            or v != int(v)
                            for v in metrics
                        ):
                            raise ValueError("counter")
                        seen.add((str(day), sku))
                        parsed.append(
                            {
                                "day": str(day),
                                "sku": sku,
                                **dict(zip(FIELDS, map(int, metrics), strict=True)),
                            }
                        )
                    totals = value["result"].get("totals")
                    if totals is not None and (
                        len(totals) != len(FIELDS)
                        or any(
                            isinstance(v, bool)
                            or not isinstance(v, (int, Decimal))
                            or v < 0
                            or v != int(v)
                            for v in totals
                        )
                    ):
                        raise ValueError("totals")
                    if offset == 0 and totals is not None:
                        state["totals"] = list(map(int, totals))
                except KeyError, IndexError, TypeError, ValueError, ArithmeticError:
                    raise OzonImportError("ozon_invalid_response") from None
                state["rows"].extend(parsed)
                state["completed"].append(offset)
                state["done"] = len(rows) < PAGE_SIZE
                # Save before requesting another page: a 429 must never restart page one.
                if self.checkpoint:
                    self.checkpoint.save(state)
        if (
            state.get("totals") is not None
            and [sum(row[field] for row in state["rows"]) for field in FIELDS] != state["totals"]
        ):
            if self.checkpoint:
                self.checkpoint.clear()
            raise OzonImportError("ozon_invalid_response")
        result = {
            start + timedelta(days=index): {
                **dict.fromkeys(FIELDS, 0),
                "products": {},
                "version": 2,
            }
            for index in range((end - start).days + 1)
        }
        for row in state["rows"]:
            values = {field: row[field] for field in FIELDS}
            target = result[date.fromisoformat(row["day"])]
            target["products"][row["sku"]] = values
            for field in FIELDS:
                target[field] += values[field]
        return result
