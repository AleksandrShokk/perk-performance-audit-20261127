import json
from datetime import date

import httpx
import pytest

from app.integrations.ozon.finance import TYPES, FinanceClient
from app.integrations.ozon.transport import OzonImportError
from app.modules.finance.ozon_facts import normalize
from app.modules.insights.ozon_sales import aggregate, posting, reprice

DAY = date(2026, 10, 1)


def cash(amount, currency="RUB"):
    return {"amount": str(amount), "currency": currency}


def accrual(rid=1, sale="1000", commission="-200", price="700", quantity=1):
    return {
        "accrual_id": rid,
        "date": str(DAY),
        "total_amount": cash(str(int(sale) + int(commission) - 50)),
        "unit_number": "posting-private-1",
        "accrued_category": "POSTING",
        "posting": {
            "products": [
                {
                    "sku": 101,
                    "quantity": quantity,
                    "commission": {
                        "sale_amount": cash(sale),
                        "seller_price": cash("1000"),
                        "sale_price": cash(price),
                        "commission": cash(commission),
                        "sale_commission": cash("-350"),
                        "bonus": cash("150"),
                        "coinvestment": cash("0"),
                    },
                    "delivery": {
                        "total_accrued": cash("-50"),
                        "services": [{"type_id": 32, "accrued": cash("-50")}],
                    },
                }
            ]
        },
    }


def test_exact_ledger_does_not_add_compensation_embedded_in_final_commission_twice():
    raw = accrual()
    raw["buyer"] = {"phone": "private-phone"}
    data = normalize([raw], DAY, {32: {"name": "Logistic", "title": "Логистика"}})
    facts = data["currencies"]["RUB"]
    assert facts["seller_revenue"] == "1000.00" and facts["buyer_revenue"] == "700.00"
    assert facts["settlement"] == "750.00"
    assert {line["group"]: line["amount"] for line in facts["lines"]} == {
        "sales": "1000.00",
        "fees": "-200.00",
        "logistics": "-50.00",
    }
    assert "private-phone" not in json.dumps(data)
    assert data["realizations"][0]["price"] == "700.00"


def test_duplicate_accrual_id_is_idempotent_but_conflicting_corrections_fail():
    value = accrual()
    assert normalize([value, value], DAY, {})["records"] == 1
    with pytest.raises(ValueError):
        normalize([value, {**value, "total_amount": cash("900")}], DAY, {})


def test_returns_reverse_seller_and_customer_income_and_do_not_replace_original_unit_price():
    data = normalize([accrual(sale="-1000", commission="200")], DAY, {})
    facts = data["currencies"]["RUB"]
    assert facts["seller_revenue"] == "-1000.00" and facts["buyer_revenue"] == "-700.00"
    assert facts["settlement"] == "-850.00" and not data["realizations"]


def test_all_charge_kinds_are_retained_and_unknown_types_are_not_lost():
    types = {41: {"name": "PayPerClick", "title": "Оплата за клик"}}
    rows = [
        {
            "accrual_id": i,
            "date": str(DAY),
            "total_amount": cash("-10"),
            "accrued_category": category,
            **value,
        }
        for i, (category, value) in enumerate(
            [
                ("NON_ITEM", {"non_item_fee": {"type_id": 41, "accrued": cash("-10")}}),
                (
                    "ITEM",
                    {
                        "item_fees": {
                            "fees": [
                                {"sku": 101, "fees": [{"type_id": 999, "accrued": cash("-10")}]}
                            ]
                        }
                    },
                ),
                (
                    "CONTAINER_FEES",
                    {"container_fees": {"fees": [{"type_id": 999, "accrued": cash("-10")}]}},
                ),
                ("FUTURE", {}),
            ],
            1,
        )
    ]
    data = normalize(rows, DAY, types)["currencies"]["RUB"]
    assert data["settlement"] == "-40.00"
    assert sum(float(row["amount"]) for row in data["lines"]) == -40
    assert {row["group"] for row in data["lines"]} == {"advertising", "other"}


def test_wrong_day_or_mixed_currency_inside_one_accrual_cannot_be_published():
    value = accrual()
    value["date"] = "2026-10-02"
    with pytest.raises(ValueError):
        normalize([value], DAY, {})
    value = accrual()
    value["posting"]["products"][0]["commission"]["sale_price"]["currency"] = "USD"
    with pytest.raises(ValueError):
        normalize([value], DAY, {})


def test_empty_day_and_separate_currencies_are_explicit():
    assert normalize([], DAY, {}) == {
        "records": 0,
        "currencies": {},
        "realizations": [],
        "cost_items": [],
        "cost_basis": "accrual_v1",
        "details_basis": "accrual_products_v1",
        "product_details": {},
    }
    rows = [
        {
            "accrual_id": i,
            "date": str(DAY),
            "total_amount": cash("-10", currency),
            "accrued_category": "NON_ITEM",
            "non_item_fee": {"type_id": 1, "accrued": cash("-10", currency)},
        }
        for i, currency in enumerate(("RUB", "USD"), 1)
    ]
    assert set(normalize(rows, DAY, {})["currencies"]) == {"RUB", "USD"}


