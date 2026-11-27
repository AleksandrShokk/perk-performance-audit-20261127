from datetime import date
from decimal import Decimal

import httpx

from app.integrations.wildberries.data import Source, WBDataClient
from app.modules.finance.schemas import ProfitDay, ProfitReport, ProfitValues
from app.modules.insights.business import merge_activity, merge_finance, sum_values
from app.modules.sync.normalize import normalize


def test_balance_transport_and_normalization():
    def handle(request):
        assert request.method == "GET"
        assert str(request.url) == "https://finance-api.wildberries.ru/api/v1/account/balance"
        return httpx.Response(200, json={"currency": "RUB", "current": 100.25, "for_withdraw": 0})

    page = WBDataClient(httpx.MockTransport(handle)).page(Source.BALANCE, "test", {}, None, None)
    key, row = normalize(Source.BALANCE, page.rows[0])
    assert page.complete and key == "current"
    assert row == {"currency": "RUB", "current": "100.25", "for_withdraw": "0"}
    assert normalize(Source.BALANCE, {"currency": "RUB"})[1]["current"] is None


def test_activity_keeps_gaps_and_marks_partial_store_sums():
    rows = merge_activity(
        [
            [{"day": "2026-10-01", "orders": 0, "buyouts": 2}],
            [{"day": "2026-10-01", "orders": 5, "buyouts": None}],
        ],
        date(2026, 10, 1),
        date(2026, 10, 2),
    )
    assert rows[0].orders == 5 and not rows[0].orders_partial
    assert rows[0].buyouts == 2 and rows[0].buyouts_partial
    assert rows[1].orders is None and rows[1].orders_partial


def test_business_money_and_unknowns():
    result = sum_values(
        [
            ProfitValues(revenue="0.10", sales=1, profit_before_tax="0.01"),
            ProfitValues(revenue="0.20", sales=2, profit_before_tax="0.02"),
        ]
    )
    assert Decimal(result.revenue) == Decimal("0.30")
    assert result.sales == 3 and Decimal(result.margin_percent) == Decimal(10)
    unknown = sum_values([result, ProfitValues()])
    assert unknown.revenue is None and unknown.profit_before_tax is None


def test_business_report_does_not_merge_product_ids_or_claim_missing_store():
    start, end = date(2026, 10, 1), date(2026, 10, 2)
    first = ProfitReport(
        date_from=start,
        date_to=end,
        currency="RUB",
        status="ready",
        is_partial=False,
        period_covered=True,
        limit=100,
        offset=0,
        summary=ProfitValues(revenue="100", sales=2),
        daily=[ProfitDay(day=start, revenue="100", sales=2)],
    )
    missing = ProfitReport(
        date_from=start,
        date_to=end,
        currency="RUB",
        status="preparing",
        is_partial=False,
        period_covered=False,
        limit=100,
        offset=0,
    )
    result = merge_finance([first, missing], start, end, "RUB")
    assert result.summary.revenue == "100" and result.is_partial
    assert not result.period_covered and not result.summary.calculation_complete
    assert result.summary.profit_before_tax is None
    assert result.products == [] and len(result.daily) == 1
