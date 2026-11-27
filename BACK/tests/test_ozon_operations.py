import json
from datetime import date
from decimal import Decimal

import httpx
import pytest

from app.integrations.ozon.operations import FBO, FBS, RETURNS, OperationsClient
from app.integrations.ozon.transport import OzonImportError
from app.modules.insights.ozon_sales import aggregate, combine, posting, returned
from app.modules.inventory.ozon_cover import normalize, portfolio, position


def order_raw(
    number="order-1", quantity=10, status="delivered", day="2026-10-01", price="100.10", sku=101
):
    return {
        "posting_number": number,
        "status": status,
        "created_at": day + "T12:00:00Z",
        "in_process_at": day + "T12:00:00Z",
        "customer": {"name": "Private buyer", "phone": "private-phone"},
        "financial_data": {
            "products": [
                {"product_id": sku, "customer_price": {"amount": price, "currency": "RUB"}}
            ]
        },
        "products": [
            {"sku": sku, "quantity": quantity, "price": {"amount": price, "currency": "RUB"}}
        ],
    }


def return_raw(number="order-1", quantity=1, rid=1, confirmed=True, exemplars=None):
    return {
        "id": rid,
        "posting_number": number,
        "product": {"sku": 101, "quantity": quantity},
        "logistic": {"final_moment": "2026-10-23T12:00:00Z" if confirmed else None},
        "exemplars": exemplars or [],
        "place": {"address": "private-address"},
    }


def test_delivery_and_return_stay_on_original_order_day_with_exact_money():
    days = aggregate(
        [posting(order_raw(), "fbo")],
        [returned(return_raw())],
        date(2026, 10, 1),
        date(2026, 10, 2),
    )
    first = days[date(2026, 10, 1)]["totals"]
    assert first["orders"] == 10 and first["buyouts"] == 9 and first["cancellations"] == 1
    assert first["orders_amount"] == "1001.00" and first["buyouts_amount"] == "900.90"
    assert first["cancellations_amount"] == "100.10" and first["buyout_percent"] == "90.0"
    assert days[date(2026, 10, 2)]["totals"]["orders"] == 0
    assert first["opens"] is None and first["carts"] is None
    assert "private-" not in json.dumps(list(days.values()))


def test_cancellation_and_return_of_same_posting_are_not_added_twice():
    data = aggregate(
        [posting(order_raw(status="cancelled"), "fbs")],
        [returned(return_raw(quantity=10))],
        date(2026, 10, 1),
        date(2026, 10, 1),
    )
    totals = data[date(2026, 10, 1)]["totals"]
    assert totals["orders"] == totals["cancellations"] == 10 and totals["buyouts"] == 0


def test_opened_claim_is_not_a_confirmed_return_and_duplicate_exemplars_count_once():
    rows = [
        returned(return_raw(rid=1, exemplars=[{"exemplar_id": 5}])),
        returned(return_raw(rid=2, exemplars=[{"exemplar_id": 5}])),
        returned(return_raw(rid=3, confirmed=False)),
    ]
    data = aggregate([posting(order_raw(), "fbo")], rows, date(2026, 10, 1), date(2026, 10, 1))
    assert data[date(2026, 10, 1)]["totals"]["buyouts"] == 9


def test_pending_is_not_delivery_and_missing_or_mixed_money_is_unknown():
    raw = order_raw(status="delivering", price=None)
    data = aggregate([posting(raw, "fbs")], [], date(2026, 10, 1), date(2026, 10, 1))
    totals = data[date(2026, 10, 1)]["totals"]
    assert totals["buyouts"] == 0 and totals["orders_amount"] is None
    assert totals["buyouts_amount"] == "0.00"
    other = order_raw(number="order-2", sku=102)
    other["financial_data"]["products"][0]["customer_price"]["currency"] = "USD"
    data = aggregate(
        [posting(order_raw(), "fbo"), posting(other, "fbs")],
        [],
        date(2026, 10, 1),
        date(2026, 10, 1),
    )
    assert data[date(2026, 10, 1)]["totals"]["orders_amount"] is None
    assert data[date(2026, 10, 1)]["totals"]["orders"] == 20


def test_external_logistics_order_is_excluded_and_unknown_status_fails_closed():
    raw = order_raw()
    raw["external_order"] = {"is_external": True}
    assert posting(raw, "fbo") is None
    raw["status"] = "new-unknown-terminal-status"
    with pytest.raises(OzonImportError):
        posting(raw, "fbo")


