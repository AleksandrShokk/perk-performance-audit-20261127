import json
from decimal import Decimal

import httpx
import pytest

from app.integrations.ozon.catalog import normalize
from app.integrations.ozon.catalog_client import (
    ATTRIBUTES,
    DEFINITIONS,
    INFO,
    LIST,
    PRICES,
    STOCKS,
    CatalogClient,
    ImportError,
)


def fixtures(pid=1, group=5):
    return (
        {
            "id": pid,
            "sku": pid + 100,
            "offer_id": f"Article-{pid}",
            "name": "Same title",
            "description_category_id": 1,
            "type_id": 2,
            "model_info": {"model_id": group},
            "images": ["https://cdn.ozon.ru/photo.jpg"],
            "barcodes": [str(pid)],
            "sources": [{"sku": pid + 200}],
        },
        {
            "id": pid,
            "attributes": [
                {"id": 10096, "values": [{"value": "чёрный"}]},
                {"id": 777, "values": [{"value": "XL"}]},
            ],
        },
        {
            "product_id": pid,
            "stocks": [
                {"type": "fbo", "present": 8, "reserved": 3, "sku": pid + 100},
                {"type": "fbs", "present": 2, "reserved": 1, "sku": pid + 200},
                {"type": "rfbs", "present": 4, "reserved": 0},
            ],
        },
        {
            "product_id": pid,
            "price": {
                "marketing_seller_price": Decimal("123.45"),
                "price": 150,
                "retail_price": 90,
                "currency_code": "RUB",
            },
        },
    )


DEFS = {"10096": "Цвет товара", "777": "Российский размер"}


def payload(pid=1, group=5):
    return normalize(*fixtures(pid, group), DEFS)


def test_normalizes_exact_provider_facts_and_seller_price():
    row = payload()
    assert row["external_id"] == "1" and row["marketplace_code"] == "101"
    assert row["sku_aliases"] == ["201"]
    assert row["colors"] == ["чёрный"] and row["size"] == "XL"
    assert row["seller_price"] == "123.45" and row["currency"] == "RUB"
    assert row["channels"]["fbo"] == {"quantity": 8, "reserved": 3}
    assert row["channels"]["fbs"]["quantity"] == 2
    assert row["channels"]["rfbs"]["quantity"] == 4
    assert "nm_id" not in row and "chrt_id" not in row


def test_missing_price_and_size_stay_unknown_instead_of_inferred():
    info, attrs, stocks, prices = fixtures()
    prices["price"] = {"price": 150, "retail_price": 80, "currency_code": "RUB"}
    row = normalize(info, attrs, stocks, prices, {})
    assert row["seller_price"] is None and row["size"] == ""
    assert row["colors"] == []


@pytest.mark.parametrize("value", [-1, "8", True])
def test_rejects_invalid_stock_instead_of_publishing_zero(value):
    info, attrs, stocks, prices = fixtures()
    stocks["stocks"][0]["present"] = value
    with pytest.raises(ValueError):
        normalize(info, attrs, stocks, prices, DEFS)


def test_new_total_items_and_cursor_are_used_not_deprecated_total():
    calls = []

    def transport(request):
        body = json.loads(request.content)
        calls.append(body["last_id"])
        return httpx.Response(
            200,
            json={
                "result": {
                    "items": [{"product_id": 1 if not body["last_id"] else 2}],
                    "last_id": "next" if not body["last_id"] else "",
                    "total_items": 2,
                    "total": 0,
                }
            },
        )

    client = CatalogClient("1", "synthetic", transport=httpx.MockTransport(transport))
    assert [row["product_id"] for row in client.paged(LIST, {}, result=True, cursor="last_id")] == [
        1,
        2,
    ]
    assert calls == ["", "next"]


@pytest.mark.parametrize(
    "rows,token,total,code",
    [
        ([], "", 2, "ozon_incomplete_response"),
        ([{"product_id": 1}], "repeated", 5, "ozon_cursor_repeated"),
    ],
)
def test_rejects_early_end_and_cursor_loops(rows, token, total, code):
    transport = httpx.MockTransport(
        lambda _: httpx.Response(
            200,
            json={
                "result": {
                    "items": rows,
                    "last_id": token,
                    "total_items": total,
                }
            },
        )
    )
    client = CatalogClient("1", "synthetic", transport=transport)
    with pytest.raises(ImportError) as error:
        list(client.paged(LIST, {}, result=True, cursor="last_id"))
    assert error.value.code == code


def test_complete_catalog_joins_by_id_not_response_order_and_loads_category_once():
    definitions_calls, progress = [], []

    def transport(request):
        path = request.url.path
        first, second = fixtures(1), fixtures(2)
        if path == LIST:
            data = {"result": {"items": [{"product_id": 1}, {"product_id": 2}], "total_items": 2}}
        elif path == INFO:
            data = {"items": [second[0], first[0]]}
        elif path == DEFINITIONS:
            definitions_calls.append(path)
            data = {"result": [{"id": key, "name": value} for key, value in DEFS.items()]}
        else:
            index = {ATTRIBUTES: 1, STOCKS: 2, PRICES: 3}[path]
            rows = [second[index], first[index]]
            data = (
                {"result": rows, "total": 2}
                if path == ATTRIBUTES
                else {"items": rows, "total_items": 2}
            )
        return httpx.Response(200, content=json.dumps(data, default=str))

    client = CatalogClient("1", "synthetic", transport=httpx.MockTransport(transport))
    rows = client.fetch(normalize, progress.append)
    assert [row["external_id"] for row in rows] == ["1", "2"]
    assert len(definitions_calls) == 1 and progress == [2]


@pytest.mark.parametrize(
    "status,code",
    [
        (401, "ozon_access_denied"),
        (403, "ozon_access_denied"),
        (429, "ozon_rate_limited"),
        (503, "ozon_unavailable"),
        (302, "ozon_unavailable"),
    ],
)
def test_remote_errors_never_leak_provider_body_or_credentials(status, code):
    client = CatalogClient(
        "1",
        "secret-value",
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                status, json={"message": "secret-value"}, headers={"Retry-After": "999999"}
            )
        ),
    )
    with pytest.raises(ImportError) as error:
        client.read(LIST, {})
    assert error.value.code == code and "secret-value" not in str(error.value)
    assert error.value.retry_after <= 3600


def test_unpublished_optional_metadata_does_not_block_confirmed_catalog_and_stock():
    original, attrs, stock, price = fixtures()
    original.pop("sku")
    original["sources"] = []
    original["description_category_id"] = 0

    def transport(request):
        if request.url.path == LIST:
            data = {"result": {"items": [{"product_id": 1}], "total_items": 1}}
        elif request.url.path == INFO:
            data = {"items": [original]}
        elif request.url.path == ATTRIBUTES:
            data = {"result": [], "total": 0}
        elif request.url.path == STOCKS:
            data = {"items": [stock], "total_items": 1}
        elif request.url.path == PRICES:
            data = {"items": [], "total_items": 0}
        else:
            raise AssertionError("No category schema is needed for an empty attribute list")
        return httpx.Response(200, json=data)

    client = CatalogClient("1", "synthetic", transport=httpx.MockTransport(transport))
    rows = client.fetch(normalize)
    assert len(rows) == 1
    assert rows[0]["seller_price"] is None and rows[0]["colors"] == []
    assert rows[0]["marketplace_code"] == ""  # Do not pretend product_id is an Ozon SKU.
    assert rows[0]["channels"]["fbo"]["quantity"] == 8
