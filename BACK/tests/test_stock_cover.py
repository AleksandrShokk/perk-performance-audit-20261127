import json
from datetime import date, timedelta
from types import SimpleNamespace

import httpx
import pytest

from app.integrations.wildberries.data import Source, WBDataClient, WBError
from app.modules.auth.dependencies import now
from app.modules.inventory.stock_cover import order_rate, product_cover, stock_cover
from app.modules.sync.normalize import normalize
from app.modules.sync.planner import next_run
from app.modules.sync.schemas import ConfigureSchedule, StartSync, moscow_today


def report(**changes):
    return {
        "nm_id": "42",
        "date_from": "2026-10-01",
        "date_to": "2026-10-28",
        "stock": 100,
        "orders": 140,
        "missing_hours": 0,
        **changes,
    }


def wb_row(**metrics):
    return {
        "nmID": 42,
        "periodStart": "2026-10-01",
        "periodEnd": "2026-10-28",
        "metrics": {
            "stockCount": 100,
            "ordersCount": 140,
            "officeMissingTime": {"days": 0, "hours": 0},
            "buyoutCount": 70,
            "saleRate": {"days": 40, "hours": 0},
            **metrics,
        },
    }


def test_stock_cover_uses_orders_and_current_stock_not_native_buyout_turnover():
    key, row = normalize(Source.STOCK_HISTORY, wb_row())
    assert key == "42" and row == report()
    assert product_cover(row) == "20.00" and stock_cover([row]) == "20.00"
    assert "saleRate" not in row and "buyoutCount" not in row


def test_out_of_stock_time_counts_hours_without_rounding_days():
    _, row = normalize(
        Source.STOCK_HISTORY, wb_row(ordersCount=195, officeMissingTime={"days": 8, "hours": 12})
    )
    assert order_rate(row) == 10 and product_cover(row) == "10.00"


@pytest.mark.parametrize(
    "changes",
    [
        {"orders": 0},
        {"orders": None},
        {"missing_hours": None},
        {"missing_hours": 672},
        {"stock": None},
        {"date_from": "2026-10-02"},
    ],
)
def test_missing_or_insufficient_demand_never_becomes_zero(changes):
    assert product_cover(report(**changes)) is None
    assert stock_cover([report(**changes)]) is None


def test_sold_out_product_is_zero_but_does_not_shorten_unrelated_inventory():
    sold_out = report(stock=0, orders=2800)
    assert product_cover(sold_out) == "0.00"
    assert stock_cover([sold_out]) == "0.00"
    assert stock_cover([report(), sold_out]) == "20.00"


def test_summary_uses_total_stock_over_total_demand_not_average_days():
    first, second = report(), report(nm_id="43", stock=90, orders=28)
    assert product_cover(second) == "90.00"
    assert stock_cover([first, second]) == "31.67"
    assert stock_cover([first, report(stock=10, orders=0)]) == "22.00"
    assert stock_cover([first, report(stock=10, missing_hours=None)]) is None


@pytest.mark.parametrize(
    "missing", [{"days": 29, "hours": 0}, {"days": 0, "hours": 24}, {"days": -1, "hours": 0}]
)
def test_provider_cannot_invent_time_outside_the_requested_period(missing):
    _, row = normalize(Source.STOCK_HISTORY, wb_row(officeMissingTime=missing))
    assert row["missing_hours"] is None and product_cover(row) is None


def test_unknown_missing_time_is_retained_as_unknown_not_full_availability():
    _, row = normalize(Source.STOCK_HISTORY, wb_row(officeMissingTime=None))
    assert row["missing_hours"] is None and product_cover(row) is None


def test_report_transport_reads_all_models_and_stocks_without_business_filters():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"data": {"items": [wb_row()]}})

    client = WBDataClient(httpx.MockTransport(handler))
    page = client.page(Source.STOCK_HISTORY, "synthetic", {}, date(2026, 10, 1), date(2026, 10, 28))
    body = json.loads(requests[0].content)
    assert requests[0].method == "POST"
    assert requests[0].url.host == "seller-analytics-api.wildberries.ru"
    assert requests[0].url.path == "/api/v2/stocks-report/products/products"
    assert body["stockType"] == "" and not body["skipDeletedNm"]
    assert body["nmIDs"] == [] and body["availabilityFilters"] == []
    assert body["currentPeriod"] == {"start": "2026-10-01", "end": "2026-10-28"}
    assert page.complete and page.rows[0]["periodStart"] == "2026-10-01"


