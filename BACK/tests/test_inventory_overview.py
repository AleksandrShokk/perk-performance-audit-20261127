from decimal import Decimal

import httpx
import pytest

from app.integrations.wildberries.data import Source, WBDataClient, WBError
from app.modules.inventory.overview import combine, valuation
from app.modules.sync.normalize import normalize


def test_valuation_counts_stock_not_barcodes_and_zero_cost_is_known():
    rows = [{"chrt_id": "10", "quantity": 3}, {"chrt_id": "10", "quantity": 2}]
    result = valuation(rows, True, {"10": "140.50"}, {"10": "0"}, True)
    assert result.units == 5
    assert result.retail_value == "702.50"
    assert result.cost_value == "0.00" and result.cost_complete


def test_partial_cost_and_price_totals_keep_known_part_and_mark_incomplete():
    rows = [{"chrt_id": "10", "quantity": 3}, {"chrt_id": "11", "quantity": 2}]
    result = valuation(rows, True, {"10": "100"}, {"11": "20"}, True)
    assert result.retail_value == "300.00" and not result.retail_complete
    assert result.cost_value == "40.00" and not result.cost_complete
    hidden = valuation(rows, True, {"10": "100"}, {"11": "20"}, False)
    assert hidden.cost_value is None and not hidden.cost_complete


def test_unknown_channel_never_becomes_zero_or_complete():
    known = valuation([{"chrt_id": "10", "quantity": 2}], True, {"10": "5"}, {}, True)
    unknown = valuation([], False, {}, {}, True)
    total = combine([known, unknown], True)
    assert unknown.units is None and unknown.retail_value is None
    assert total.units is None and total.retail_value == "10.00"
    assert not total.retail_complete and not total.cost_complete
    zero = valuation([], True, {}, {}, True)
    assert zero.units == 0 and zero.cost_value == "0.00" and zero.retail_complete


def test_seller_discount_price_is_retained_per_size_without_club_or_wb_discount():
    key, row = normalize(
        Source.PRICES,
        {
            "nmID": 42,
            "currencyIsoCode4217": "RUB",
            "sizes": [
                {
                    "sizeID": 10,
                    "price": 1000,
                    "discountedPrice": Decimal("700.50"),
                    "clubDiscountedPrice": 500,
                }
            ],
        },
    )
    assert key == "42" and row["prices"] == {"10": "700.50"}
    assert "clubDiscountedPrice" not in str(row)
    with pytest.raises(WBError):
        normalize(Source.PRICES, {"nmID": 42, "sizes": [{"sizeID": 10, "discountedPrice": -1}]})


def test_price_page_uses_fixed_read_endpoint_and_paginates_until_empty():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(
            200, json={"data": {"listGoods": [{"nmID": 42}] if len(requests) == 1 else []}}
        )

    client = WBDataClient(httpx.MockTransport(handler))
    first = client.page(Source.PRICES, "fake", {}, None, None)
    second = client.page(Source.PRICES, "fake", first.cursor, None, None)
    assert not first.complete and second.complete
    assert (
        requests[0].method == "GET"
        and requests[0].url.host == "discounts-prices-api.wildberries.ru"
    )
    assert requests[1].url.params["offset"] == "1000"


def test_fbs_reads_only_fbs_warehouses_and_uses_size_ids():
    requests = []

    def handler(request):
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(
                200,
                json=[
                    {"id": 1, "name": "Свой склад", "deliveryType": 1},
                    {"id": 2, "name": "DBS", "deliveryType": 2},
                ],
            )
        return httpx.Response(200, json={"stocks": [{"chrtId": 10, "amount": 7}]})

    client = WBDataClient(httpx.MockTransport(handler))
    first = client.page(Source.FBS, "fake", {}, None, None)
    second = client.page(
        Source.FBS,
        "fake",
        {
            **first.cursor,
            "_sizes": [{"nm_id": "42", "chrt_id": "10"}, {"nm_id": "42", "chrt_id": "11"}],
        },
        None,
        None,
    )
    assert second.complete and [row["quantity"] for row in second.rows] == [7, 0]
    assert requests[1].method == "POST" and requests[1].url.path == "/api/v3/stocks/1"
    assert b"chrtIds" in requests[1].content and b"skus" not in requests[1].content
    assert "_sizes" not in second.cursor
    key, row = normalize(Source.FBS, second.rows[0])
    assert key == "42:10:1" and row["quantity"] == 7


def test_empty_positions_do_not_make_unknown_stock_value_zero():
    unknown = valuation([{"chrt_id": "10", "quantity": 2}], True, {}, {}, True)
    empty = valuation([], True, {}, {}, True)
    total = combine([unknown, empty], True)
    assert total.units == 2
    assert total.cost_value is None and total.retail_value is None
    assert not total.cost_complete and not total.retail_complete
    # A real zero cost is still meaningful, and completely empty stock is worth zero.
    free = valuation([{"chrt_id": "10", "quantity": 2}], True, {}, {"10": "0"}, True)
    assert combine([free, empty], True).cost_value == "0.00"
    assert combine([empty], True).cost_value == "0.00"
