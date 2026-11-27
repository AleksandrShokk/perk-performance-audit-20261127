from decimal import Decimal
from types import SimpleNamespace

import pytest
from test_stock_cover import report

from app.modules.supplies.demand import calendar_rate
from app.modules.supplies.destinations.service import calendar_destinations
from app.modules.supplies.service import from_demand, recommendation


@pytest.mark.parametrize(
    "orders,fbs,expected",
    [(41, 0, 44), (41, 9, 35), (18, 0, 20), (18, 5, 15), (18, 100, 0)],
)
def test_plan_uses_calendar_orders_and_credits_fbs_once(orders, fbs, expected):
    row = report(stock=0, orders=orders, missing_hours=653)
    result = from_demand(0, calendar_rate(row), fbs_stock=fbs)
    assert result["quantity"] == expected
    assert result["fbs_reduction"] == min(fbs, 44 if orders == 41 else 20)
    assert recommendation(row)["quantity"] == (44 if orders == 41 else 20)


@pytest.mark.parametrize("orders", [1, 18, 41, 140, 10000])
def test_repeating_decimal_rate_does_not_add_one_unit_at_exact_horizon(orders):
    rate = calendar_rate(report(orders=orders))
    assert from_demand(0, rate, target_days=28)["quantity"] == orders


def test_missing_availability_hours_do_not_hide_known_calendar_demand():
    assert recommendation(report(missing_hours=None))["quantity"] == 85
    assert calendar_rate(report(date_from="2026-10-02")) is None
    assert calendar_rate(report(orders=None)) is None


def test_fbs_credit_follows_dated_incoming_and_never_credits_more_than_need():
    arrivals = [SimpleNamespace(day=7, quantity=10)]
    result = from_demand(0, Decimal(1), arrivals=arrivals, fbs_stock=5)
    assert result["quantity"] == 15
    assert result["incoming_reduction"] == 10
    assert result["fbs_reduction"] == 5
    assert from_demand(0, Decimal(1), fbs_stock=None)["quantity"] == 30


def test_destination_rates_use_native_proportions_without_multiplying_global_demand():
    groups = [{"id": "a", "daily_orders": "2"}, {"id": "b", "daily_orders": "3"}]
    values = calendar_destinations(groups, Decimal(1))
    assert [v["daily_orders"] for v in values] == ["0.4", "0.6"]
    assert sum(Decimal(v["daily_orders"]) for v in values) == 1
    assert all(v["daily_orders"] is None for v in calendar_destinations(groups, None))
    assert all(
        v["daily_orders"] is None
        for v in calendar_destinations([{"daily_orders": None}], Decimal(1))
    )
