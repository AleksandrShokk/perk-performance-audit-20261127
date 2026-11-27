from datetime import timedelta
from unittest.mock import Mock

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_insights_flow import env as env
from test_insights_flow import pytestmark as pytestmark
from test_ozon_analytics_flow import queue
from test_ozon_connection import connect
from test_ozon_connection import ozon as ozon
from test_ozon_finance import accrual
from test_ozon_operations import order_raw

from app.db.session import set_actor
from app.integrations.ozon.transport import OzonImportError
from app.modules.accounts.models import StoreCredential
from app.modules.auth.models import Membership
from app.modules.finance.marketplace_models import MarketplaceFinanceDay, MarketplaceRealization
from app.modules.finance.ozon_jobs import execute
from app.modules.insights.marketplace_models import OzonAnalyticsSync
from app.modules.insights.ozon_jobs import execute as execute_sales
from app.modules.sync.schemas import moscow_today


def publish(e, sid, amount="1000", during=None, number="posting-private-1"):
    run, (start, end) = queue(e, sid, "finance")

    def days(left, right, normalize, progress):
        assert (left, right) == (start, end)
        if during:
            during()
        raw = accrual(sale=amount)
        raw["date"], raw["unit_number"] = str(end), number
        data = {
            day: normalize(
                [raw] if day == end else [], day, {32: {"name": "Logistic", "title": "Логистика"}}
            )
            for day in (start + timedelta(days=i) for i in range((end - start).days + 1))
        }
        progress(1)
        return data, 1

    execute(e.engine, e.vault, e.workspace, sid, e.owner, run, lambda cid, key: Mock(days=days))
    return start, end


def url(e):
    return f"/api/v1/workspaces/{e.workspace}/finance/overview"


