"""Read-only, bounded WB data transport. No arbitrary URLs or upstream errors escape."""

import json
import math
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from email.utils import parsedate_to_datetime
from enum import StrEnum

import httpx

from app.modules.finance.fields import AMOUNT_FIELDS, REFERENCE_FIELDS


class Source(StrEnum):
    CATALOG = "catalog"
    SALES = "sales"
    STOCKS = "stocks"
    FINANCE = "finance"
    ORDERS = "orders"
    FUNNEL = "funnel"
    RETURNS = "returns"
    BALANCE = "balance"
    PRICES = "prices"
    FBS = "fbs"
    STOCK_HISTORY = "stock_history"
    SUPPLY_DEMAND = "supply_demand"
    SUPPLY_DEMAND_FBS = "fbs_demand"
    SUPPLIES = "supplies"


# Statistics reports read by change date (lastChangeDate), kept by WB for 90 days.
CHANGE_FEEDS = frozenset({Source.SALES, Source.ORDERS})
# Sources with a business-date period (as opposed to current snapshots).
DATED = frozenset({Source.SALES, Source.ORDERS, Source.FINANCE, Source.FUNNEL, Source.RETURNS})
# Sources aggregated into encrypted daily metrics.
METRIC_SOURCES = frozenset({Source.SALES, Source.ORDERS, Source.FINANCE, Source.FUNNEL})
SCOPES = {
    Source.CATALOG: "content",
    Source.STOCK_HISTORY: "analytics",
    Source.SUPPLY_DEMAND: "analytics",
    Source.SUPPLY_DEMAND_FBS: "analytics",
    Source.SUPPLIES: "supplies",
    Source.PRICES: "prices",
    Source.FBS: "marketplace",
    Source.SALES: "statistics",
    Source.ORDERS: "statistics",
    Source.STOCKS: "analytics",
    Source.FINANCE: "finance",
    Source.FUNNEL: "analytics",
    Source.RETURNS: "analytics",
    Source.BALANCE: "finance",
}
INTERVALS = {
    Source.CATALOG: 1,
    Source.STOCK_HISTORY: 21,
    Source.SUPPLY_DEMAND: 21,
    Source.SUPPLY_DEMAND_FBS: 21,
    Source.SUPPLIES: 3,
    Source.PRICES: 1,
    Source.FBS: 1,
    Source.SALES: 61,
    Source.ORDERS: 61,
    Source.STOCKS: 21,
    Source.FINANCE: 61,
    # 3 requests per minute, one every 20 seconds.
    Source.FUNNEL: 21,
    Source.RETURNS: 61,
    Source.BALANCE: 61,
}
ENDPOINTS = {
    Source.SUPPLY_DEMAND_FBS: (
        "POST",
        "https://seller-analytics-api.wildberries.ru/api/v2/stocks-report/products/products",
    ),
    Source.SUPPLY_DEMAND: (
        "POST",
        "https://seller-analytics-api.wildberries.ru/api/v2/stocks-report/products/products",
    ),
    Source.SUPPLIES: ("POST", "https://supplies-api.wildberries.ru/api/v1/supplies"),
    Source.STOCK_HISTORY: (
        "POST",
        "https://seller-analytics-api.wildberries.ru/api/v2/stocks-report/products/products",
    ),
    Source.PRICES: ("GET", "https://discounts-prices-api.wildberries.ru/api/v2/list/goods/filter"),
    Source.FBS: ("GET", "https://marketplace-api.wildberries.ru/api/v3/warehouses"),
    Source.BALANCE: ("GET", "https://finance-api.wildberries.ru/api/v1/account/balance"),
    Source.CATALOG: ("POST", "https://content-api.wildberries.ru/content/v2/get/cards/list"),
    Source.SALES: ("GET", "https://statistics-api.wildberries.ru/api/v1/supplier/sales"),
    Source.ORDERS: ("GET", "https://statistics-api.wildberries.ru/api/v1/supplier/orders"),
    Source.STOCKS: (
        "POST",
        "https://seller-analytics-api.wildberries.ru/api/analytics/v1/stocks-report/wb-warehouses",
    ),
    Source.FINANCE: (
        "POST",
        "https://finance-api.wildberries.ru/api/finance/v1/sales-reports/detailed",
    ),
    Source.FUNNEL: (
        "POST",
        "https://seller-analytics-api.wildberries.ru/api/analytics/v3/sales-funnel/products",
    ),
    Source.RETURNS: (
        "GET",
        "https://seller-analytics-api.wildberries.ru/api/analytics/v1/item-returns",
    ),
}
FUNNEL_PAGE_SIZE = 1000
FUNNEL_COUNTERS = ("openCount", "cartCount", "orderCount", "buyoutCount", "cancelCount")
RETURNS_PAGE_SIZE = 1000
RETURNS_WINDOW_DAYS = 31
FINANCE_FIELDS = [
    "rrdId",
    "reportId",
    "nmId",
    "docTypeName",
    "sellerOperName",
    "quantity",
    "rrDate",
    "currency",
    *AMOUNT_FIELDS.values(),
    *(field for field, _ in REFERENCE_FIELDS.values()),
]
MAX_BYTES = 64 * 1024 * 1024
STOCK_PAGE_SIZE = 10000
FINANCE_PAGE_SIZE = 100000
INITIAL_FINANCE_PAGE_SIZE = 1000
MAX_FINANCE_PAGE_SIZE = 100000


