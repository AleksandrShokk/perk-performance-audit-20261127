import json
from datetime import date, timedelta
from decimal import Decimal

import httpx
import pytest
from cryptography.exceptions import InvalidTag

from app.integrations.wildberries.data import (
    FINANCE_PAGE_SIZE,
    INITIAL_FINANCE_PAGE_SIZE,
    STOCK_PAGE_SIZE,
    Source,
    WBDataClient,
    WBError,
)
from app.modules.sync.normalize import normalize
from app.modules.sync.schemas import FINANCE_START, StartSync, moscow_today
from app.modules.sync.service import context


def client(response, calls=None):
    def handler(request):
        if calls is not None:
            calls.append(request)
        return response

    return WBDataClient(httpx.MockTransport(handler))


def test_redirect_never_sends_credential_to_another_host():
    calls = []
    c = client(httpx.Response(302, headers={"Location": "https://attacker.test/"}), calls)
    with pytest.raises(WBError, match="wb_request_rejected"):
        c.request(Source.CATALOG, "secret-wb-token")
    assert len(calls) == 1
    assert calls[0].url.host == "content-api.wildberries.ru"


@pytest.mark.parametrize(
    "status,code,retryable",
    [
        (401, "wb_token_rejected", False),
        (403, "wb_access_denied", False),
        (402, "wb_subscription_required", False),
        (503, "wb_unavailable", True),
    ],
)
def test_upstream_errors_are_redacted(status, code, retryable):
    with pytest.raises(WBError) as caught:
        client(httpx.Response(status, text="token=secret; confidential seller")).request(
            Source.SALES, "secret"
        )
    assert str(caught.value) == code
    assert caught.value.retryable is retryable


def test_retry_after_and_rate_limit_headers_are_respected():
    with pytest.raises(WBError) as caught:
        client(
            httpx.Response(429, headers={"Retry-After": "300", "X-Ratelimit-Retry": "7200"})
        ).request(Source.FINANCE, "secret")
    assert caught.value.retry_after == 7200


@pytest.mark.parametrize("value", [{}, {"cards": None}, {"cards": [], "cursor": {"total": 1}}])
def test_malformed_catalog_does_not_turn_into_empty_success(value):
    with pytest.raises(WBError):
        client(httpx.Response(200, json=value)).page(
            Source.CATALOG, "x", {}, date.today(), date.today()
        )


def test_finance_short_page_requires_another_request_until_204():
    c = client(httpx.Response(200, json=[{"rrdId": 42}]))
    page = c.page(Source.FINANCE, "x", {}, date.today(), date.today())
    assert not page.complete and page.cursor == {
        "rrdId": 42,
        "page_size": INITIAL_FINANCE_PAGE_SIZE,
    }
    with pytest.raises(WBError, match="wb_pagination_stalled"):
        c.page(Source.FINANCE, "x", page.cursor, date.today(), date.today())
    assert (
        client(httpx.Response(204))
        .page(Source.FINANCE, "x", page.cursor, date.today(), date.today())
        .complete
    )


def test_legacy_daily_sales_upgrades_to_bulk_without_deleting_earlier_pages():
    calls = []
    day = date(2026, 10, 1)
    page = client(httpx.Response(200, json=[]), calls).page(
        Source.SALES, "x", {"day": day.isoformat()}, day, day + timedelta(days=1)
    )
    assert calls[0].url.params["flag"] == "0"
    assert page.complete


def test_stocks_full_page_advances_offset():
    page = client(httpx.Response(200, json={"data": {"items": [{}] * STOCK_PAGE_SIZE}})).page(
        Source.STOCKS, "x", {}, date.today(), date.today()
    )
    assert page.cursor == {"offset": STOCK_PAGE_SIZE} and not page.complete


def test_money_exactness_unknown_fields_removed_and_returns_keep_separate_keys():
    row = {
        "saleID": "R1",
        "nmId": 42,
        "date": "2026-10-01",
        "lastChangeDate": "2026-10-02",
        "forPay": Decimal("1234567.89"),
        "buyerPhone": "PRIVATE",
        "token": "secret",
    }
    key, value = normalize(Source.SALES, row)
    assert key == "R1" and value["kind"] == "return"
    assert value["for_pay"] == "1234567.89"
    assert "PRIVATE" not in json.dumps(value) and "secret" not in json.dumps(value)
    assert value["finished_price"] is None
    assert normalize(Source.SALES, {**row, "saleID": "S1"})[0] != key


def test_ciphertext_bound_to_tenant_store_source_and_record(vault):
    aad = context("tenant", "store", Source.SALES, "S1")
    encrypted = vault.seal('{"for_pay":"10.25"}', aad)
    assert vault.open(encrypted, aad) == '{"for_pay":"10.25"}'
    with pytest.raises(InvalidTag):
        vault.open(encrypted, context("other-tenant", "store", Source.SALES, "S1"))