def test_report_pagination_advances_and_accepts_a_confirmed_empty_last_page(monkeypatch):
    from app.integrations.wildberries import stock_history

    monkeypatch.setattr(stock_history, "PAGE_SIZE", 2)
    offsets = []

    def handler(request):
        offsets.append(json.loads(request.content)["offset"])
        items = [{"nmID": 42}, {"nmID": 43}] if offsets[-1] == 0 else []
        return httpx.Response(200, json={"data": {"items": items}})

    client = WBDataClient(httpx.MockTransport(handler))
    first = client.page(
        Source.STOCK_HISTORY, "synthetic", {}, date(2026, 10, 1), date(2026, 10, 28)
    )
    last = client.page(
        Source.STOCK_HISTORY, "synthetic", first.cursor, date(2026, 10, 1), date(2026, 10, 28)
    )
    assert not first.complete and last.complete and last.rows == [] and offsets == [0, 2]


def test_history_schedule_always_requests_past_28_days_without_a_backfill():
    plan = SimpleNamespace(
        source=Source.STOCK_HISTORY,
        recent_days=7,
        recent_completed=False,
        next_refresh_at=now() + timedelta(hours=6),
        history_from=None,
    )
    mode, start, end, cursor = next_run(plan)
    assert mode == "snapshot" and (end - start).days == 27
    assert end == moscow_today() - timedelta(days=1) and cursor == {}
    assert StartSync(sources=[Source.STOCK_HISTORY]).period_for(Source.STOCK_HISTORY) == (
        start,
        end,
    )
    plan.recent_completed = True
    assert next_run(plan) is None
    plan.next_refresh_at = now()
    assert next_run(plan)[1:3] == (start, end)
    for source in (Source.STOCKS, Source.FUNNEL):
        assert Source.STOCK_HISTORY in ConfigureSchedule(sources=[source]).effective_sources()


def test_live_wb_negative_hours_are_unknown_and_summary_is_explicitly_partial():
    from app.modules.inventory.stock_cover import coverage_summary

    _, invalid = normalize(Source.STOCK_HISTORY, wb_row(officeMissingTime={"days": 0, "hours": -4}))
    assert invalid["missing_hours"] is None and product_cover(invalid) is None
    assert coverage_summary([report(), invalid]) == ("20.00", True)
    assert coverage_summary([report()]) == ("20.00", False)
    assert coverage_summary([invalid]) == (None, True)


def test_malformed_duration_is_rejected_instead_of_being_treated_as_full_availability():
    with pytest.raises(WBError):
        normalize(Source.STOCK_HISTORY, wb_row(officeMissingTime={"days": "unknown", "hours": 0}))


@pytest.mark.parametrize(
    "row,loading,expected",
    [
        (report(), False, ("20.00", "ready")),
        (report(stock=0), False, ("0.00", "ready")),
        (report(orders=0), False, (None, "no_orders")),
        (report(orders=0, missing_hours=None), False, (None, "no_orders")),
        (report(orders=None), False, (None, "no_data")),
        (report(missing_hours=None), False, (None, "no_data")),
        (report(missing_hours=672), False, (None, "no_data")),
        (report(orders=0, date_from="2026-10-02"), False, (None, "no_data")),
        (None, False, (None, "no_data")),
        (None, True, (None, "loading")),
        (report(), True, ("20.00", "ready")),
        (report(orders=0), True, (None, "no_orders")),
    ],
)
def test_product_coverage_distinguishes_no_orders_from_missing_data_and_refresh(
    row, loading, expected
):
    from app.modules.inventory.stock_cover import product_coverage

    assert product_coverage(row, loading=loading) == expected
