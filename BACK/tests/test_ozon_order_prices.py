import json
from datetime import date

import httpx
import pytest
from test_ozon_operations import order_raw

from app.integrations.ozon.operations import FBO, FBS, RETURNS, OperationsClient
from app.integrations.ozon.order_prices import CREATE, INFO, OrderPrices, apply, parse
from app.integrations.ozon.transport import OzonImportError
from app.modules.insights.ozon_sales import aggregate, posting, reprice

CSV = (
    "Номер отправления;SKU;Количество;Оплачено покупателем;Код валюты покупателя\n"
    "order-1;101;2;700.25;RUB\n"
).encode("utf-8-sig")


def test_both_price_modes_and_buyer_price_precedence_for_historical_orders():
    raw = order_raw(day="2025-02-01", quantity=2, price="1200")
    raw["financial_data"]["products"][0].pop("customer_price")
    orders = [posting(raw, "fbo")]
    apply(orders, parse(CSV))
    day = date(2025, 2, 1)
    data = aggregate(orders, [], day, day)[day]
    quote = {("order-1", "101"): {"price": "650", "currency": "RUB"}}
    customer = reprice(data, quote, "RUB")
    seller = reprice(data, quote, "RUB", "seller")
    assert customer["totals"]["orders_amount"] == "1400.50"
    assert seller["totals"]["orders_amount"] == "2400.00"
    assert customer["totals"]["buyouts_amount"] == "1400.50"
    assert not customer["totals"]["partial_amounts"]
    assert customer["totals"]["orders"] == seller["totals"]["orders"] == 2
    assert "Private buyer" not in json.dumps(data)


def test_no_currency_guessing_or_false_full_sum():
    data = aggregate(
        [posting(order_raw(price="25", quantity=1), "fbs")],
        [],
        date(2026, 10, 1),
        date(2026, 10, 1),
    )[date(2026, 10, 1)]
    data["price_items"][0]["currency"] = "BYN"
    result = reprice(data, {}, "RUB")
    assert result["totals"]["orders_amount"] is None
    assert "orders_amount" in result["totals"]["partial_amounts"]
    result = reprice(data, {("order-1", "101"): {"price": "700", "currency": "RUB"}}, "RUB")
    assert result["totals"]["orders_amount"] == "700.00"


def test_report_join_never_invents_missing_items_or_averages_conflicting_prices():
    orders = [posting(order_raw(quantity=3), "fbo")]
    with pytest.raises(OzonImportError, match="ozon_price_report_incomplete"):
        apply(orders, parse(CSV))
    orders = [posting(order_raw(quantity=2), "fbo")]
    with pytest.raises(OzonImportError, match="ozon_price_report_conflict"):
        apply(orders, {("order-1", "101"): [(1, 700, "RUB"), (1, 800, "RUB")]})
    with pytest.raises(ValueError):
        parse(CSV.replace(b"700.25", b"NaN"))


def test_fbo_prices_are_fetched_from_official_report_without_leaking_credentials():
    calls = []

    def handle(request):
        calls.append(request.url.path)
        if request.method == "GET":
            assert "Api-Key" not in request.headers and "Client-Id" not in request.headers
            return httpx.Response(200, content=CSV)
        if request.url.path == FBO:
            raw = order_raw(quantity=2)
            raw["financial_data"]["products"][0].pop("customer_price")
            return httpx.Response(200, json={"postings": [raw], "has_next": False})
        if request.url.path == FBS:
            return httpx.Response(200, json={"postings": [], "has_next": False})
        if request.url.path == CREATE:
            assert json.loads(request.content)["with"]["customer_data"] is False
            return httpx.Response(200, json={"result": {"code": "test"}})
        if request.url.path == INFO:
            return httpx.Response(
                200,
                json={"result": {"status": "success", "file": "https://ir-3.ozone.ru/report.csv"}},
            )
        assert request.url.path == RETURNS
        return httpx.Response(200, json={"returns": [], "has_next": False})

    from app.modules.insights.ozon_sales import returned

    reader = OperationsClient(
        "synthetic", "private-key", transport=httpx.MockTransport(handle), pause=lambda _: None
    )
    rows, _ = reader.sales(date(2026, 10, 1), date(2026, 10, 1), posting, returned)
    assert rows[0]["items"][0]["price"] == "700.25"
    assert calls.count(CREATE) == 1


@pytest.mark.parametrize(
    "url",
    [
        "http://ir-3.ozone.ru/file",
        "https://ozone.ru.attacker.test/file",
        "https://localhost/file",
        "https://<REDACTED>@ir-3.ozone.ru/file",
    ],
)
def test_signed_report_download_rejects_untrusted_destinations(url):
    reader = OrderPrices("1", "test", pause=lambda _: None)
    with pytest.raises(OzonImportError, match="ozon_invalid_report_url"):
        reader.download(url)
