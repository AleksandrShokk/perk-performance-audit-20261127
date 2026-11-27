import json
from datetime import date, timedelta
from types import SimpleNamespace

import httpx
import pytest

from app.integrations.wildberries import data
from app.integrations.wildberries.data import Source, WBDataClient, WBError
from app.modules.insights import returns
from app.modules.sync.normalize import normalize
from app.modules.sync.schemas import ConfigureSchedule, StartSync, history_limits, moscow_today


def wb_row(**changes):
    return {
        "srid": "mp.abc.r",
        "shkId": 23411783472,
        "nmId": 42,
        "sku": "1680063403480",
        "techSize": "M",
        "subjectName": "Бирки",
        "brand": "dub",
        "returnType": "Возврат брака",
        "returnStatus": "Готов к выдаче",
        "orderDt": "2026-09-01",
        "readyToReturnDt": "2026-10-01T08:33:50",
        "completedDt": "",
        "expiredDt": "2026-10-20T11:33:53",
        "dstOfficeId": 310105,
        "dstOfficeAddress": "Жуковский, ул. Маяковского 19",
        "kiz": "0102900000376311210G2CIS-private",
        "stickerId": "33811984302",
        "orderId": 2034240826,
        **changes,
    }


def client(responses, calls):
    def handler(request):
        calls.append(request)
        return responses.pop(0)

    return WBDataClient(httpx.MockTransport(handler))


def test_long_period_is_split_into_31_day_windows():
    calls = []
    start, end = date(2026, 8, 1), date(2026, 9, 9)
    c = client(
        [httpx.Response(200, json={"count": 1, "report": [wb_row()]}), httpx.Response(204)], calls
    )
    first = c.page(Source.RETURNS, "x", {}, start, end)
    assert calls[0].url.path == "/api/analytics/v1/item-returns"
    assert calls[0].url.params["dateFrom"] == "2026-08-01"
    assert calls[0].url.params["dateTo"] == "2026-08-31"
    assert first.cursor == {"from": "2026-09-01", "offset": 0} and not first.complete
    second = c.page(Source.RETURNS, "x", first.cursor, start, end)
    assert calls[1].url.params["dateTo"] == "2026-09-09"
    assert second.complete and second.rows == []


def test_full_page_continues_inside_the_window(monkeypatch):
    monkeypatch.setattr(data, "RETURNS_PAGE_SIZE", 1)
    calls = []
    day = date(2026, 10, 1)
    page = client([httpx.Response(200, json={"count": 2, "report": [wb_row()]})], calls).page(
        Source.RETURNS, "x", {}, day, day
    )
    assert page.cursor == {"from": "2026-10-01", "offset": 1} and not page.complete


def test_malformed_report_is_rejected():
    with pytest.raises(WBError, match="wb_invalid_response"):
        client([httpx.Response(200, json={"count": "1", "report": []})], []).page(
            Source.RETURNS, "x", {}, date(2026, 10, 1), date(2026, 10, 1)
        )


def test_normalized_return_has_no_marking_code_or_order_ids():
    key, value = normalize(Source.RETURNS, wb_row())
    assert key == "mp.abc.r:23411783472"
    text = json.dumps(value, ensure_ascii=False)
    assert "private" not in text and "33811984302" not in text and "2034240826" not in text
    assert value["completed_at"] is None and value["ready_at"].startswith("2026-10-01")
    with pytest.raises(WBError):
        normalize(Source.RETURNS, wb_row(srid=""))


def test_returns_are_scheduled_by_default_with_bounded_history():
    assert Source.RETURNS in ConfigureSchedule().effective_sources()
    floor = history_limits()[Source.RETURNS]["date_from"]
    assert floor == moscow_today() - timedelta(days=179)
    request = StartSync(sources=[Source.RETURNS], date_from=date(2024, 1, 29))
    assert request.period_for(Source.RETURNS)[0] == floor


def fake(monkeypatch, items, windows, today=date(2026, 10, 18)):
    monkeypatch.setattr(returns, "records", lambda *args: iter(items))
    monkeypatch.setattr(returns, "coverage", lambda *args: {Source.RETURNS: windows})
    monkeypatch.setattr(returns, "moscow_today", lambda: today)
    return SimpleNamespace(scalar=lambda *args: None)


def item(**changes):
    return {**normalize(Source.RETURNS, wb_row())[1], **changes}


def test_period_counts_and_pickup_deadlines(monkeypatch):
    items = [
        item(),  # ready, expires in 2 days
        item(srid="b", nm_id="7", expires_at="2026-10-15T00:00:00", return_type="Невыкуп"),
        item(srid="c", completed_at="2026-10-05T10:00:00"),  # already collected
        item(srid="d", ready_at=None, order_date="2026-10-02"),  # still in transit
        item(srid="e", ready_at="2026-06-01T00:00:00"),  # outside the period
    ]
    db = fake(monkeypatch, items, [{"date_from": "2026-09-01", "date_to": "2026-10-17"}])
    result = returns.report(db, None, "w", "s", date(2026, 10, 1), date(2026, 10, 2))
    assert result["status"] == "ready" and result["totals"]["returns"] == 4
    assert {row["name"]: row["count"] for row in result["by_type"]} == {
        "Возврат брака": 3,
        "Невыкуп": 1,
    }
    pickup = result["pickup"]
    assert pickup["awaiting"] == 3 and pickup["in_transit"] == 1
    assert pickup["expired"] == 1 and pickup["expiring_soon"] == 2
    assert [row["days_left"] for row in pickup["items"]] == [-3, 2, 2]
    assert result["products"][0]["nm_id"] == "42"


def test_uncovered_days_are_unknown(monkeypatch):
    db = fake(monkeypatch, [item()], [])
    result = returns.report(db, None, "w", "s", date(2026, 10, 1), date(2026, 10, 1))
    assert result["status"] == "no_data" and result["totals"]["returns"] is None
    assert result["daily"][0]["returns"] is None
    assert result["pickup"]["awaiting"] == 1  # current state does not depend on the period
