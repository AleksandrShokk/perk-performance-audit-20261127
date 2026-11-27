import json
from datetime import date, timedelta
from decimal import Decimal

import httpx
import pytest
from test_sync_plans import plan

from app.integrations.wildberries.data import Source, WBDataClient, WBError
from app.modules.auth.dependencies import now
from app.modules.sync.analytics import contribution
from app.modules.sync.normalize import normalize
from app.modules.sync.schemas import (
    FINANCE_START,
    ConfigureSchedule,
    StartSync,
    history_limits,
    moscow_today,
)


def order(**changes):
    return {
        "srid": "11.rabc",
        "nmId": 42,
        "date": "2026-10-01T10:00:00",
        "lastChangeDate": "2026-10-01T10:05:00",
        "supplierArticle": "A-1",
        "barcode": "200",
        "techSize": "M",
        "warehouseName": "Коледино",
        "warehouseType": "Склад WB",
        "regionName": "Московская",
        "totalPrice": Decimal("2000"),
        "discountPercent": 30,
        "spp": Decimal("12.5"),
        "priceWithDisc": Decimal("1400"),
        "finishedPrice": Decimal("1225.50"),
        "isCancel": False,
        "cancelDate": "0001-01-01T00:00:00",
        "gNumber": "basket-private",
        "sticker": "123",
        **changes,
    }


def test_order_keeps_only_analytics_fields_and_exact_money():
    key, value = normalize(Source.ORDERS, order())
    assert key == "11.rabc" and value["nm_id"] == "42"
    assert value["finished_price"] == "1225.50" and value["spp"] == "12.5"
    assert value["cancel_date"] is None and value["is_cancel"] is False
    assert "basket-private" not in json.dumps(value, ensure_ascii=False)
    cancelled = normalize(Source.ORDERS, order(isCancel=True, cancelDate="2026-10-02T08:00:00"))[1]
    assert cancelled["is_cancel"] and cancelled["cancel_date"] == "2026-10-02T08:00:00"


@pytest.mark.parametrize("changes", [{"srid": ""}, {"isCancel": "false"}, {"nmId": -1}])
def test_malformed_orders_are_rejected(changes):
    with pytest.raises(WBError, match="wb_invalid_record"):
        normalize(Source.ORDERS, order(**changes))


def test_cancellation_moves_an_order_between_aggregate_fields():
    _, active = normalize(Source.ORDERS, order())
    _, cancelled = normalize(Source.ORDERS, order(isCancel=True))
    key, before = contribution(Source.ORDERS, active)
    same_key, after = contribution(Source.ORDERS, cancelled)
    assert key == same_key == (date(2026, 10, 1), "42", "WB")
    assert before["orders"] == after["orders"] == 1
    assert before["orders_amount"] == Decimal("1225.50")
    assert "cancellations" not in before
    assert after["cancellations"] == 1 and after["cancellations_amount"] == Decimal("1225.50")
    _, unpriced = contribution(Source.ORDERS, {**active, "finished_price": None})
    assert unpriced["missing_prices"] == 1 and unpriced["orders_amount"] == 0


def test_orders_page_uses_change_feed_and_filters_order_dates():
    calls = []

    def handler(request):
        calls.append(request)
        rows = [
            order(srid="a", date="2026-09-30T23:00:00", lastChangeDate="2026-10-01T01:00:00"),
            order(srid="b", date="2026-10-01T09:00:00", lastChangeDate="2026-10-01T09:30:00"),
        ]
        return httpx.Response(200, content=json.dumps(rows, default=float))

    day = date(2026, 10, 1)
    page = WBDataClient(httpx.MockTransport(handler)).page(Source.ORDERS, "x", {}, day, day)
    assert calls[0].url.host == "statistics-api.wildberries.ru"
    assert calls[0].url.path == "/api/v1/supplier/orders"
    assert calls[0].url.params["flag"] == "0"
    assert [row["srid"] for row in page.rows] == ["b"]
    assert page.cursor == {"last_change": "2026-10-01T09:30:00"} and not page.complete


def test_orders_follow_sales_retention_and_schedule_defaults():
    today = moscow_today()
    request = StartSync(sources=[Source.ORDERS], date_from=FINANCE_START, date_to=today)
    assert request.effective_sources() == [Source.ORDERS]
    assert request.period_for(Source.ORDERS) == (today - timedelta(days=89), today)
    assert Source.ORDERS in ConfigureSchedule().effective_sources()
    assert len(StartSync().sources) == len(Source)


