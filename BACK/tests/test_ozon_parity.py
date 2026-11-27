import json
from datetime import date
from decimal import Decimal

import httpx
import pytest
from test_ozon_finance import DAY, accrual, cash

from app.integrations.ozon.supplies import BUNDLE, COUNTER, GET, LIST, SupplyClient
from app.integrations.ozon.traffic import TrafficClient
from app.integrations.ozon.transport import OzonImportError
from app.modules.finance.ozon_facts import normalize
from app.modules.finance.xlsx import HEADERS, build_template, read_rows


def test_native_traffic_and_confirmed_empty_days():
    def handler(request):
        assert request.url.path == "/v1/analytics/data"
        body = json.loads(request.content)
        assert body["metrics"] == ["hits_view", "hits_view_pdp", "hits_tocart"] and body[
            "dimension"
        ] == ["sku", "day"]
        return httpx.Response(
            200,
            json={
                "result": {
                    "data": [
                        {
                            "dimensions": [{"id": "101"}, {"id": "2026-10-01"}],
                            "metrics": [1000, 100, 20],
                        }
                    ],
                    "totals": [1000, 100, 20],
                }
            },
        )

    result = TrafficClient("1", "test", transport=httpx.MockTransport(handler)).days(
        DAY, date(2026, 10, 2)
    )
    assert result[DAY] == {
        "impressions": 1000,
        "opens": 100,
        "carts": 20,
        "products": {"101": {"impressions": 1000, "opens": 100, "carts": 20}},
        "version": 2,
    }
    assert result[date(2026, 10, 2)] == {
        "impressions": 0,
        "opens": 0,
        "carts": 0,
        "products": {},
        "version": 2,
    }


@pytest.mark.parametrize("metrics", [[True, 1], [-1, 2], [1.1, 2]])
def test_malformed_traffic_never_becomes_zero(metrics):
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={"result": {"data": [{"dimensions": [{"id": "2026-10-01"}], "metrics": metrics}]}},
        )
    )
    with pytest.raises(OzonImportError):
        TrafficClient("1", "test", transport=transport).days(DAY, DAY)


def supply_raw():
    return {
        "order_id": 1,
        "order_number": "SUP-1",
        "created_date": "2026-10-01T12:00:00Z",
        "state": "COMPLETED",
        "state_updated_date": "2026-10-02T12:00:00Z",
        "drop_off_warehouse": {"name": "Warehouse", "address": "private address"},
        "timeslot": {
            "timeslot": {"from": "2026-10-01T22:00:00Z"},
            "timezone_info": {"iana_name": "Europe/Moscow"},
        },
        "supplies": [
            {
                "supply_id": 2,
                "bundle_id": "bundle",
                "storage_warehouse": None,
                "macrolocal_cluster_id": "cluster",
            }
        ],
    }


def test_supplies_follow_native_quantities_status_and_warehouse_timezone():
    calls = []

    def handler(request):
        calls.append(request.url.path)
        response = {
            COUNTER: {"items": [{"order_state": "ORDER_STATE_COMPLETED", "count": 1}]},
            LIST: {"order_ids": [1], "last_id": ""},
            GET: {"orders": [supply_raw()]},
            BUNDLE: {
                "items": [{"sku": 101, "quantity": 5}, {"sku": 102, "quantity": 6}],
                "has_next": False,
                "last_id": "",
            },
        }
        return httpx.Response(200, json=response[request.url.path])

    result = SupplyClient("1", "test", transport=httpx.MockTransport(handler)).snapshot(
        date(2026, 10, 3)
    )
    row = result["items"][0]
    assert row["quantity"] == 11 and row["status"] == "accepted"
    assert row["planned_date"] == "2026-10-02" and row["accepted_quantity"] is None
    assert row["display_number"] == "SUP-1" and row["marketplace"] == "ozon"
    assert "private" not in json.dumps(result)
    assert set(calls) == {COUNTER, LIST, GET, BUNDLE}


def test_product_lines_plus_unassigned_reconcile_to_accrual_total():
    sale = accrual()
    non_item = {
        "accrual_id": 2,
        "date": str(DAY),
        "total_amount": cash("-10"),
        "unit_number": "private",
        "accrued_category": "NON_ITEM",
        "non_item_fee": {"type_id": 99, "accrued": cash("-10")},
    }
    result = normalize(
        [sale, non_item],
        DAY,
        {
            32: {"name": "Logistic", "title": "Logistics"},
            99: {"name": "Placements", "title": "Storage"},
        },
    )
    products = result["product_details"]["RUB"]
    assert products["101"]["sales"] == 1
    assert sum(
        (Decimal(line["amount"]) for detail in products.values() for line in detail["lines"]),
        Decimal(0),
    ) == Decimal(result["currencies"]["RUB"]["settlement"])
    assert products[""]["lines"][0]["amount"] == "-10.00"
    assert "private" not in json.dumps(result["product_details"])


def test_generated_xlsx_preserves_identifiers_and_does_not_create_formulas():
    rows = [("00101", "000001", "12,34", "2026-10-01", "RUB")]
    payload = build_template(HEADERS, rows)
    assert read_rows(payload) == [(2, list(rows[0]))]