class WBError(Exception):
    def __init__(self, code: str, *, retryable: bool = False, retry_after: int = 0):
        super().__init__(code)
        self.code, self.retryable, self.retry_after = code, retryable, retry_after


@dataclass(frozen=True)
class Page:
    rows: list[dict]
    cursor: dict
    complete: bool
    cooldown_seconds: int = 0


def retry_seconds(headers: httpx.Headers) -> int:
    delays = [61]
    # Reset replenishes the whole burst, not the time until the next allowed request.
    names = ["Retry-After", "X-Ratelimit-Retry"]
    if not any(headers.get(name) for name in names):
        names.append("X-Ratelimit-Reset")
    for name in names:
        value = headers.get(name, "")
        try:
            seconds = float(value)
            if math.isfinite(seconds) and seconds >= 0:
                delays.append(math.ceil(seconds))
        except ValueError:
            if name == "Retry-After" and value:
                try:
                    delays.append(
                        math.ceil(
                            (parsedate_to_datetime(value) - datetime.now(UTC)).total_seconds()
                        )
                    )
                except TypeError, ValueError, OverflowError:
                    pass
    # Unreasonably long limits fail closed instead of retrying sooner than instructed.
    if max(delays) > 86400:
        raise WBError("wb_retry_window_unsupported")
    return max(delays)


def success_cooldown(headers: httpx.Headers) -> int:
    if headers.get("X-Ratelimit-Remaining") != "0":
        return 0
    return retry_seconds(headers)


def object_rows(value) -> list[dict]:
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise WBError("wb_invalid_response")
    return value