def test_finance_progressive_days_exact_totals_and_mixed_provider_overview(ozon):
    e = ozon
    sid = connect(e)
    start, end = publish(e, sid)
    response = e.client.get(
        url(e),
        params={"store_id": str(sid), "date_from": str(start), "date_to": str(end)},
        headers=e.headers,
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["known_days"] == 7 and data["period_covered"]
    assert data["totals"] == {
        "storage_total": "0.00",
        "seller_revenue": "1000.00",
        "marketplace_revenue": "700.00",
        "expenses_before_tax": "250.00",
        "profit_before_tax": None,
        "settlement": "750.00",
    }
    assert data["expenses_exclude_cogs"] and data["data_sources"] == ["ozon_accruals"]
    assert not data["taxes"]["configured_stores"] and not data["source_errors"]
    wide = e.client.get(
        url(e),
        params={
            "store_id": str(sid),
            "date_from": str(start - timedelta(days=21)),
            "date_to": str(end),
        },
        headers=e.headers,
    ).json()
    assert wide["is_partial"] and wide["is_loading"] and wide["totals"]["settlement"] == "750.00"
    mixed = e.client.get(
        url(e), params={"date_from": str(start), "date_to": str(end)}, headers=e.headers
    )
    assert mixed.status_code == 200, mixed.text
    assert mixed.json()["total_stores"] == 2
    assert set(mixed.json()["data_sources"]) == {"wb_finance", "ozon_accruals"}
    assert len({group["key"] for group in mixed.json()["groups"]}) == len(mixed.json()["groups"])
    assert e.ozon_key not in response.text and "posting-private" not in response.text


def test_finance_and_buyer_price_rls_are_independent_and_store_scoped(ozon):
    e = ozon
    sid = connect(e)
    start, end = publish(e, sid)
    with Session(e.admin) as db, db.begin():
        member = db.get(Membership, (e.viewer, e.workspace))
        member.permissions = ["analytics.read"]
    headers = e.login(e.viewer)
    params = {"store_id": str(sid), "date_from": str(start), "date_to": str(end)}
    assert e.client.get(url(e), params=params, headers=headers).status_code == 403
    with Session(e.engine) as db, db.begin():
        set_actor(db, e.viewer)
        assert db.get(MarketplaceFinanceDay, (e.workspace, sid, end)) is None
        assert (
            db.scalar(select(MarketplaceRealization).where(MarketplaceRealization.store_id == sid))
            is not None
        )
    with Session(e.admin) as db, db.begin():
        member = db.get(Membership, (e.viewer, e.workspace))
        member.permissions = ["finance.read"]
    with Session(e.engine) as db, db.begin():
        set_actor(db, e.viewer)
        assert db.get(MarketplaceFinanceDay, (e.workspace, sid, end)) is not None
        assert (
            db.scalar(select(MarketplaceRealization).where(MarketplaceRealization.store_id == sid))
            is None
        )
    assert e.client.get(url(e), params=params, headers=headers).status_code == 200
    with Session(e.admin) as db, db.begin():
        db.get(Membership, (e.viewer, e.workspace)).store_ids = [str(e.store)]
    assert e.client.get(url(e), params=params, headers=headers).status_code == 404


def test_new_realization_reprices_original_order_date_without_redownloading_orders(ozon):
    e = ozon
    sid = connect(e)
    run, (start, end) = queue(e, sid)

    def sales(left, right, normalize, normalize_return, progress):
        raw = order_raw(number="posting-private-1", quantity=1, day=str(end))
        raw.pop("financial_data")
        return [normalize(raw, "fbo")], []

    execute_sales(
        e.engine,
        e.vault,
        e.workspace,
        sid,
        "sales",
        e.owner,
        run,
        lambda cid, key: Mock(sales=sales),
    )
    path = f"/api/v1/workspaces/{e.workspace}/stores/{sid}/insights/funnel"
    params = {"date_from": str(start), "date_to": str(end)}
    before = e.client.get(path, params=params, headers=e.headers).json()
    assert before["totals"]["orders"] == 1 and before["totals"]["orders_amount"] is None
    publish(e, sid)
    after = e.client.get(path, params=params, headers=e.headers).json()
    assert after["totals"]["orders"] == 1 and after["totals"]["orders_amount"] == "700.00"
    assert after["totals"]["buyouts_amount"] == "700.00"
    assert after["daily"][-1]["orders_amount"] == "700.00"


def test_failed_or_replaced_key_preserves_last_successful_financial_snapshot(ozon):
    e = ozon
    sid = connect(e)
    start, end = publish(e, sid)
    with Session(e.admin) as db:
        previous = db.get(MarketplaceFinanceDay, (e.workspace, sid, end)).ciphertext

    def replace_key():
        with Session(e.admin) as db, db.begin():
            row = db.scalar(select(StoreCredential).where(StoreCredential.store_id == sid))
            row.ciphertext = "test-replaced"

    with pytest.raises(OzonImportError, match="credential_changed"):
        publish(e, sid, during=replace_key)
    with Session(e.admin) as db:
        assert db.get(MarketplaceFinanceDay, (e.workspace, sid, end)).ciphertext == previous


def test_requesting_history_uses_original_authorized_owner_and_empty_days_zero(ozon):
    e = ozon
    sid = connect(e)
    start, end = publish(e, sid)
    headers = e.login(e.viewer)
    old = moscow_today() - timedelta(days=365)
    response = e.client.get(
        url(e),
        params={"store_id": str(sid), "date_from": str(old), "date_to": str(end)},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    with Session(e.admin) as db:
        job = db.get(OzonAnalyticsSync, (e.workspace, sid, "finance"))
        assert job.history_from == old and job.requested_by == e.owner
    empty = e.client.get(
        url(e),
        params={"store_id": str(sid), "date_from": str(start), "date_to": str(start)},
        headers=headers,
    ).json()
    assert (
        empty["period_covered"]
        and empty["totals"]["seller_revenue"] == "0.00"
        and empty["totals"]["settlement"] == "0.00"
    )
