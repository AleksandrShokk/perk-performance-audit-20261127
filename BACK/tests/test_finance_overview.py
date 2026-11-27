from collections import defaultdict
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from test_profit_rules import finance_row

from app.modules.finance.categories import deduction_category
from app.modules.finance.facts import facts, report_sale
from app.modules.finance.overview import build_groups, build_overview
from app.modules.finance.report import add_group, render_values
from app.modules.finance.schemas import ProfitReport
from app.modules.insights.business import sum_values


def customer(**changes):
    return finance_row(
        data_version=3,
        retail_price_with_discount="1000",
        retail_amount="800",
        for_pay="700",
        acquiring_fee="30",
        acquiring_percent="3",
        **changes,
    )


def total(*rows, cost="100", external="0"):
    values = defaultdict(Decimal)
    for row in rows:
        _, _, data = facts(row, {})
        add_group(values, data, Decimal(cost))
    values["external_expenses"] = Decimal(external)
    return render_values(values, True)


def service(operation, **changes):
    return finance_row(
        operation=operation,
        document_type="",
        quantity=0,
        retail_amount="0",
        for_pay="0",
        acquiring_fee="0",
        data_version=3,
        **changes,
    )


def test_seller_revenue_and_buyer_revenue_stay_separate_and_fees_are_not_deducted_twice():
    summary = total(customer(delivery_service="50", deduction="10"), external="5")
    details = summary.financial_details
    assert summary.revenue == "800"
    assert details["seller_revenue"] == "1000"
    assert details["commission"] == "270" and details["acquiring"] == "30"
    assert details["wb_expenses_total"] == "360"
    assert details["total_expenses"] == "465"
    assert summary.settlement_estimate == "640" and summary.profit_before_tax == "535"
    groups = {group.key: group for group in build_groups(summary)}
    assert groups["fees"].amount == "300" and groups["fees"].share_percent == "30.0"


def test_compensation_is_income_already_in_payout_and_not_a_second_sale():
    compensation = finance_row(
        operation="Компенсация брака", quantity=0, retail_amount="0", for_pay="100", data_version=3
    )
    summary = total(customer(delivery_service="50", deduction="10"), compensation, external="5")
    assert summary.sales == 1 and summary.revenue == "800"
    assert summary.financial_details["compensation_defect"] == "100"
    assert summary.financial_details["wb_expenses_total"] == "360"
    assert summary.profit_before_tax == "635"


def test_acquiring_credit_reduces_its_cost_once():
    correction = finance_row(
        operation="Корректировка эквайринга",
        quantity=0,
        retail_amount="0",
        for_pay="10",
        data_version=3,
    )
    summary = total(customer(), correction)
    assert summary.financial_details["commission"] == "270"
    assert summary.financial_details["acquiring"] == "20"
    assert summary.settlement_estimate == "710"
    assert summary.profit_before_tax == "610"


@pytest.mark.parametrize(
    "name,category",
    [
        ("Оказание услуг «WB Продвижение», кампания 123", "advertising"),
        ("Предоставление услуг по подписке «Джем», период", "jam"),
        ("Витрина Магазина, период", "showcase"),
        ("Разовое изменение срока перечисления денежных средств", "payout_service"),
        ("Неизвестная услуга", "other"),
        (None, "other"),
    ],
)
def test_deductions_are_classified_by_service_title(name, category):
    assert deduction_category(name) == category


def test_old_unclassified_deductions_keep_known_total_and_do_not_invent_zero_advertising():
    summary = total(customer(), service("Удержание", deduction="25"))
    assert summary.wb_expenses["deduction"] == "25"
    assert summary.financial_details["deduction_other"] == "25"
    assert summary.financial_details["deduction_advertising"] is None
    assert summary.financial_details["unclassified_deduction_rows"] == "1"


def test_signed_wb_columns_for_loyalty_withdrawal_and_reward_adjustments_are_separate_costs():
    summary = total(
        customer(
            cashback_amount="20",
            cashback_commission_change="2",
            payment_schedule="3",
            additional_payment="5",
        )
    )
    assert summary.settlement_estimate == "670"
    assert summary.profit_before_tax == "570"
    assert summary.financial_details["wb_expenses_total"] == "330"
    groups = {group.key: group for group in build_groups(summary)}
    assert groups["loyalty"].amount == "22"
    assert groups["services"].amount == "3"
    assert groups["adjustments"].amount == "5"


def test_negative_withdrawal_or_adjustment_refunds_are_not_lost():
    summary = total(customer(payment_schedule="-1", additional_payment="-2"))
    assert summary.settlement_estimate == "703"
    assert summary.profit_before_tax == "603"


