from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.modules.finance import economics
from app.modules.finance.schemas import ProfitProduct, ProfitValues


def setting(regime="usn_income", rate="6", vat="0", base="revenue"):
    return SimpleNamespace(
        regime=regime,
        rate=Decimal(rate),
        vat_rate=Decimal(vat),
        income_base=base,
        effective_from=date(2026, 1, 1),
    )


def product(**values):
    defaults = dict(
        nm_id="42",
        sales=12,
        returns=2,
        net_units=10,
        revenue="10000",
        for_pay="7000",
        wb_expenses={
            "delivery_service": "800",
            "paid_storage": "200",
            "paid_acceptance": "0",
            "penalty": "100",
            "deduction": "0",
        },
        cogs="3000",
        contribution_before_external_expenses="2900",
    )
    return ProfitProduct(**{**defaults, **values})


def test_usn_income_tax_is_on_buyer_revenue():
    vat, tax, notes = economics.tax_estimate(
        setting(), revenue=Decimal(10000), payout=Decimal(7000), profit=Decimal(2900)
    )
    assert (vat, tax) == (Decimal(0), Decimal(600))
    assert any("страховые взносы" in note for note in notes)


def test_payout_base_and_vat_inside_price():
    vat, tax, _ = economics.tax_estimate(
        setting(vat="5", base="payout"),
        revenue=Decimal(10000),
        payout=Decimal(7350),
        profit=Decimal(2900),
    )
    assert vat == Decimal(350)
    assert tax == Decimal(420)


def test_usn_income_expense_applies_minimum_tax():
    _, tax, notes = economics.tax_estimate(
        setting("usn_income_expense", "15"),
        revenue=Decimal(10000),
        payout=Decimal(7000),
        profit=Decimal(-500),
    )
    assert tax == Decimal(100)
    assert any("Минимальный" in note or "минимальный" in note for note in notes)


def test_unknown_profit_keeps_tax_unknown():
    values = ProfitValues(revenue="1000", profit_before_tax=None)
    result = economics.net_profit(setting("profit", "25"), values)
    assert result["tax"] is None and result["net_profit"] is None


def test_unit_row_splits_costs_per_unit_and_classifies():
    row = economics.unit_row(product(), setting(), Decimal(15))
    assert row["price"] == "1000.00"
    assert row["marketplace_fee"] == "300.00"
    assert row["logistics"] == "80.00"
    assert row["storage"] == "20.00"
    assert row["penalties"] == "10.00"
    assert row["cost_price"] == "300.00"
    assert row["tax"] == "60.00"
    assert row["profit"] == "230.00"
    assert row["margin_percent"] == "23.00"
    assert row["status"] == "profitable"


@pytest.mark.parametrize(
    "contribution,status", [("-100", "loss"), ("1000", "marginal"), (None, "unknown")]
)
def test_unit_status(contribution, status):
    row = economics.unit_row(
        product(contribution_before_external_expenses=contribution),
        setting("none", "0"),
        Decimal(15),
    )
    assert row["status"] == status


def test_simulation_break_even_is_exact():
    result = economics.simulate(product(), setting(), price=Decimal(1200), cost_price=Decimal(300))
    # share 0.7; WB per unit (800+200+0)/10 = 100; fixed = 400; slope = 0.7 - 0.06
    assert result["payout"] == "840.00"
    assert result["profit_per_unit"] == "368.00"
    assert result["break_even_price"] == "625.00"
    zero = economics.simulate(product(), setting(), price=Decimal(625), cost_price=Decimal(300))
    assert zero["profit_per_unit"] == "0.00"
    assert result["units_to_match_history_profit"] == 8


def test_simulation_needs_history():
    assert (
        economics.simulate(
            product(net_units=0), setting(), price=Decimal(100), cost_price=Decimal(1)
        )
        is None
    )
    assert (
        economics.simulate(
            product(wb_expenses={"delivery_service": None}),
            setting(),
            price=Decimal(100),
            cost_price=Decimal(1),
        )
        is None
    )