def test_dates_and_duplicate_sources_are_rejected():
    with pytest.raises(ValueError):
        StartSync(sources=[Source.SALES, Source.SALES])
    request = StartSync(sources=[Source.SALES], date_from=moscow_today() - timedelta(days=365))
    assert request.effective_sources() == [Source.SALES, Source.FINANCE]
    request = StartSync(
        sources=[Source.SALES],
        date_from=FINANCE_START,
        date_to=moscow_today() - timedelta(days=365),
    )
    assert request.effective_sources() == [Source.FINANCE]


def test_history_is_source_specific_and_not_limited_to_31_days():
    today = moscow_today()
    maximum = StartSync(date_from=FINANCE_START, date_to=today)
    assert maximum.period_for(Source.FINANCE) == (FINANCE_START, today)
    assert maximum.period_for(Source.SALES) == (today - timedelta(days=89), today)
    assert maximum.period_for(Source.STOCKS) == (None, None)
    assert StartSync(sources=[Source.SALES], date_from=today - timedelta(days=89))
    with pytest.raises(ValueError):
        StartSync(sources=[Source.FINANCE], date_from=FINANCE_START - timedelta(days=1))
    with pytest.raises(ValueError):
        StartSync(date_to=today + timedelta(days=1))


def test_bulk_sales_filters_event_dates_and_preserves_exact_change_cursor():
    calls = []
    day = date(2026, 10, 1)
    changed = "2026-10-02T15:12:13.12345"
    rows = [
        {"saleID": "S1", "date": "2026-09-29", "lastChangeDate": changed},
        {"saleID": "S2", "date": "2026-10-01", "lastChangeDate": changed},
        {"saleID": "S3", "date": "2026-10-02", "lastChangeDate": changed},
    ]
    page = client(httpx.Response(200, json=rows), calls).page(Source.SALES, "x", {}, day, day)
    assert calls[0].url.params["flag"] == "0"
    assert [r["saleID"] for r in page.rows] == ["S2"]
    assert page.cursor == {"last_change": changed} and not page.complete
    terminal = client(httpx.Response(200, json=[]), calls).page(
        Source.SALES, "x", page.cursor, day, day
    )
    assert calls[-1].url.params["dateFrom"] == changed
    assert terminal.complete


def test_inclusive_timestamp_stall_falls_back_to_days_without_skipping_ties():
    changed = "2026-10-01T15:12:13.12345"
    page = client(
        httpx.Response(200, json=[{"date": "2026-10-01", "lastChangeDate": changed}])
    ).page(Source.SALES, "x", {"last_change": changed}, date(2026, 10, 1), date(2026, 10, 2))
    assert not page.complete and page.cursor == {
        "mode": "daily",
        "day": "2026-10-01",
        "bulk_attempted": True,
    }


def test_retry_wait_does_not_confuse_full_burst_reset_with_retry():
    with pytest.raises(WBError) as caught:
        client(
            httpx.Response(429, headers={"X-Ratelimit-Retry": "120", "X-Ratelimit-Reset": "43200"})
        ).request(Source.FINANCE, "x")
    assert caught.value.retry_after == 120


def test_successful_response_observes_token_specific_cooldown():
    page = client(
        httpx.Response(
            200, json=[], headers={"X-Ratelimit-Remaining": "0", "X-Ratelimit-Reset": "7200"}
        )
    ).page(Source.SALES, "x", {}, date.today(), date.today())
    assert page.cooldown_seconds == 7200


def test_downloading_response_consumes_header_cooldown(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr("app.integrations.wildberries.data.time.monotonic", lambda: clock[0])

    class SlowBody(httpx.SyncByteStream):
        def __iter__(self):
            clock[0] += 20
            yield b"[]"

    page = client(
        httpx.Response(
            200,
            stream=SlowBody(),
            headers={"X-Ratelimit-Remaining": "0", "X-Ratelimit-Retry": "120"},
        )
    ).page(Source.SALES, "x", {}, date.today(), date.today())
    assert page.cooldown_seconds == 100


def test_finance_downloads_larger_pages_without_changing_amount_fields():
    calls = []
    client(httpx.Response(204), calls).page(
        Source.FINANCE, "x", {"rrdId": 1}, FINANCE_START, date.today()
    )
    body = json.loads(calls[0].content)
    assert body["limit"] == FINANCE_PAGE_SIZE
    assert body["dateFrom"] == "2024-01-29"


def test_finance_first_preview_page_is_small_then_returns_to_bulk_downloads():
    calls = []
    rows = [{"rrdId": index + 1} for index in range(INITIAL_FINANCE_PAGE_SIZE)]
    page = client(httpx.Response(200, json=rows), calls).page(
        Source.FINANCE, "fixture-token", {}, FINANCE_START, date.today()
    )
    assert json.loads(calls[0].content)["limit"] == 1000
    assert not page.complete
    assert page.cursor["page_size"] == 100000
    client(httpx.Response(204), calls).page(
        Source.FINANCE, "fixture-token", page.cursor, FINANCE_START, date.today()
    )
    assert json.loads(calls[1].content)["limit"] == 100000
