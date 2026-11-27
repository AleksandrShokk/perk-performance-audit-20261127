from collections import defaultdict
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from app.modules.finance.facts import facts, original_sales
from app.modules.finance.fields import AMOUNT_FIELDS
from app.modules.finance.report import abc, add_group, price_for, render_values
from app.modules.finance.schemas import ProfitProduct, ProfitReport


def finance_row(**changes):
    row = {field: "0" for field in AMOUNT_FIELDS}
    row.update(
        nm_id="42",
        barcode="0001",
        document_type="Продажа",
        operation="Продажа",
        quantity=1,
        report_date="2026-10-01",
        currency="RUB",
        data_version=2,
        sale_date="2026-09-30",
        sale_reference="synthetic-sale",
        retail_amount="200",
        for_pay="160",
        sales_commission="30",
        acquiring_fee="10",
    )
    row.update(changes)
    return row


def test_no_second_commission_deduction_and_store_expenses_are_separate():
    row = finance_row(delivery_service="20", paid_storage="3", deduction="2")
    _, _, amounts = facts(row, {})
    values = defaultdict(Decimal)
    add_group(values, amounts, Decimal(100))
    values["external_expenses"] = Decimal(5)
    result = render_values(values, True)
    assert result.for_pay == "160"
    assert result.settlement_estimate == "135"
    assert result.cogs == "100"
    assert result.contribution_before_external_expenses == "35"
    assert result.profit_before_tax == "30"
    assert result.margin_percent == "15.0000"


def test_return_uses_original_sale_date_not_new_return_date():
    sale = finance_row(sale_date="2026-01-01", report_date="2026-01-02")
    returned = finance_row(document_type="Возврат", operation="Возврат", sale_date="2026-10-01")
    links = original_sales([sale, returned])
    _, key, amounts = facts(returned, links)
    assert key == ("42", "0001", "2026-01-01", "returns")
    item = dict(nm_id=key[0], barcode=key[1], cost_day=key[2])
    book = {
        ("42", "0001", "RUB"): [(date(2025, 1, 1), Decimal(100)), (date(2026, 9, 1), Decimal(130))]
    }
    values = defaultdict(Decimal)
    add_group(values, amounts, price_for(book, item, "RUB"))
    result = render_values(values, True)
    assert result.cogs == "-100" and result.profit_before_tax == "-60"


@pytest.mark.parametrize(
    "rows",
    [
        [finance_row(document_type="Возврат", operation="Возврат")],
        [finance_row(), finance_row(), finance_row(document_type="Возврат", operation="Возврат")],
        [finance_row(), finance_row(document_type="Возврат", operation="Возврат", quantity=2)],
    ],
)
def test_unmatched_ambiguous_and_excess_returns_do_not_get_guessed_costs(rows):
    row = rows[-1]
    _, key, amounts = facts(row, original_sales(rows))
    assert key[2] == ""
    values = defaultdict(Decimal)
    add_group(values, amounts, None)
    result = render_values(values, True)
    assert result.profit_before_tax is None
    assert result.issues["missing_cost_units"] >= 1


def test_unknown_is_not_zero_and_signed_expense_reversal_is_preserved():
    _, _, amounts = facts(finance_row(paid_storage=None), {})
    values = defaultdict(Decimal)
    add_group(values, amounts, Decimal(0))
    result = render_values(values, True)
    assert result.wb_expenses["paid_storage"] is None
    assert result.cogs == "0" and result.profit_before_tax is None
    _, _, amounts = facts(finance_row(paid_storage="-4"), {})
    values = defaultdict(Decimal)
    add_group(values, amounts, Decimal(100))
    assert render_values(values, True).profit_before_tax == "64"


