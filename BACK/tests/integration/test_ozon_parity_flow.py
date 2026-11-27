from datetime import timedelta
from decimal import Decimal
from unittest.mock import Mock
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_insights_flow import env as env
from test_insights_flow import pytestmark as pytestmark
from test_ozon_analytics_flow import publish as publish_sales
from test_ozon_analytics_flow import queue
from test_ozon_catalog_flow import publish as publish_catalog
from test_ozon_connection import connect
from test_ozon_connection import ozon as ozon
from test_ozon_costs_supplies import cost
from test_ozon_costs_supplies import report as overview
from test_ozon_finance_flow import publish as publish_finance

from app.db.session import set_actor
from app.modules.accounts.models import StoreCredential
from app.modules.auth.models import Membership
from app.modules.finance.variant_import import OZON_HEADERS
from app.modules.finance.xlsx import build_template, read_rows
from app.modules.insights.extra_models import MarketplaceSupplySnapshot, MarketplaceTrafficDay
from app.modules.insights.marketplace_models import OzonAnalyticsSync
from app.modules.insights.ozon_jobs import execute
from app.modules.sync.schemas import moscow_today


def base(e, sid):
    return f"/api/v1/workspaces/{e.workspace}/stores/{sid}"


def test_ozon_tax_settings_use_the_same_calculator_and_roles(ozon):
    e = ozon
    sid = connect(e)
    publish_catalog(e, sid)
    assert cost(e, sid).status_code == 200
    start, end = publish_finance(e, sid)
    saved = e.client.put(
        base(e, sid) + "/tax-settings",
        json={
            "effective_from": str(start),
            "regime": "usn_income",
            "rate": "6",
            "vat_rate": "0",
            "income_base": "revenue",
        },
        headers=e.headers,
    )
    assert saved.status_code == 200, saved.text
    result = overview(e, sid, start, end)
    assert result["taxes"]["configured_stores"] == 1
    assert result["taxes"]["tax"] == "42.00" and result["taxes"]["net_profit"] == "608.00"
    response = e.client.get(
        base(e, sid) + "/finance/net-profit",
        params={"date_from": str(start), "date_to": str(end)},
        headers=e.headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["tax"] == "42.00"
    denied = e.client.put(
        base(e, sid) + "/tax-settings", json=saved.json(), headers=e.login(e.viewer)
    )
    assert denied.status_code in {403, 404}


def test_ozon_cost_file_preview_apply_and_idempotency(ozon):
    e = ozon
    sid = connect(e)
    publish_catalog(e, sid)
    template = e.client.get(base(e, sid) + "/costs/template", headers=e.headers)
    assert template.status_code == 200, template.text
    assert read_rows(template.content, headers=OZON_HEADERS)
    payload = build_template(
        OZON_HEADERS, [("101", "", "100", str(moscow_today() - timedelta(days=365)), "RUB")]
    )
    checked = e.client.post(
        base(e, sid) + "/cost-imports",
        files={
            "file": (
                "costs.xlsx",
                payload,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
        headers=e.headers,
    )
    assert checked.status_code == 200, checked.text
    data = checked.json()
    assert (
        data["can_apply"]
        and data["valid_count"] == 1
        and data["items"][0]["marketplace_code"] == "101"
    )
    path = base(e, sid) + f"/cost-imports/{data['preview_id']}/apply"
    first = e.client.post(path, headers=e.headers)
    again = e.client.post(path, headers=e.headers)
    assert first.status_code == 200, first.text
    assert first.json() == again.json() and first.json()["inserted"] == 1
    start, end = publish_finance(e, sid)
    assert overview(e, sid, start, end)["totals"]["profit_before_tax"] == "650.00"


def test_ozon_financial_products_and_unallocated_manual_costs(ozon):
    e = ozon
    sid = connect(e)
    publish_catalog(e, sid)
    assert cost(e, sid).status_code == 200
    start, end = publish_finance(e, sid)
    expense = e.client.post(
        base(e, sid) + "/expenses",
        json={
            "expense_date": str(end),
            "amount": "20",
            "category": "advertising",
            "comment": "Synthetic",
        },
        headers=e.headers,
    )
    assert expense.status_code == 201, expense.text
    params = {"date_from": str(start), "date_to": str(end)}
    response = e.client.get(base(e, sid) + "/finance/summary", params=params, headers=e.headers)
    assert response.status_code == 200, response.text
    data = response.json()
    product = data["products"][0]
    assert product["nm_id"] == "" and product["id"] and product["marketplace"] == "ozon"
    assert product["marketplace_code"] == "101" and product["revenue"] == "700.00"
    assert product["profit_before_tax"] == "650.00"
    assert product["financial_details"]["total_expenses"] == "350.00"
    assert data["summary"]["financial_details"]["total_expenses"] == "370.00"
    assert data["summary"]["financial_details"]["wb_expenses_total"] == "250.00"
    assert (
        data["summary"]["profit_before_tax"] == "630.00"
        and data["unassigned"]["profit_before_tax"] == "-20.00"
    )
    assert sum(Decimal(day["profit_before_tax"]) for day in data["daily"]) == Decimal("630")
    business = e.client.get(
        f"/api/v1/workspaces/{e.workspace}/business",
        params={**params, "store_id": str(sid), "topic": "profit"},
        headers=e.headers,
    )
    assert business.status_code == 200, business.text
    unit = e.client.get(base(e, sid) + "/finance/unit-economics", params=params, headers=e.headers)
    assert unit.status_code == 200, unit.text
    assert unit.json()["items"][0]["marketplace_code"] == "101"
    assert unit.json()["items"][0]["marketplace_fee"] == "200.00"


def test_traffic_is_independent_of_orders_and_does_not_invent_favorites(ozon):
    e = ozon
    sid = connect(e)
    start, end = publish_sales(e, sid)
    run, _ = queue(e, sid, "traffic")
    days = {start + timedelta(days=index): {"opens": 100, "carts": 20} for index in range(7)}
    execute(
        e.engine,
        e.vault,
        e.workspace,
        sid,
        "traffic",
        e.owner,
        run,
        lambda cid, key: Mock(days=lambda left, right: days),
    )
    response = e.client.get(
        base(e, sid) + "/insights/funnel",
        params={"date_from": str(start), "date_to": str(end)},
        headers=e.headers,
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert (
        data["totals"]["orders"] == 10
        and data["totals"]["opens"] == 700
        and data["totals"]["carts"] == 140
    )
    assert data["totals"]["wishlist"] is None and "wishlist" not in data["available_metrics"]
    assert data["totals"]["add_to_cart_percent"] == "20.0"
    with Session(e.admin) as db:
        job = db.get(OzonAnalyticsSync, (e.workspace, sid, "traffic"))
        assert job.next_attempt_at >= job.updated_at + timedelta(seconds=61)
    with Session(e.admin) as db, db.begin():
        db.get(Membership, (e.viewer, e.workspace)).permissions = ["inventory.read"]
    with Session(e.engine) as db:
        set_actor(db, e.viewer)
        assert (
            db.scalar(select(MarketplaceTrafficDay).where(MarketplaceTrafficDay.store_id == sid))
            is None
        )


def test_ozon_supply_snapshot_and_per_store_filter(ozon):
    e = ozon
    sid = connect(e)
    run, _ = queue(e, sid, "supplies")
    item = {
        "marketplace": "ozon",
        "display_number": "SUP-1",
        "external_id": "ozon:1:2",
        "supply_id": "2",
        "preorder_id": "1",
        "status": "ready_to_ship",
        "planned_date": None,
        "actual_date": None,
        "created_date": str(moscow_today()),
        "destination": "Synthetic warehouse",
        "quantity": 11,
        "accepted_quantity": None,
        "rejected": False,
    }
    execute(
        e.engine,
        e.vault,
        e.workspace,
        sid,
        "supplies",
        e.owner,
        run,
        lambda cid, key: Mock(snapshot=lambda today, prior: {"items": [item]}),
    )
    response = e.client.get(
        f"/api/v1/workspaces/{e.workspace}/inventory/supplies",
        params={"store_id": str(sid)},
        headers=e.headers,
    )
    assert response.status_code == 200, response.text
    assert (
        response.json()["items"][0]["quantity"] == 11
        and response.json()["items"][0]["marketplace"] == "ozon"
    )
    assert response.json()["count"] == 1
    with Session(e.admin) as db, db.begin():
        db.get(Membership, (e.viewer, e.workspace)).permissions = ["analytics.read"]
    with Session(e.engine) as db:
        set_actor(db, e.viewer)
        assert db.get(MarketplaceSupplySnapshot, (e.workspace, sid)) is None


def test_cost_permission_dependencies_apply_to_catalog_and_history(ozon):
    e = ozon
    sid = connect(e)
    publish_catalog(e, sid)
    with Session(e.admin) as db, db.begin():
        db.get(Membership, (e.viewer, e.workspace)).permissions = ["costs.write"]
    headers = e.login(e.viewer)
    payload = build_template(OZON_HEADERS, [("101", "", "100", str(moscow_today()), "RUB")])
    preview = e.client.post(
        base(e, sid) + "/cost-imports", files={"file": ("costs.xlsx", payload)}, headers=headers
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["can_apply"]
    assert e.client.get(base(e, sid) + "/variant-costs", headers=headers).status_code == 200


@pytest.mark.parametrize("source", ["traffic", "supplies"])
def test_extra_import_key_rotation_never_replaces_previous_snapshot(ozon, source):
    e = ozon
    sid = connect(e)
    run, (start, end) = queue(e, sid, source)
    original = {start: {"opens": 100, "carts": 20}} if source == "traffic" else {"items": []}

    def factory(cid, key):
        return Mock(days=lambda *args: original, snapshot=lambda *args: original)

    execute(e.engine, e.vault, e.workspace, sid, source, e.owner, run, factory)
    model = MarketplaceTrafficDay if source == "traffic" else MarketplaceSupplySnapshot
    key = (e.workspace, sid, start) if source == "traffic" else (e.workspace, sid)
    with Session(e.admin) as db:
        before = db.get(model, key).ciphertext
    run, _ = queue(e, sid, source)

    def replace_key(*args):
        with Session(e.admin) as db, db.begin():
            credential = db.scalar(select(StoreCredential).where(StoreCredential.store_id == sid))
            credential.ciphertext = "synthetic-replaced-key"
        return {start: {"opens": 999, "carts": 999}} if source == "traffic" else {"items": []}

    execute(
        e.engine,
        e.vault,
        e.workspace,
        sid,
        source,
        e.owner,
        run,
        lambda cid, secret: Mock(days=replace_key, snapshot=replace_key),
    )
    with Session(e.admin) as db:
        assert db.get(model, key).ciphertext == before


@pytest.mark.parametrize("source", ["traffic", "supplies"])
def test_extra_import_rejects_duplicate_run_and_revoked_owner(ozon, source):
    e = ozon
    sid = connect(e)
    run, _ = queue(e, sid, source)
    provider = Mock()
    execute(e.engine, e.vault, e.workspace, sid, source, e.owner, uuid4(), provider)
    assert not provider.called
    with Session(e.admin) as db, db.begin():
        db.get(Membership, (e.owner, e.workspace)).role = "viewer"
    execute(e.engine, e.vault, e.workspace, sid, source, e.owner, run, provider)
    assert not provider.called
    with Session(e.admin) as db:
        assert db.get(OzonAnalyticsSync, (e.workspace, sid, source)).error_code == "access_revoked"


def test_cost_import_rejects_unknown_sku_and_changed_price_at_apply(ozon):
    e = ozon
    sid = connect(e)
    publish_catalog(e, sid)
    effective = moscow_today() - timedelta(days=365)
    path = base(e, sid) + "/cost-imports"
    unknown = build_template(OZON_HEADERS, [("999999", "", "100", str(effective), "RUB")])
    checked = e.client.post(path, files={"file": ("costs.xlsx", unknown)}, headers=e.headers)
    assert checked.status_code == 200, checked.text
    assert not checked.json()["can_apply"] and checked.json()["error_count"] == 1
    payload = build_template(OZON_HEADERS, [("101", "", "100", str(effective), "RUB")])
    checked = e.client.post(path, files={"file": ("costs.xlsx", payload)}, headers=e.headers)
    assert checked.status_code == 200, checked.text
    assert cost(e, sid, amount="101").status_code == 200
    response = e.client.post(path + f"/{checked.json()['preview_id']}/apply", headers=e.headers)
    assert response.status_code == 409, response.text