def test_loyalty_refunds_reverse_only_loyalty_money_not_operational_charges():
    returned = customer(
        document_type="Возврат",
        operation="Возврат",
        cashback_amount="10",
        cashback_commission_change="1",
    )
    _, _, data = facts(returned, {})
    assert data["cashback_amount"] == -10 and data["cashback_commission_change"] == -1
    assert data["detail_loyalty_points"] == -10 and data["detail_loyalty_cost"] == -1
    returned["cashback_amount"] = "-10"
    assert facts(returned, {})[2]["detail_loyalty_points"] == -10


def test_wb_informational_service_quantities_are_not_customer_sales_or_unclassified_turnover():
    summary = total(
        customer(),
        service(
            "Возмещение издержек по перемещению и операционной обработке товара",
            rebill_logistic_cost="40",
        ),
    )
    assert summary.calculation_complete and summary.sales == 1
    assert summary.profit_before_tax == "600"


@pytest.mark.parametrize(
    "operation,document,expected",
    [
        ("Корректная продажа", "Продажа", "sales"),
        ("Сторно возвратов", "Продажа", "sales"),
        ("Сторно продаж", "Возврат", "returns"),
        ("Корректный возврат", "Возврат", "returns"),
        ("Коррекция продаж", "Возврат", "returns"),
    ],
)
def test_reviewed_corrections_follow_their_document_type(operation, document, expected):
    assert report_sale(finance_row(operation=operation, document_type=document)) == (expected, 1)


def test_unknown_or_inconsistent_operation_keeps_profit_unconfirmed():
    result = total(customer(operation="Неизвестная продажа"))
    assert result.profit_before_tax is None and result.issues["unclassified_operation"]
    assert report_sale(finance_row(operation="Корректный возврат", document_type="Продажа")) is None


def test_multi_store_summaries_add_amounts_without_averaging_or_mixing_unknowns():
    first = total(customer())
    second = total(customer())
    result = sum_values([first, second])
    assert result.financial_details["seller_revenue"] == "2000"
    assert result.financial_details["commission"] == "540"
    second.financial_details["commission"] = None
    assert sum_values([first, second]).financial_details["commission"] is None


def test_tax_setting_is_required_before_showing_net_profit():
    summary = total(customer())
    report = ProfitReport(
        date_from=date(2026, 10, 1),
        date_to=date(2026, 10, 24),
        currency="RUB",
        status="ready",
        is_partial=False,
        period_covered=True,
        summary=summary,
        limit=100,
        offset=0,
    )
    business = SimpleNamespace(
        finance=report, total_stores=1, stores=[SimpleNamespace(finance=report)]
    )
    result = build_overview(business, [(None, False)])
    assert result.totals.profit_before_tax == "600" and result.taxes.net_profit is None
    setting = SimpleNamespace(
        regime="usn_income", rate=Decimal(6), vat_rate=Decimal(0), income_base="revenue"
    )
    result = build_overview(business, [(setting, False)])
    assert result.taxes.tax == "48.00" and result.taxes.net_profit == "552.00"
    assert build_overview(business, [(setting, True)]).taxes.net_profit is None


def test_no_data_is_not_a_zero_financial_report():
    result = render_values(defaultdict(Decimal), False)
    assert result.financial_details["seller_revenue"] is None
    assert all(
        group.amount is None
        for group in build_groups(result)
        if group.key in {"sales", "fees", "cogs", "external"}
    )


def as_overview(summary):
    report = ProfitReport(
        date_from=date(2026, 7, 28),
        date_to=date(2026, 10, 25),
        currency="RUB",
        status="ready",
        is_partial=False,
        period_covered=True,
        summary=summary,
        limit=100,
        offset=0,
    )
    return build_overview(
        SimpleNamespace(finance=report, total_stores=1, stores=[SimpleNamespace(finance=report)]),
        [(None, False)],
    )


def test_known_expenses_and_payout_do_not_depend_on_missing_product_cost():
    amounts = defaultdict(Decimal)
    add_group(amounts, facts(customer(delivery_service="50", deduction="10"), {})[2], None)
    amounts["external_expenses"] = Decimal(5)
    result = as_overview(render_values(amounts, True))
    assert result.expenses_exclude_cogs
    assert result.totals.expenses_before_tax == "365"
    assert result.totals.settlement == "640"
    assert result.totals.profit_before_tax is None
    assert result.taxes.net_profit is None