class WBDataClient:
    def __init__(self, transport=None):
        self.transport = transport
        self.cooldown_deadline = 0
        self.response_bytes = 0

    @property
    def cooldown_seconds(self):
        # WB headers describe the wait from receipt, not after downloading the body.
        return max(0, math.ceil(self.cooldown_deadline - time.monotonic()))

    def request(
        self,
        source: Source,
        token: str,
        *,
        body=None,
        params=None,
        catalog_subject=None,
        warehouse=None,
        supply=None,
        supply_goods=False,
        stock_detail=None,
    ):
        self.cooldown_deadline = 0
        self.response_bytes = 0
        method, url = ENDPOINTS[source]
        if catalog_subject is not None:
            if (
                source != Source.CATALOG
                or not str(catalog_subject).isdigit()
                or len(str(catalog_subject)) > 10
            ):
                raise WBError("wb_invalid_subject")
            method, url = (
                "GET",
                f"https://content-api.wildberries.ru/content/v2/object/charcs/{catalog_subject}",
            )

        if warehouse is not None:
            if source != Source.FBS or type(warehouse) is not int or warehouse <= 0:
                raise WBError("wb_invalid_warehouse")
            method, url = (
                "POST",
                f"https://marketplace-api.wildberries.ru/api/v3/stocks/{warehouse}",
            )
        if supply is not None:
            if source != Source.SUPPLIES or type(supply) is not int or supply <= 0:
                raise WBError("wb_invalid_supply")
            method, url = "GET", f"https://supplies-api.wildberries.ru/api/v1/supplies/{supply}"
        if supply_goods:
            if supply is None or source != Source.SUPPLIES:
                raise WBError("wb_invalid_supply")
            url += "/goods"
        if stock_detail is not None:
            if source != Source.SUPPLY_DEMAND or type(stock_detail) is not int or stock_detail <= 0:
                raise WBError("wb_invalid_record")
            method, url = (
                "POST",
                "https://seller-analytics-api.wildberries.ru/api/v2/stocks-report/products/sizes",
            )
        started = time.monotonic()
        try:
            with httpx.Client(
                timeout=httpx.Timeout(20, connect=5),
                follow_redirects=False,
                trust_env=False,
                transport=self.transport,
            ) as client:
                with client.stream(
                    method, url, headers={"Authorization": token}, json=body, params=params
                ) as response:
                    status = response.status_code
                    if status == 429:
                        raise WBError(
                            "wb_rate_limited",
                            retryable=True,
                            retry_after=retry_seconds(response.headers),
                        )
                    if status == 401:
                        raise WBError("wb_token_rejected")
                    if status == 403:
                        raise WBError("wb_access_denied")
                    if status == 402:
                        raise WBError("wb_subscription_required")
                    if status >= 500:
                        raise WBError("wb_unavailable", retryable=True)
                    if status == 204 and source in {Source.STOCKS, Source.FINANCE, Source.RETURNS}:
                        return None
                    if status != 200:
                        raise WBError("wb_request_rejected")
                    self.cooldown_deadline = time.monotonic() + success_cooldown(response.headers)
                    raw = bytearray()
                    for chunk in response.iter_bytes(chunk_size=65536):
                        raw.extend(chunk)
                        if len(raw) > MAX_BYTES:
                            raise WBError("wb_response_too_large")
                        if time.monotonic() - started > 45:
                            raise WBError("wb_timeout", retryable=True)
                    self.response_bytes = len(raw)
                    return json.loads(raw, parse_float=Decimal)
        except httpx.HTTPError:
            raise WBError("wb_network_error", retryable=True) from None
        except ValueError, RecursionError:
            raise WBError("wb_invalid_response") from None

    def category_schema(self, token: str, subject: str):
        result = self.request(Source.CATALOG, token, catalog_subject=subject)
        return object_rows(result["data"])

    def page(self, source: Source, token: str, cursor: dict, start: date, end: date) -> Page:
        try:
            if source in {Source.STOCK_HISTORY, Source.SUPPLY_DEMAND, Source.SUPPLY_DEMAND_FBS}:
                from app.integrations.wildberries.stock_history import history_page

                return history_page(
                    self,
                    token,
                    cursor,
                    start,
                    end,
                    source=source,
                    stock_type="wb"
                    if source == Source.SUPPLY_DEMAND
                    else "mp"
                    if source == Source.SUPPLY_DEMAND_FBS
                    else "",
                )
            if source == Source.SUPPLIES:
                from app.integrations.wildberries.supplies import supply_page

                return supply_page(self, token, cursor)
            if source in {Source.PRICES, Source.FBS}:
                from app.integrations.wildberries.inventory import inventory_page

                return inventory_page(self, source, token, cursor)
            if source == Source.BALANCE:
                result = self.request(source, token)
                if not isinstance(result, dict):
                    raise WBError("wb_invalid_response")
                return Page([result], {}, True, self.cooldown_seconds)
            if source == Source.CATALOG:
                result = self.request(
                    source,
                    token,
                    body={
                        "settings": {
                            "sort": {"ascending": True},
                            "filter": {"withPhoto": -1},
                            "cursor": {"limit": 100, **cursor},
                        }
                    },
                )
                rows = object_rows(result["cards"])
                total = result["cursor"]["total"]
                if type(total) is not int or total != len(rows) or total > 100:
                    raise WBError("wb_invalid_response")
                if total < 100:
                    return Page(rows, cursor, True, self.cooldown_seconds)
                following = {k: result["cursor"][k] for k in ("updatedAt", "nmID")}
                if (
                    not isinstance(following["updatedAt"], str)
                    or type(following["nmID"]) is not int
                ):
                    raise WBError("wb_invalid_cursor")
                if cursor and (following["updatedAt"], following["nmID"]) <= (
                    cursor["updatedAt"],
                    cursor["nmID"],
                ):
                    raise WBError("wb_pagination_stalled")
                return Page(rows, following, False, self.cooldown_seconds)
            if source in CHANGE_FEEDS:
                # Existing daily runs resume safely. Oversized bulk responses fall back to days.
                if cursor.get("mode") == "daily" and cursor.get("bulk_attempted"):
                    day = date.fromisoformat(cursor.get("day", start.isoformat()))
                    rows = object_rows(
                        self.request(source, token, params={"dateFrom": day.isoformat(), "flag": 1})
                    )
                    return Page(
                        rows,
                        {
                            "mode": "daily",
                            "day": (day + timedelta(days=1)).isoformat(),
                            "bulk_attempted": True,
                        },
                        day >= end,
                        self.cooldown_seconds,
                    )
                previous = cursor.get("last_change", start.isoformat())
                try:
                    rows = object_rows(
                        self.request(source, token, params={"dateFrom": previous, "flag": 0})
                    )
                except WBError as error:
                    if error.code != "wb_response_too_large":
                        raise
                    return Page(
                        [],
                        {"mode": "daily", "day": start.isoformat(), "bulk_attempted": True},
                        False,
                        self.cooldown_seconds,
                    )
                if not rows:
                    return Page([], cursor, True, self.cooldown_seconds)
                timestamps = [row["lastChangeDate"] for row in rows]
                parsed = [
                    datetime.fromisoformat(value).replace(tzinfo=None) for value in timestamps
                ]
                if parsed != sorted(parsed):
                    raise WBError("wb_invalid_cursor")
                if "last_change" in cursor and parsed[-1] <= datetime.fromisoformat(
                    previous
                ).replace(tzinfo=None):
                    # Never increment the timestamp: that could skip sales with the same timestamp.
                    return Page(
                        [],
                        {"mode": "daily", "day": start.isoformat(), "bulk_attempted": True},
                        False,
                        self.cooldown_seconds,
                    )
                # dateFrom filters changes, not business dates. Keep only the requested events.
                selected = [
                    row for row in rows if start <= date.fromisoformat(row["date"][:10]) <= end
                ]
                return Page(selected, {"last_change": timestamps[-1]}, False, self.cooldown_seconds)
            if source == Source.STOCKS:
                offset = cursor.get("offset", 0)
                result = self.request(
                    source, token, body={"limit": STOCK_PAGE_SIZE, "offset": offset}
                )
                rows = [] if result is None else object_rows(result["data"]["items"])
                if len(rows) > STOCK_PAGE_SIZE:
                    raise WBError("wb_invalid_response")
                return Page(
                    rows,
                    {"offset": offset + len(rows)},
                    len(rows) < STOCK_PAGE_SIZE,
                    self.cooldown_seconds,
                )
            if source == Source.FINANCE:
                previous = cursor.get("rrdId", 0)
                preview = previous == 0 and "page_size" not in cursor
                page_size = cursor.get(
                    "page_size", INITIAL_FINANCE_PAGE_SIZE if preview else FINANCE_PAGE_SIZE
                )
                if type(page_size) is not int or not 1000 <= page_size <= MAX_FINANCE_PAGE_SIZE:
                    raise WBError("wb_invalid_cursor")
                try:
                    result = self.request(
                        source,
                        token,
                        body={
                            "dateFrom": start.isoformat(),
                            "dateTo": end.isoformat(),
                            "limit": page_size,
                            "rrdId": previous,
                            "period": "daily",
                            "fields": FINANCE_FIELDS,
                        },
                    )
                except WBError as error:
                    if error.code != "wb_response_too_large" or page_size <= 1000:
                        raise
                    return Page(
                        [],
                        {**cursor, "page_size": max(1000, page_size // 2)},
                        False,
                        self.cooldown_seconds,
                    )
                if result is None:
                    return Page([], cursor, True)
                rows = object_rows(result)
                # WB documents 204 as exhaustion; an empty 200 is not proof of completion.
                if not rows or len(rows) > page_size:
                    raise WBError("wb_invalid_response")
                ids = [row["rrdId"] for row in rows]
                if any(type(value) is not int or value <= previous for value in ids):
                    raise WBError("wb_pagination_stalled")
                if ids != sorted(set(ids)):
                    raise WBError("wb_invalid_cursor")
                following = {"rrdId": ids[-1], "page_size": page_size}
                if len(rows) == page_size and self.response_bytes <= MAX_BYTES // 4:
                    # Show the first preview quickly, then return to bulk downloads.
                    following["page_size"] = (
                        MAX_FINANCE_PAGE_SIZE
                        if preview
                        else min(MAX_FINANCE_PAGE_SIZE, page_size * 2)
                    )
                return Page(rows, following, False, self.cooldown_seconds)
            if source == Source.FUNNEL:
                if cursor.get("summary"):
                    return self.funnel_summary_page(token, cursor, start, end)
                return self.funnel_page(token, cursor, start, end)
            if source == Source.RETURNS:
                return self.returns_page(token, cursor, start, end)
            raise WBError("unsupported_source")
        except KeyError, TypeError, ValueError, IndexError:
            raise WBError("wb_invalid_response") from None

    def returns_page(self, token: str, cursor: dict, start: date, end: date) -> Page:
        """Returns to the seller in windows of at most 31 days (WB limit), 1000 per page."""
        window = date.fromisoformat(cursor.get("from", start.isoformat()))
        offset = cursor.get("offset", 0)
        if type(offset) is not int or offset < 0 or not start <= window <= end:
            raise WBError("wb_invalid_cursor")
        window_end = min(window + timedelta(days=RETURNS_WINDOW_DAYS - 1), end)
        result = self.request(
            Source.RETURNS,
            token,
            params={
                "dateFrom": window.isoformat(),
                "dateTo": window_end.isoformat(),
                "limit": RETURNS_PAGE_SIZE,
                "offset": offset,
            },
        )
        rows = [] if result is None else object_rows(result["report"])
        if result is not None and type(result["count"]) is not int:
            raise WBError("wb_invalid_response")
        if len(rows) > RETURNS_PAGE_SIZE:
            raise WBError("wb_invalid_response")
        if len(rows) == RETURNS_PAGE_SIZE:
            following = {"from": window.isoformat(), "offset": offset + len(rows)}
            return Page(rows, following, False, self.cooldown_seconds)
        if window_end >= end:
            return Page(
                rows, {"from": window.isoformat(), "offset": 0}, True, self.cooldown_seconds
            )
        following = {"from": (window_end + timedelta(days=1)).isoformat(), "offset": 0}
        return Page(rows, following, False, self.cooldown_seconds)

    def funnel_summary_page(self, token: str, cursor: dict, start: date, end: date) -> Page:
        """Current and previous periods in one paginated request, without daily detail."""
        before_end = start - timedelta(days=1)
        before_start = before_end - (end - start)
        offset = cursor.get("offset", 0)
        if type(offset) is not int or offset < 0:
            raise WBError("wb_invalid_cursor")
        periods = {
            "selected": {"start": start.isoformat(), "end": end.isoformat()},
            "past": {"start": before_start.isoformat(), "end": before_end.isoformat()},
        }
        result = self.request(
            Source.FUNNEL,
            token,
            body={
                "selectedPeriod": periods["selected"],
                "pastPeriod": periods["past"],
                "nmIds": [],
                "skipDeletedNm": False,
                "orderBy": {"field": "openCard", "mode": "desc"},
                "limit": FUNNEL_PAGE_SIZE,
                "offset": offset,
            },
        )
        products = object_rows(result["data"]["products"])
        currency = result["data"]["currency"]
        if (
            len(products) > FUNNEL_PAGE_SIZE
            or not isinstance(currency, str)
            or not 0 < len(currency) <= 16
        ):
            raise WBError("wb_invalid_response")
        if cursor.get("currency", currency) != currency:
            raise WBError("wb_invalid_response")
        rows = []
        for item in products:
            for name, period in periods.items():
                figures = item["statistic"][name]
                if figures["period"] != period:
                    raise WBError("wb_invalid_response")
                counts = [figures[field] for field in (*FUNNEL_COUNTERS, "addToWishlist")]
                sums = [figures[field] for field in ("orderSum", "buyoutSum", "cancelSum")]
                if any(type(value) is not int or value < 0 for value in counts) or any(
                    isinstance(value, bool)
                    or not isinstance(value, (int, Decimal))
                    or not Decimal(value).is_finite()
                    or value < 0
                    for value in sums
                ):
                    raise WBError("wb_invalid_response")
                rows.append(
                    {
                        **figures,
                        "nmId": item["product"]["nmId"],
                        "currency": currency,
                        "period_from": period["start"],
                        "period_to": period["end"],
                    }
                )
        following = {"summary": True, "offset": offset + len(products), "currency": currency}
        return Page(rows, following, len(products) < FUNNEL_PAGE_SIZE, self.cooldown_seconds)

    def funnel_page(self, token: str, cursor: dict, start: date, end: date) -> Page:
        """One day per request: the daily-history method only covers the last week, the
        period method covers 365 days, so a one-day period gives daily figures for a year.
        Rows get the requested day and currency attached; idle cards are skipped."""
        descending = cursor.get("direction") == "desc"
        first = end if descending else start
        day = date.fromisoformat(cursor.get("day", first.isoformat()))
        offset = cursor.get("offset", 0)
        if type(offset) is not int or offset < 0 or not start <= day <= end:
            raise WBError("wb_invalid_cursor")
        result = self.request(
            Source.FUNNEL,
            token,
            body={
                "selectedPeriod": {"start": day.isoformat(), "end": day.isoformat()},
                "nmIds": [],
                "skipDeletedNm": False,
                "orderBy": {"field": "openCard", "mode": "desc"},
                "limit": FUNNEL_PAGE_SIZE,
                "offset": offset,
            },
        )
        products = object_rows(result["data"]["products"])
        currency = result["data"]["currency"]
        if len(products) > FUNNEL_PAGE_SIZE or not isinstance(currency, str):
            raise WBError("wb_invalid_response")
        if not currency or len(currency) > 16:
            raise WBError("wb_invalid_response")
        rows = []
        for item in products:
            figures = item["statistic"]["selected"]
            if not isinstance(figures, dict):
                raise WBError("wb_invalid_response")
            period = figures["period"]
            if period != {"start": day.isoformat(), "end": day.isoformat()}:
                raise WBError("wb_invalid_response")
            # Validate zero rows too: a malformed report must never erase published data.
            counts = [figures[name] for name in (*FUNNEL_COUNTERS, "addToWishlist")]
            if any(type(value) is not int or value < 0 for value in counts):
                raise WBError("wb_invalid_response")
            sums = [figures[name] for name in ("orderSum", "buyoutSum", "cancelSum")]
            if any(
                isinstance(value, bool)
                or not isinstance(value, (int, Decimal))
                or not Decimal(value).is_finite()
                or value < 0
                for value in sums
            ):
                raise WBError("wb_invalid_response")
            if any(counts) or any(sums):
                rows.append(
                    {
                        **figures,
                        "nmId": item["product"]["nmId"],
                        "vendorCode": item["product"].get("vendorCode", ""),
                        "day": day.isoformat(),
                        "currency": currency,
                    }
                )
        direction = {"direction": "desc"} if descending else {}
        if len(products) == FUNNEL_PAGE_SIZE:
            return Page(
                rows,
                {**direction, "day": day.isoformat(), "offset": offset + len(products)},
                False,
                self.cooldown_seconds,
            )
        complete = day <= start if descending else day >= end
        following = day if complete else day + timedelta(days=-1 if descending else 1)
        return Page(
            rows,
            {**direction, "day": following.isoformat(), "offset": 0},
            complete,
            self.cooldown_seconds,
        )
