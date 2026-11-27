import json
from datetime import date, timedelta
from decimal import Decimal

import httpx
import pytest
from test_sync_plans import plan

from app.integrations.wildberries import data
from app.integrations.wildberries.data import Source, WBDataClient, WBError
from app.modules.insights import funnel
from app.modules.sync.analytics import contribution
from app.modules.sync.normalize import normalize
from app.modules.sync.planner import next_run
from app.modules.sync.schemas import ConfigureSchedule, history_limits, moscow_today


def figures(day="2026-10-01", **changes):
    return {
        "period": {"start": day, "end": day},
        "openCount": 100,
        "cartCount": 20,
        "orderCount": 10,
        "buyoutCount": 6,
        "cancelCount": 2,
        "addToWishlist": 5,
        "orderSum": 1000,
        "buyoutSum": 600,
        "cancelSum": 200,
        **changes,
    }


def item(**changes):
    return {
        "product": {"nmId": 42, "vendorCode": "a"},
        "statistic": {"selected": figures(**changes)},
    }


def client(products, calls):
    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"data": {"products": products, "currency": "RUB"}})

    return WBDataClient(httpx.MockTransport(handler))


def test_funnel_one_day_request_and_next_day_cursor():
    calls = []
    start = date(2026, 10, 1)
    page = client([item()], calls).page(Source.FUNNEL, "x", {}, start, start + timedelta(days=1))
    body = json.loads(calls[0].content)
    assert calls[0].url.path == "/api/analytics/v3/sales-funnel/products"
    assert body["selectedPeriod"] == {"start": str(start), "end": str(start)}
    assert body["skipDeletedNm"] is False and body["nmIds"] == []
    assert page.cursor == {"day": "2026-10-02", "offset": 0} and not page.complete
    key, row = normalize(Source.FUNNEL, page.rows[0])
    assert key == "2026-10-01:42" and row["open_count"] == 100
    assert row["order_sum"] == "1000" and row["currency"] == "RUB"


def test_funnel_pagination_and_completion(monkeypatch):
    monkeypatch.setattr(data, "FUNNEL_PAGE_SIZE", 1)
    start = date(2026, 10, 1)
    calls = []
    page = client([item()], calls).page(Source.FUNNEL, "x", {}, start, start)
    assert page.cursor == {"day": str(start), "offset": 1} and not page.complete
    done = client([], calls).page(Source.FUNNEL, "x", page.cursor, start, start)
    assert json.loads(calls[-1].content)["offset"] == 1 and done.complete


@pytest.mark.parametrize(
    "changes",
    [
        {"period": {"start": "2026-09-01", "end": "2026-10-01"}},
        {"cartCount": -1},
        {"openCount": "100"},
        {"openCount": True},
        {"orderSum": -1},
        {"buyoutSum": True},
    ],
)
def test_bad_response_cannot_be_published(changes):
    with pytest.raises(WBError, match="wb_invalid_response"):
        client([item(**changes)], []).page(
            Source.FUNNEL, "x", {}, date(2026, 10, 1), date(2026, 10, 1)
        )


def test_idle_card_skipped_but_day_is_complete():
    values = {key: 0 for key in figures() if key != "period"}
    page = client([item(**values)], []).page(
        Source.FUNNEL, "x", {}, date(2026, 10, 1), date(2026, 10, 1)
    )
    assert page.complete and page.rows == []


def test_normalize_aggregate_and_weighted_conversions():
    _, row = normalize(
        Source.FUNNEL,
        {**figures(), "day": "2026-10-01", "nmId": 42, "currency": "RUB", "secret": "private"},
    )
    assert "secret" not in row
    key, values = contribution(Source.FUNNEL, row)
    assert key == (date(2026, 10, 1), "42", "RUB")
    result = funnel.view(values, True)
    assert result["add_to_cart_percent"] == "20.0"
    assert result["cart_to_order_percent"] == "50.0"
    assert result["open_to_order_percent"] == "10.0"
    assert result["buyout_percent"] == "75.0"  # 6 / (6 + 2), excludes in-flight
    assert result["orders_amount"] == "1000.00"
    values["missing_order_sum"] = Decimal(1)
    assert funnel.view(values, True)["orders_amount"] is None
    assert funnel.view(values, False)["buyouts_amount"] is None


def test_coverage_never_fills_a_gap_with_zero():
    days = funnel.known_days(
        [
            {"date_from": "2026-10-01", "date_to": "2026-10-02"},
            {"date_from": "2026-10-04", "date_to": "2026-10-05"},
        ],
        date(2026, 10, 2),
        date(2026, 10, 4),
    )
    assert days == {date(2026, 10, 2), date(2026, 10, 4)}
    assert funnel.unknown()["opens"] is None
    assert funnel.percent(0, 0) is None and funnel.percent(0, 100) == "0.0"


def test_schedule_includes_funnel_and_retention_is_bounded():
    assert Source.FUNNEL in ConfigureSchedule().effective_sources()
    value = plan(Source.FUNNEL)
    assert next_run(value)[0] == "recent"
    value.history_from = date(2024, 1, 29)
    value.recent_completed = True
    mode, start, end, _ = next_run(value)
    # One request per day: history is published week by week, never older than WB keeps.
    assert mode == "backfill" and (end - start).days == 6
    assert value.history_from == history_limits()[Source.FUNNEL]["date_from"]
    assert start >= moscow_today() - timedelta(days=364)
