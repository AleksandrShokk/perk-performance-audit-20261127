from decimal import Decimal

import pytest
from test_ozon_finance import DAY, cash

from app.modules.finance.ozon_facts import line_group, normalize
from app.modules.finance.ozon_report import empty, merge, values


@pytest.mark.parametrize(
    ("name", "group"),
    [
        ("ReturnFlowLogistic", "logistics"),
        ("PushCampaign", "advertising"),
        ("PremiumSubscription", "subscriptions"),
        ("AnalyticsPlus", "subscriptions"),
        ("LabelBrandVerified", "other"),
    ],
)
def test_provider_services_keep_the_same_money_in_current_and_historical_reports(name, group):
    raw = {
        "accrual_id": 1,
        "date": str(DAY),
        "total_amount": cash("-10.25"),
        "accrued_category": "NON_ITEM",
        "non_item_fee": {"type_id": 987, "accrued": cash("-10.25")},
    }
    data = normalize([raw], DAY, {987: {"name": name, "title": "Услуга"}})
    facts = data["currencies"]["RUB"]
    line = facts["lines"][0]
    assert line["group"] == group
    assert facts["settlement"] == line["amount"] == "-10.25"

    # Before this change these provider services were stored in "other".
    line["group"] = "other"
    assert line_group(line) == group
    assert line["group"] == "other"  # Reading does not mutate the stored snapshot.
    detail = data["product_details"]["RUB"][""]
    detail["lines"][0]["group"] = "other"
    ledger = empty()
    merge(ledger, detail)
    assert ledger["lines"][(group, line["key"])] == Decimal("-10.25")
    result = values(ledger, {"known": Decimal(0), "complete": True})
    assert result.settlement_estimate == "-10.25"
    assert result.financial_details["wb_expenses_total"] == "10.25"
    assert result.profit_before_tax == "-10.25"
    assert result.wb_expenses["delivery_service"] == ("10.25" if group == "logistics" else "0.00")


@pytest.mark.parametrize(
    "line",
    [
        {"key": "ozon_unreconciled", "group": "other"},
        {"key": "ozon_future_service", "group": "other"},
        {"key": "ozon_999", "group": "other"},
        {"key": "seller_sales", "group": "sales"},
        {"key": "ozon_delivery_residual", "group": "logistics"},
        {"key": "ozon_PremiumCashbackPromotion", "group": "advertising"},
    ],
)
def test_unknown_services_and_non_subscription_premium_charges_keep_their_category(line):
    assert line_group(line) == line["group"]