def test_moscow_day_and_known_empty_days_do_not_depend_on_device_timezone():
    raw = order_raw()
    raw["created_at"] = "2026-09-30T22:30:00Z"
    assert posting(raw, "fbo")["day"] == date(2026, 10, 1)
    days = aggregate([], [], date(2026, 10, 1), date(2026, 10, 3))
    assert len(days) == 3 and all(value["totals"]["orders"] == 0 for value in days.values())
    assert combine([])["orders"] is None


def test_current_cursor_methods_and_50_posting_return_batches():
    seen = []

    def transport(request):
        body = json.loads(request.content)
        seen.append((request.url.path, body))
        if request.url.path == FBO:
            return httpx.Response(
                200,
                json={
                    "postings": [order_raw()]
                    if not body["cursor"]
                    else [order_raw(number="order-2")],
                    "has_next": not body["cursor"],
                    "cursor": "next" if not body["cursor"] else "",
                },
            )
        if request.url.path == FBS:
            return httpx.Response(200, json={"postings": [], "has_next": False, "cursor": ""})
        return httpx.Response(200, json={"returns": [], "has_next": False})

    client = OperationsClient("1", "synthetic", transport=httpx.MockTransport(transport))
    orders, returns = client.sales(date(2026, 10, 1), date(2026, 10, 1), posting, returned)
    assert len(orders) == 2 and not returns
    assert all("customer" not in row and "products" not in row for row in orders)
    assert [path for path, _ in seen][:3] == [FBO, FBO, FBS]
    assert all(body["with"]["financial_data"] is True for path, body in seen if path != RETURNS)
    seen.clear()
    list(client.returns([f"posting-{index}" for index in range(121)]))
    assert [len(body["filter"]["posting_numbers"]) for _, body in seen] == [50, 50, 21]


def test_cursor_loop_and_duplicate_postings_reject_incomplete_snapshot():
    client = OperationsClient(
        "1",
        "synthetic",
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200, json={"postings": [order_raw()], "has_next": True, "cursor": "same"}
            )
        ),
    )
    with pytest.raises(OzonImportError):
        list(client.postings(FBO, date(2026, 10, 1), date(2026, 10, 1)))
    with pytest.raises(OzonImportError):
        client.sales(date(2026, 10, 1), date(2026, 10, 1), posting, returned)


def stock_row(sku=101, warehouse=1, available=10, ads="1", idc="10", grade="ACTUAL"):
    return {
        "sku": sku,
        "warehouse_id": warehouse,
        "cluster_id": 1,
        "placement_zone": "SORT",
        "available_stock_count": available,
        "ads": Decimal(ads) if ads is not None else None,
        "idc": Decimal(idc) if idc is not None else None,
        "turnover_grade": grade,
    }


def test_global_ads_and_idc_are_not_added_for_each_warehouse():
    facts = normalize(
        [stock_row(available=4), stock_row(warehouse=2, available=6), stock_row(available=4)]
    )
    assert facts["101"]["available"] == 10 and facts["101"]["ads"] == "1"
    assert position(facts, ["101", "201"])[0] == "10"
    assert portfolio(facts, ["101"]) == ("10.00", False)


def test_portfolio_uses_stock_over_demand_and_never_average_coverage_days():
    facts = normalize(
        [
            stock_row(101, available=10, ads="1", idc="10"),
            stock_row(102, available=90, ads="3", idc="30"),
        ]
    )
    assert portfolio(facts, ["101", "102"]) == ("25.00", False)
    assert portfolio(facts, ["999"]) == ("25.00", True)


def test_missing_demand_stays_unknown_and_native_no_sales_is_explicit():
    facts = normalize([stock_row(ads="0", idc=None, grade="NO_SALES")])
    assert position(facts, ["101"]) == (None, "no_sales")
    assert portfolio(facts, ["101"])[0] is None
    assert position({}, ["101"], True) == (None, "loading")
    facts = normalize([stock_row(ads=None, idc=None)])
    assert portfolio(facts, ["101"]) == (None, True)


def test_conflicting_native_warehouse_values_are_not_guessed():
    with pytest.raises(ValueError):
        normalize([stock_row(available=5), stock_row(available=8)])


def test_ozon_cohort_uses_processing_date_even_when_a_draft_is_days_older():
    raw = order_raw(day="2026-10-01")
    raw["created_at"] = "2026-09-28T12:00:00Z"
    assert posting(raw, "fbo")["day"] == date(2026, 10, 1)


def test_sold_out_positions_do_not_shorten_stock_cover_of_other_products():
    rows = normalize(
        [
            stock_row(101, available=10, ads="1", idc="10"),
            stock_row(102, available=0, ads="100", idc="0"),
        ]
    )
    assert portfolio(rows, ["101"]) == ("10.00", False)