def fake_metrics(monkeypatch, rows):
    from app.modules.insights import orders as report_module

    def published(db, vault, workspace_id, store_id, source, start, end):
        for day, nm_id, values in rows[source]:
            if start <= day <= end:
                yield day, nm_id, values

    monkeypatch.setattr(report_module, "published", published)
    return report_module


def test_orders_report_counts_cancellations_and_buyouts(monkeypatch):
    d1, d2 = date(2026, 10, 1), date(2026, 10, 2)
    module = fake_metrics(
        monkeypatch,
        {
            Source.ORDERS: [
                (
                    d1,
                    "1",
                    {
                        "orders": "4",
                        "orders_amount": "400",
                        "cancellations": "1",
                        "cancellations_amount": "100",
                        "missing_prices": "0",
                    },
                ),
                (d2, "2", {"orders": "6", "orders_amount": "900", "missing_prices": "0"}),
            ],
            Source.SALES: [
                (d1, "1", {"sales": "2", "sales_amount": "200", "missing_prices": "0"}),
                (
                    d2,
                    "2",
                    {"sales": "4", "sales_amount": "600", "returns": "1", "missing_prices": "0"},
                ),
            ],
        },
    )
    full = module.report(None, None, "w", "s", d1, d2, lambda source: (d1, d2))
    totals = full["totals"]
    assert full["status"] == "ready" and full["period_days"] == 2
    assert totals["orders"] == 10 and totals["cancellations"] == 1 and totals["net_orders"] == 9
    assert totals["orders_amount"] == "1300.00" and totals["net_orders_amount"] == "1200.00"
    assert totals["cancel_rate_percent"] == "10.0" and totals["average_order_value"] == "130.00"
    assert totals["buyouts"] == 6 and totals["returns"] == 1
    assert totals["buyout_rate_percent"] == "66.7"
    assert [item["nm_id"] for item in full["products"]] == ["2", "1"]

    def partial_known(source):
        return (d1, d2) if source == Source.ORDERS else (d1, d1)

    partial = module.report(None, None, "w", "s", d1, d2, partial_known)
    assert partial["status"] == "partial" and partial["sales_known_days"] == 1
    assert partial["daily"][1]["buyouts"] is None and partial["daily"][1]["orders"] == 6
    # Buyouts of one day against orders of two would be misleading.
    assert partial["totals"]["buyout_rate_percent"] is None
    assert partial["totals"]["buyouts"] == 2
    nothing = module.report(None, None, "w", "s", d1, d2, lambda source: (None, None))
    assert nothing["status"] == "no_data" and nothing["totals"]["orders"] is None


def test_unpriced_order_makes_amounts_unknown_not_zero(monkeypatch):
    day = date(2026, 10, 1)
    module = fake_metrics(
        monkeypatch,
        {
            Source.ORDERS: [
                (day, "1", {"orders": "2", "orders_amount": "100", "missing_prices": "1"})
            ],
            Source.SALES: [],
        },
    )
    result = module.report(None, None, "w", "s", day, day, lambda source: (day, day))
    assert result["totals"]["orders"] == 2 and result["totals"]["orders_amount"] is None
    assert result["totals"]["average_order_value"] is None


def test_forecast_demand_uses_orders_only_when_they_cover_the_window(monkeypatch):
    from app.modules.inventory import service

    start, end = date(2026, 9, 1), date(2026, 9, 30)
    calls = []
    monkeypatch.setattr(
        service, "daily_sales", lambda *args, **kwargs: calls.append(args[-1:]) or {}
    )
    monkeypatch.setattr(service, "known_days", lambda *args: (start, end))
    assert service.demand(None, None, "w", "s", start, end)[0] == "orders"
    assert calls[-1] == (Source.ORDERS,)
    monkeypatch.setattr(service, "known_days", lambda *args: (start + timedelta(days=1), end))
    assert service.demand(None, None, "w", "s", start, end)[0] == "buyouts"
    monkeypatch.setattr(service, "known_days", lambda *args: (None, None))
    assert service.demand(None, None, "w", "s", start, end)[0] == "buyouts"


def test_orders_refresh_by_change_cursor_like_sales():
    from app.modules.sync.planner import next_run

    value = plan(
        Source.ORDERS,
        recent_completed=True,
        next_refresh_at=now(),
        sales_cursor=(moscow_today() - timedelta(days=1)).isoformat(),
    )
    mode, start, end, cursor = next_run(value)
    assert mode == "incremental" and start == history_limits()[Source.ORDERS]["date_from"]
    assert end == moscow_today() and cursor["last_change"]
    value = plan(Source.ORDERS, recent_completed=True)
    mode, start, _, _ = next_run(value)
    assert mode == "backfill" and start == history_limits()[Source.ORDERS]["date_from"]
