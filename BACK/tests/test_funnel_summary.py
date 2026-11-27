import json
from datetime import date, timedelta

import httpx
import pytest
from test_sync_plans import plan
from test_wb_funnel import figures

from app.integrations.wildberries import data
from app.integrations.wildberries.data import Source, WBDataClient, WBError
from app.modules.sync.funnel_summary import normalize_row, previous
from app.modules.sync.planner import next_run


def test_period_request_includes_exact_previous_period_and_preserves_money():
    start, end = date(2026, 9, 27), date(2026, 10, 24)
    before_start, before_end = previous(start, end)
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(
            200,
            content="""{"data":{"currency":"RUB","products":[{
          "product":{"nmId":42},"statistic":{
          "selected":SELECTED,"past":PAST}}]}}""".replace(
                "SELECTED", json.dumps(figures(period={"start": str(start), "end": str(end)}))
            ).replace(
                "PAST",
                json.dumps(figures(period={"start": str(before_start), "end": str(before_end)})),
            ),
        )

    page = WBDataClient(httpx.MockTransport(respond)).page(
        Source.FUNNEL, "synthetic", {"summary": True}, start, end
    )
    body = json.loads(calls[0].content)
    assert body["selectedPeriod"] == {"start": "2026-09-27", "end": "2026-10-24"}
    assert body["pastPeriod"] == {"start": "2026-08-30", "end": "2026-09-26"}
    assert page.complete and len(page.rows) == 2 and page.cursor["currency"] == "RUB"
    key, current = normalize_row(page.rows[0])
    assert key == "2026-09-27:42" and current["order_sum"] == "1000"
    assert "day" not in current and current["period_to"] == "2026-10-24"


def test_period_pagination_empty_end_and_currency_validation(monkeypatch):
    monkeypatch.setattr(data, "FUNNEL_PAGE_SIZE", 1)
    start = date(2026, 10, 24)
    card = {
        "product": {"nmId": 42},
        "statistic": {
            "selected": figures(day=str(start)),
            "past": figures(day=str(start - timedelta(days=1))),
        },
    }
    responses = [[card], []]
    client = WBDataClient(
        httpx.MockTransport(
            lambda _: httpx.Response(
                200, json={"data": {"products": responses.pop(0), "currency": "RUB"}}
            )
        )
    )
    first = client.page(Source.FUNNEL, "synthetic", {"summary": True}, start, start)
    assert not first.complete and first.cursor["offset"] == 1
    last = client.page(Source.FUNNEL, "synthetic", first.cursor, start, start)
    assert last.complete and last.rows == [] and last.cursor["summary"] is True
    wrong = WBDataClient(
        httpx.MockTransport(
            lambda _: httpx.Response(200, json={"data": {"products": [], "currency": "KZT"}})
        )
    )
    with pytest.raises(WBError, match="wb_invalid_response"):
        wrong.page(Source.FUNNEL, "synthetic", first.cursor, start, start)


def test_period_wrong_or_missing_past_period_is_rejected():
    start = date(2026, 10, 24)
    for past in (None, figures(day="2026-10-01")):
        card = {"product": {"nmId": 42}, "statistic": {"selected": figures(day=str(start))}}
        if past:
            card["statistic"]["past"] = past
        client = WBDataClient(
            httpx.MockTransport(
                lambda _, item=card: httpx.Response(
                    200, json={"data": {"products": [item], "currency": "RUB"}}
                )
            )
        )
        with pytest.raises(WBError, match="wb_invalid_response"):
            client.page(Source.FUNNEL, "synthetic", {"summary": True}, start, start)


def test_initial_funnel_is_seven_days_and_newest_day_comes_first():
    mode, start, end, cursor = next_run(plan(Source.FUNNEL))
    assert mode == "recent" and (end - start).days == 6 and cursor["direction"] == "desc"
    calls = []

    def respond(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200, json={"data": {"products": [], "currency": "RUB"}})

    client = WBDataClient(httpx.MockTransport(respond))
    page = client.page(Source.FUNNEL, "synthetic", cursor, start, end)
    assert calls[0]["selectedPeriod"] == {"start": str(end), "end": str(end)}
    assert page.cursor == {"direction": "desc", "day": str(end - timedelta(days=1)), "offset": 0}
    assert not page.complete
