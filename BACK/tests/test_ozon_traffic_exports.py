import copy
import json
from datetime import date

import httpx
import pytest

from app.integrations.ozon import traffic
from app.integrations.ozon.transport import OzonImportError
from app.modules.insights.ozon_traffic import enrich_products

DAY = date(2026, 10, 1)


class Checkpoint:
    def __init__(self):
        self.state = {"completed": [], "rows": []}

    def load(self, keys):
        return copy.deepcopy(self.state)

    def save(self, value):
        self.state = copy.deepcopy(value)

    def clear(self):
        self.state = {"completed": [], "rows": []}


def test_pagination_resumes_after_rate_limit_without_repeating_first_page(monkeypatch):
    monkeypatch.setattr(traffic, "PAGE_SIZE", 2)
    checkpoint, offsets = Checkpoint(), []

    def handler(request):
        offset = json.loads(request.content)["offset"]
        offsets.append(offset)
        ids = [1, 2] if offset == 0 else [3]
        return httpx.Response(
            200,
            json={
                "result": {
                    "data": [
                        {"dimensions": [{"id": str(sku)}, {"id": str(DAY)}], "metrics": [10, 5, 1]}
                        for sku in ids
                    ],
                    "totals": [30, 15, 3],
                }
            },
        )

    attempts = 0

    def wait():
        nonlocal attempts
        attempts += 1
        if attempts > 1:
            raise OzonImportError("ozon_rate_limited")

    with pytest.raises(OzonImportError):
        traffic.TrafficClient(
            "1", "test", checkpoint=checkpoint, transport=httpx.MockTransport(handler), wait=wait
        ).days(DAY, DAY)
    result = traffic.TrafficClient(
        "1", "test", checkpoint=checkpoint, transport=httpx.MockTransport(handler)
    ).days(DAY, DAY)
    assert offsets == [0, 2]
    assert result[DAY]["opens"] == 15 and result[DAY]["impressions"] == 30
    assert len(result[DAY]["products"]) == 3


class DayCheckpoints:
    """Like the Redis checkpoint: one saved state per requested day."""

    def __init__(self):
        self.states, self.current = {}, None

    def load(self, keys):
        self.current = tuple(keys)
        return copy.deepcopy(self.states.get(self.current, {"completed": [], "rows": []}))

    def save(self, value):
        self.states[self.current] = copy.deepcopy(value)

    def clear(self):
        self.states.pop(self.current, None)


def test_finished_days_survive_a_rate_limit_and_a_bad_day_restarts_alone():
    second = date(2026, 10, 2)
    checkpoint, requested, broken = DayCheckpoints(), [], [True]

    def handler(request):
        day = json.loads(request.content)["date_from"]
        requested.append(day)
        totals = [999, 5, 1] if day == str(second) and broken[0] else [10, 5, 1]
        return httpx.Response(
            200,
            json={
                "result": {
                    "data": [{"dimensions": [{"id": "1"}, {"id": day}], "metrics": [10, 5, 1]}],
                    "totals": totals,
                }
            },
        )

    with pytest.raises(OzonImportError):
        traffic.TrafficClient(
            "1", "test", checkpoint=checkpoint, transport=httpx.MockTransport(handler)
        ).days(DAY, second)
    broken[0] = False
    result = traffic.TrafficClient(
        "1", "test", checkpoint=checkpoint, transport=httpx.MockTransport(handler)
    ).days(DAY, second)
    # The first day was not requested again; only the inconsistent day was.
    assert requested == [str(DAY), str(second), str(second)]
    assert result[DAY]["opens"] == 5 and result[second]["opens"] == 5


def test_inconsistent_provider_totals_never_publish_a_partial_page():
    response = {
        "result": {
            "data": [{"dimensions": [{"id": "1"}, {"id": str(DAY)}], "metrics": [10, 5, 1]}],
            "totals": [100, 50, 10],
        }
    }
    with pytest.raises(OzonImportError):
        traffic.TrafficClient(
            "1", "test", transport=httpx.MockTransport(lambda r: httpx.Response(200, json=response))
        ).days(DAY, DAY)


def test_product_traffic_uses_native_skus_and_recomputes_period_conversions():
    products = [{"marketplace_code": "1", "orders": 3}]
    days = {
        "2026-10-01": {
            "version": 2,
            "products": {
                "1": {"impressions": 100, "opens": 10, "carts": 5},
                "2": {"impressions": 40, "opens": 8, "carts": 2},
            },
        },
        "2026-10-02": {
            "version": 2,
            "products": {"1": {"impressions": 200, "opens": 30, "carts": 10}},
        },
    }
    enrich_products(products, days, 2, True)
    assert products[0]["opens"] == 40 and products[0]["impressions"] == 300
    assert (
        products[0]["add_to_cart_percent"] == "37.5"
        and products[0]["cart_to_order_percent"] == "20.0"
    )
    assert products[1]["orders"] == 0 and products[1]["opens"] == 8


def test_old_or_partial_traffic_never_becomes_confirmed_zero():
    products = [{"marketplace_code": "1", "orders": 3, "opens": None}]
    enrich_products(products, {str(DAY): {"opens": 20, "carts": 2}}, 1, True)
    assert products[0]["opens"] is None
    enrich_products(products, {str(DAY): {"version": 2, "products": {}}}, 2, True)
    assert products[0]["opens"] is None


def test_partial_sku_traffic_does_not_divide_full_period_orders_by_partial_carts():
    products = [{"marketplace_code": "1", "orders": 10}]
    days = {
        str(DAY): {"version": 2, "products": {"1": {"impressions": 100, "opens": 20, "carts": 4}}}
    }
    enrich_products(products, days, 7, True)
    assert products[0]["opens"] == 20 and products[0]["add_to_cart_percent"] == "20.0"
    assert products[0]["cart_to_order_percent"] is None
    assert products[0]["open_to_order_percent"] is None