def test_older_wb_reimbursement_label_does_not_block_long_period_payout():
    rows = [
        customer(),
        service(
            "Возмещение издержек по перевозке/по складским операциям с товаром",
            rebill_logistic_cost="40",
        ),
    ]
    summary = total(*rows)
    assert summary.calculation_complete
    assert summary.settlement_estimate == "700"
    assert summary.financial_details["wb_expenses_total"] == "300"


def test_zero_turnover_return_correction_changes_commission_not_inventory():
    correction = finance_row(
        operation="Коррекция возвратов",
        document_type="Возврат",
        quantity=1,
        retail_amount="0",
        retail_price_with_discount="0",
        for_pay="10",
        acquiring_fee="0",
    )
    summary = total(customer(), correction)
    assert summary.sales == 1 and summary.returns == 0 and summary.cogs == "100"
    assert summary.revenue == "800" and summary.financial_details["seller_revenue"] == "1000"
    assert summary.settlement_estimate == "690" and summary.profit_before_tax == "590"
    assert summary.financial_details["commission"] == "280"
    groups = {row.key: row for row in build_groups(summary)}
    assert groups["fees"].amount == summary.financial_details["wb_expenses_total"] == "310"
    correction["document_type"] = "Неизвестно"
    assert total(customer(), correction).settlement_estimate is None


def test_historical_fees_total_does_not_need_an_acquiring_percent():
    historical = customer()
    historical.update(data_version=2, acquiring_percent=None, payment_schedule=None)
    result = as_overview(total(historical))
    fees = next(group for group in result.groups if group.key == "fees")
    assert fees.amount == "300"
    assert fees.share_percent == "30.0"
    # Missing source data stays unknown; a re-import is required to restore these values.
    assert all(row.amount is None for row in fees.lines[:2])
    assert result.totals.expenses_before_tax is None
    assert result.totals.settlement is None


def test_refreshing_historical_fields_restores_expenses_and_settlement_without_cogs():
    historical = customer(delivery_service="50", deduction="10")
    historical.update(data_version=2, acquiring_percent=None, payment_schedule=None)
    _, _, old_facts = facts(historical, {})
    old = defaultdict(Decimal)
    add_group(old, old_facts, None)
    assert as_overview(render_values(old, True)).totals.settlement is None
    historical.update(data_version=3, acquiring_percent="3", payment_schedule="0")
    _, _, refreshed_facts = facts(historical, {})
    updated = defaultdict(Decimal)
    add_group(updated, refreshed_facts, None)
    result = as_overview(render_values(updated, True))
    assert result.totals.settlement == "640"
    assert result.totals.expenses_before_tax == "360"
    assert result.totals.profit_before_tax is None


def test_combined_fees_keep_corrections_once_when_acquiring_breakdown_is_unknown():
    sale = customer()
    sale.update(acquiring_percent=None)
    acquiring_credit = finance_row(
        operation="Корректировка эквайринга",
        quantity=0,
        retail_amount="0",
        for_pay="10",
        data_version=3,
    )
    payout_credit = finance_row(
        operation="Коррекция продаж",
        document_type="Продажа",
        retail_price_with_discount="0",
        retail_amount="0",
        for_pay="5",
    )
    result = total(sale, acquiring_credit, payout_credit)
    assert result.financial_details["fees_total"] == "285"
    assert next(group for group in build_groups(result) if group.key == "fees").amount == "285"


def test_combined_fees_work_when_merging_different_stores_with_different_import_versions():
    old = customer()
    old.update(data_version=2, acquiring_percent=None, payment_schedule=None)
    combined = sum_values([total(old), total(customer())])
    assert combined.financial_details["fees_total"] == "600"
    assert combined.financial_details["acquiring"] is None
    assert next(group for group in build_groups(combined) if group.key == "fees").amount == "600"


def test_advertising_is_totalled_separately_without_counting_it_twice():
    row = customer(deduction="50", bonus_type_name="WB Продвижение")
    values = defaultdict(Decimal)
    add_group(values, facts(row, {})[2], None)
    values["external_expenses"] = Decimal("20")
    values["detail_external_advertising"] = Decimal("7")
    values["detail_external_packaging"] = Decimal("13")
    summary = render_values(values, True)
    groups = {group.key: group for group in build_groups(summary)}
    assert groups["advertising"].amount == "57"
    assert groups["services"].amount == "0"
    assert groups["external"].amount == "13"
    charges = [g.amount for g in groups.values() if g.key not in {"sales", "compensations", "cogs"}]
    assert sum(map(Decimal, charges)) == Decimal(as_overview(summary).totals.expenses_before_tax)
