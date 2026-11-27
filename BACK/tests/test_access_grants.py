from datetime import date
from types import SimpleNamespace

import pytest

from app.modules.accounts.access import effective, hide_profit, normalize_permissions, store_allowed
from app.modules.accounts.team import InviteInput
from app.modules.finance.schemas import ProfitReport, ProfitValues


def test_admin_has_all_rights_and_store_scopes_never_limit_admin():
    member = SimpleNamespace(role="admin", permissions=[], store_ids=[])
    assert len(effective(member)) == 8
    assert store_allowed(member, "any")
    member.role = "manager"
    assert not store_allowed(member, "any")


def test_permission_dependencies_and_unknown_flags():
    assert normalize_permissions(["costs.write"]) == ["costs.write", "finance.read", "profit.read"]
    assert normalize_permissions(["expenses.write"]) == ["expenses.write", "finance.read"]
    with pytest.raises(ValueError):
        InviteInput(email="staff@example.com", permissions=["root"])
    value = InviteInput(email="staff@example.com", role="admin", permissions=[], store_ids=[])
    assert value.permissions is value.store_ids is None


def test_profit_projection_cannot_mutate_shared_cache_or_leak_cost_through_totals():
    report = ProfitReport(
        date_from=date(2026, 10, 1),
        date_to=date(2026, 10, 2),
        currency="RUB",
        status="ready",
        is_partial=False,
        limit=100,
        offset=0,
        summary=ProfitValues(
            revenue="100",
            cogs="37",
            profit_before_tax="63",
            margin_percent="63",
            contribution_before_external_expenses="63",
            calculation_complete=True,
            financial_details={
                "seller_revenue": "100",
                "wb_expenses_total": "10",
                "total_expenses": "37",
            },
        ),
    )
    filtered = hide_profit(report)
    assert filtered.summary.revenue == "100"
    assert (
        filtered.summary.cogs
        is filtered.summary.profit_before_tax
        is filtered.summary.margin_percent
        is None
    )
    assert filtered.summary.contribution_before_external_expenses is None
    assert "total_expenses" not in filtered.summary.financial_details
    assert not filtered.summary.calculation_complete
    assert report.summary.cogs == "37" and report.summary.calculation_complete