@pytest.mark.parametrize(
    "changes,issue",
    [
        ({"data_version": 1}, "legacy_records"),
        ({"operation": "Неизвестная корректировка"}, "unclassified_operation"),
        ({"installment_cofinancing_amount": "5"}, "unreconciled_adjustment"),
        ({"cashback_amount": None}, "missing_cashback_amount"),
        ({"retail_amount": "-200"}, "unexpected_customer_amount_sign"),
        ({"for_pay": "-160"}, "unexpected_customer_amount_sign"),
        (
            {"document_type": "Возврат", "operation": "Возврат", "deduction": "5"},
            "ambiguous_expense_sign",
        ),
    ],
)
def test_unreviewed_operations_and_supplements_do_not_claim_complete_profit(changes, issue):
    _, _, amounts = facts(finance_row(**changes), {})
    values = defaultdict(Decimal)
    add_group(values, amounts, Decimal(100))
    result = render_values(values, True)
    assert result.profit_before_tax is None and result.issues[issue] > 0
    if issue in {"unexpected_customer_amount_sign", "unclassified_operation"}:
        assert result.revenue is None


def test_size_price_and_general_price_fallback_and_unknown_barcode():
    book = {
        ("42", "", "RUB"): [(date(2025, 1, 1), Decimal(100))],
        ("42", "0001", "RUB"): [(date(2026, 1, 1), Decimal(80))],
    }
    item = {"nm_id": "42", "barcode": "0001", "cost_day": "2026-01-01"}
    assert price_for(book, item, "RUB") == 80
    assert price_for(book, {**item, "barcode": "0002"}, "RUB") == 100
    assert price_for(book, {**item, "barcode": ""}, "RUB") is None
    assert price_for(book, item, "USD") is None


def test_abc_dominant_item_stays_a_and_loss_zero_unknown_are_not_ranked_positive():
    products = [
        ProfitProduct(nm_id=str(i), revenue=value)
        for i, value in enumerate(["90", "5", "5", "-1", "0", None], 1)
    ]
    result = ProfitReport(
        date_from=date(2026, 1, 1),
        date_to=date(2026, 1, 31),
        currency="RUB",
        status="ready",
        is_partial=False,
        updated_at=datetime.now(UTC),
        products=products,
        product_count=len(products),
        period_covered=True,
        limit=50000,
        offset=0,
    )
    output = abc(result, "revenue", 1, 0)
    assert output.items[0].group == "A" and output.items[0].share_percent == "90.0000"
    assert output.positive_total == "100" and output.positive_count == 3
    assert output.negative_count == output.zero_count == output.unknown_count == 1
    assert output.status == "incomplete"
    assert [item.group for item in abc(result, "revenue", 100, 0).items] == ["A", "B", "C"]


def test_service_zero_retail_does_not_hide_known_customer_revenue():
    rows = [
        finance_row(),
        finance_row(document_type="Возврат", operation="Возврат", retail_amount="50", for_pay="40"),
        finance_row(
            document_type="",
            operation="Возмещение издержек по перемещению и операционной обработке товара",
            quantity=3,
            retail_amount="0",
            for_pay="0",
        ),
    ]
    total = defaultdict(Decimal)
    for row in rows:
        _, _, amounts = facts(row, {})
        add_group(total, amounts, Decimal(0))
    result = render_values(total, False)
    assert result.revenue == "150"
    assert result.sales == 1 and result.returns == 1
    assert result.issues["incomplete_period"] > 0
    assert result.profit_before_tax is None and not result.calculation_complete


@pytest.mark.parametrize("amount", [None, "1", "-1"])
def test_non_sale_unknown_or_nonzero_retail_keeps_revenue_unknown(amount):
    total = defaultdict(Decimal)
    for row in [
        finance_row(),
        finance_row(document_type="", operation="Unknown", retail_amount=amount, for_pay="0"),
    ]:
        _, _, amounts = facts(row, {})
        add_group(total, amounts, Decimal(0))
    result = render_values(total, False)
    assert result.revenue is None
    assert result.issues["unclassified_revenue"] == 1
    assert result.profit_before_tax is None


def test_legacy_unclassified_aggregate_stays_unknown_until_rebuilt():
    values = defaultdict(
        Decimal, {"retail_amount": Decimal(200), "unclassified_operation": Decimal(1)}
    )
    assert render_values(values, False).revenue is None