def test_current_finance_client_uses_same_day_cursor_and_discards_duplicate_page():
    bodies = []

    def handler(request):
        if request.url.path == TYPES:
            return httpx.Response(200, json={"accrual_types": []})
        bodies.append(json.loads(request.content))
        return httpx.Response(
            200, json={"accruals": [accrual()], "last_id": "next" if len(bodies) == 1 else ""}
        )

    client = FinanceClient("client", "test-only", transport=httpx.MockTransport(handler))
    days, count = client.days(DAY, DAY, normalize)
    assert count == 1 and len(days) == 1
    assert bodies == [{"date": str(DAY), "last_id": ""}, {"date": str(DAY), "last_id": "next"}]


def test_repeated_cursor_fails_instead_of_partial_publication():
    client = FinanceClient(
        "client",
        "test-only",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"accruals": [accrual()], "last_id": "repeat"})
        ),
    )
    with pytest.raises(OzonImportError, match="ozon_cursor_repeated"):
        list(client.day(DAY))


def test_actual_buyer_quote_never_falls_back_to_ordinary_seller_price():
    raw = {
        "posting_number": "posting-1",
        "status": "delivered",
        "in_process_at": str(DAY) + "T12:00:00Z",
        "products": [{"sku": 101, "quantity": 2, "price": cash("1000")}],
        "financial_data": {
            "products": [{"product_id": 101, "price": 1000, "customer_price": cash("700")}]
        },
    }
    assert posting(raw, "fbs")["items"][0]["price"] == "700"
    del raw["financial_data"]["products"][0]["customer_price"]
    value = posting(raw, "fbo")
    assert value["items"][0]["price"] is None
    day = aggregate([value], [], DAY, DAY)[DAY]
    assert day["totals"]["orders"] == 2 and day["totals"]["orders_amount"] is None
    priced = reprice(day, {("posting-1", "101"): {"price": "650.25", "currency": "RUB"}})
    assert (
        priced["totals"]["orders_amount"] == "1300.50"
        and priced["totals"]["buyouts_amount"] == "1300.50"
    )
    assert reprice(day, {})["totals"]["orders_amount"] is None


def test_negative_return_price_and_quantity_are_signed_once():
    for quantity in (1, -1):
        facts = normalize(
            [accrual(sale="-1000", commission="200", price="-700", quantity=quantity)], DAY, {}
        )
        assert facts["currencies"]["RUB"]["buyer_revenue"] == "-700.00"
        assert not facts["realizations"]


def test_foreign_buyer_quote_is_not_added_to_rubles_and_native_financial_equivalent_wins():
    raw = {
        "posting_number": "foreign-1",
        "status": "delivered",
        "in_process_at": str(DAY) + "T12:00:00Z",
        "products": [{"sku": 101, "quantity": 1, "price": cash("1000")}],
        "financial_data": {"products": [{"product_id": 101, "customer_price": cash("25", "BYN")}]},
    }
    day = aggregate([posting(raw, "fbs")], [], DAY, DAY)[DAY]
    assert reprice(day, {}, "RUB")["totals"]["orders_amount"] is None
    assert reprice(day, {}, "RUB")["currencies"] == ["RUB"]
    quotes = {("foreign-1", "101"): {"price": "650.50", "currency": "RUB"}}
    result = reprice(day, quotes, "RUB")
    assert result["totals"]["orders_amount"] == "650.50"
    assert result["totals"]["buyouts_amount"] == "650.50"


def test_confirmed_price_subtotal_is_available_without_claiming_completeness():
    raw = {
        "posting_number": "known-1",
        "status": "delivered",
        "in_process_at": str(DAY) + "T12:00:00Z",
        "products": [{"sku": 101, "quantity": 1, "price": cash("1000")}],
        "financial_data": {"products": [{"product_id": 101, "customer_price": cash("700")}]},
    }
    known = posting(raw, "fbs")
    raw["posting_number"] = "unknown-1"
    raw.pop("financial_data")
    unknown = posting(raw, "fbo")
    result = reprice(aggregate([known, unknown], [], DAY, DAY)[DAY], {}, "RUB")
    assert result["totals"]["orders"] == 2 and result["totals"]["buyouts"] == 2
    assert (
        result["totals"]["orders_amount"] == "700.00"
        and result["totals"]["buyouts_amount"] == "700.00"
    )
    assert set(result["totals"]["partial_amounts"]) == {"orders_amount", "buyouts_amount"}
