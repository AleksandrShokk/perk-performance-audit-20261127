"""Current cursor APIs for order-date cohorts and native 28-day FBO stock cover."""

from datetime import datetime, time, timedelta
from time import sleep
from zoneinfo import ZoneInfo

from app.integrations.ozon.transport import OzonImportError, SellerReader

FBO = "/v3/posting/fbo/list"
FBS = "/v4/posting/fbs/list"
RETURNS = "/v1/returns/list"
STOCK_COVER = "/v1/analytics/stocks"
MOSCOW = ZoneInfo("Europe/Moscow")
MAX_ROWS = 200000


def boundaries(start, end):
    return {
        "since": datetime.combine(start, time.min, MOSCOW).isoformat(),
        "to": (
            datetime.combine(end + timedelta(days=1), time.min, MOSCOW) - timedelta(microseconds=1)
        ).isoformat(),
    }


class OperationsClient(SellerReader):
    allowed_methods = frozenset({FBO, FBS, RETURNS, STOCK_COVER})

    def __init__(
        self, client_id, api_key, *, checkpoint=None, pause=sleep, price_checkpoint=None, **options
    ):
        super().__init__(client_id, api_key, **options)
        self.checkpoint, self.pause = checkpoint, pause
        self.price_checkpoint = price_checkpoint

    def postings(self, path, start, end):
        token, seen, count = "", set(), 0
        while True:
            data = self.read(
                path,
                {
                    "cursor": token,
                    "filter": boundaries(start, end),
                    "limit": 100,
                    "sort_dir": "ASC",
                    "with": {"analytics_data": False, "financial_data": True, "legal_info": False},
                },
            )
            rows, more = data.get("postings"), data.get("has_next")
            if not isinstance(rows, list) or not isinstance(more, bool):
                raise OzonImportError("ozon_invalid_response")
            count += len(rows)
            if count > MAX_ROWS:
                raise OzonImportError("ozon_import_limit")
            yield from rows
            if not more:
                return
            cursor = data.get("cursor")
            if (
                not rows
                or not isinstance(cursor, str)
                or not cursor
                or cursor == token
                or cursor in seen
            ):
                raise OzonImportError("ozon_cursor_repeated")
            seen.add(cursor)
            token = cursor

    def returns(self, posting_numbers):
        # The documented filter accepts at most 50 posting numbers.
        for offset in range(0, len(posting_numbers), 50):
            token, seen, count = 0, set(), 0
            while True:
                data = self.read(
                    RETURNS,
                    {
                        "filter": {"posting_numbers": posting_numbers[offset : offset + 50]},
                        "limit": 500,
                        "last_id": token,
                    },
                )
                rows, more = data.get("returns"), data.get("has_next")
                if not isinstance(rows, list) or not isinstance(more, bool):
                    raise OzonImportError("ozon_invalid_response")
                count += len(rows)
                if count > MAX_ROWS:
                    raise OzonImportError("ozon_import_limit")
                yield from rows
                if not more:
                    break
                next_id = rows[-1].get("id") if rows else None
                if not isinstance(next_id, int) or next_id <= token or next_id in seen:
                    raise OzonImportError("ozon_cursor_repeated")
                seen.add(next_id)
                token = next_id

    def sales(self, start, end, normalize_posting, normalize_return, progress=lambda count: None):
        """PII fields are discarded immediately; only normalized facts leave this method."""
        postings, seen = [], set()
        try:
            with self:
                for path, channel in ((FBO, "fbo"), (FBS, "fbs")):
                    for raw in self.postings(path, start, end):
                        row = normalize_posting(raw, channel)
                        if row is None:
                            continue
                        key = row["number"]
                        if key in seen:
                            raise OzonImportError("ozon_duplicate_posting")
                        seen.add(key)
                        # Both providers' list filters refer to this same cohort timestamp.
                        if not start <= row["day"] <= end:
                            raise OzonImportError("ozon_wrong_period")
                        postings.append(row)
                        if len(postings) % 100 == 0:
                            progress(len(postings))
                from app.integrations.ozon.order_prices import OrderPrices

                with OrderPrices(
                    self.headers["Client-Id"],
                    self.headers["Api-Key"],
                    transport=self.transport,
                    wait=self.wait,
                    pause=self.pause,
                    checkpoint=self.price_checkpoint,
                ) as prices:
                    prices.enrich(postings, start, end, f"{start}:{end}")
                returned = {}
                for raw in self.returns(sorted(seen)):
                    row = normalize_return(raw)
                    if row["number"] not in seen:
                        raise OzonImportError("ozon_wrong_return")
                    if row["id"] in returned and returned[row["id"]] != row:
                        raise OzonImportError("ozon_duplicate_return")
                    returned[row["id"]] = row
                progress(len(postings))
                return postings, list(returned.values())
        except KeyError, TypeError, ValueError, ArithmeticError:
            raise OzonImportError("ozon_invalid_response") from None

    def stock_cover(self, skus):
        state = self.checkpoint.load(skus) if self.checkpoint else {"completed": [], "rows": []}
        if state.get("format") != 2:
            state = {"completed": [], "rows": [], "format": 2}
        completed = set(state["completed"])
        remaining = [sku for sku in skus if sku not in completed]
        with self:
            for offset in range(0, len(remaining), 100):
                if offset:
                    self.pause(2)
                selected = remaining[offset : offset + 100]
                rows = self.read(STOCK_COVER, {"skus": selected}).get("items")
                if not isinstance(rows, list) or any(
                    str(row.get("sku")) not in selected for row in rows
                ):
                    raise OzonImportError("ozon_invalid_response")
                # Store only calculation facts; omit names and all unrelated provider data.
                state["rows"].extend(
                    {
                        key: row.get(key)
                        for key in (
                            "sku",
                            "warehouse_id",
                            "cluster_id",
                            "placement_zone",
                            "available_stock_count",
                            "ads",
                            "ads_cluster",
                            "cluster_name",
                            "idc",
                            "turnover_grade",
                        )
                    }
                    for row in rows
                )
                completed.update(selected)
                state["completed"] = sorted(completed)
                if len(state["rows"]) > MAX_ROWS:
                    raise OzonImportError("ozon_import_limit")
                if self.checkpoint:
                    self.checkpoint.save(state)
        return state["rows"]
