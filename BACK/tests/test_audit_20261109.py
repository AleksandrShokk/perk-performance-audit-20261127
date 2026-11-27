from datetime import date
from decimal import Decimal

import pytest
from test_ozon_finance import DAY, accrual, cash
from test_ozon_operations import order_raw

from app.integrations.ozon.order_prices import apply, parse
from app.integrations.wildberries.data import WBError
from app.modules.finance.ozon_facts import normalize, normalize_partial
from app.modules.finance.precision import money
from app.modules.insights.ozon_sales import aggregate, posting
from app.modules.sync.funnel_summary import normalize_row

HEADER = "Номер отправления;SKU;Количество;Оплачено покупателем;Код валюты покупателя\n"


def test_unrelated_bad_price_row_does_not_block_requested_order():
    csv = HEADER + "order-1;101;2;700.25;RUB\nother;555;1;0;\n"
    result = parse(csv.encode("utf-8-sig"), {("order-1", "101")})
    assert len(result) == 1 and result[("order-1", "101")][0][1] == Decimal("700.25")


def test_zero_without_currency_stays_unknown_instead_of_becoming_rubles():
    row = posting(order_raw(quantity=2), "fbo")
    apply([row], parse((HEADER + "order-1;101;2;0;\n").encode("utf-8-sig")))
    assert row["items"][0]["price_status"] == "currency_missing"
    day = date(2026, 10, 1)
    result = aggregate([row], [], day, day)[day]
    assert result["totals"]["orders_amount"] is None


def test_zero_financial_component_uses_confirmed_accrual_currency_only():
    row = accrual(price="0")
    row["posting"]["products"][0]["commission"]["sale_price"] = cash("0", "")
    assert normalize([row], DAY, {})["currencies"]["RUB"]["buyer_revenue"] == "0.00"


def test_bad_finance_row_is_quarantined_without_losing_good_rows():
    bad = accrual(rid=2)
    bad["posting"]["products"][0]["commission"]["sale_price"] = cash("700", "")
    result = normalize_partial([accrual(), bad], DAY, {})
    assert result["is_partial"] and result["records"] == 1
    assert result["issues"] == [{"record_id": "2", "reason": "ozon_invalid_record"}]
    assert result["currencies"]["RUB"]["buyer_revenue"] == "700.00"


def test_malformed_summary_is_a_record_error_not_a_credential_error():
    with pytest.raises(WBError, match="wb_invalid_record"):
        normalize_row({})


@pytest.mark.parametrize(
    "value,expected", [("0.125", "0.13"), ("-0.125", "-0.13"), ("0.124", "0.12")]
)
def test_canonical_money_rounding(value, expected):
    assert money(Decimal(value)) == expected
