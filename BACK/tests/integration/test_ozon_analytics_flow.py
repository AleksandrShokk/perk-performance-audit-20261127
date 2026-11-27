from datetime import timedelta
from unittest.mock import Mock
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_insights_flow import env as env
from test_insights_flow import pytestmark as pytestmark
from test_ozon_catalog_flow import publish as publish_catalog
from test_ozon_connection import connect
from test_ozon_connection import ozon as ozon
from test_ozon_operations import order_raw, return_raw, stock_row

from app.db.session import set_actor
from app.integrations.ozon.transport import OzonImportError
from app.modules.accounts.models import StoreCredential
from app.modules.auth.dependencies import now
from app.modules.auth.models import Membership
from app.modules.insights.marketplace_models import MarketplaceSalesDay, OzonAnalyticsSync
from app.modules.insights.ozon_jobs import execute, plan
from app.modules.sync.schemas import moscow_today


def queue(e, sid, source="sales"):
    run = uuid4()
    with Session(e.admin) as db, db.begin():
        job = db.get(OzonAnalyticsSync, (e.workspace, sid, source))
        plan(job)
        job.run_id, job.status = run, "queued"
        job.next_attempt_at = now() + timedelta(minutes=10)
        window = (job.date_from, job.date_to)
    return run, window


def publish(e, sid, quantity=10, during=None):
    run, (start, end) = queue(e, sid)

    def sales(left, right, normalize, normalize_return, progress):
        assert (left, right) == (start, end)
        if during:
            during()
        raw = order_raw(day=end.isoformat(), quantity=quantity)
        progress(1)
        return [normalize(raw, "fbo")], [normalize_return(return_raw())]

    execute(
        e.engine,
        e.vault,
        e.workspace,
        sid,
        "sales",
        e.owner,
        run,
        lambda cid, key: Mock(sales=sales),
    )
    return start, end


def test_recent_seven_days_then_comparison_history_and_unknown_days(ozon):
    e = ozon
    sid = connect(e)
    start, end = publish(e, sid)
    assert (end - start).days == 6
    base = f"/api/v1/workspaces/{e.workspace}/stores/{sid}/insights/funnel"
    response = e.client.get(
        base, params={"date_from": str(start), "date_to": str(end)}, headers=e.headers
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["known_days"] == 7 and data["status"] == "ready"
    assert data["totals"]["orders"] == 10 and data["totals"]["buyouts"] == 9
    assert data["totals"]["opens"] is None and "opens" not in data["available_metrics"]
    assert data["data_source"] == "ozon_postings" and data["buyouts_by"] == "order_date"
    assert all(not row["nm_id"] and row["identifier_kind"] == "sku" for row in data["products"])
    wider = e.client.get(
        base,
        params={"date_from": str(start - timedelta(days=21)), "date_to": str(end)},
        headers=e.headers,
    ).json()
    assert wider["status"] == "partial" and wider["is_loading"]
    assert wider["daily"][0]["orders"] is None
    assert wider["daily"][-1]["orders"] == 10
    summary = e.client.get(
        base + "/summary", params={"date_from": str(start), "date_to": str(end)}, headers=e.headers
    ).json()
    assert summary["status"] == "preparing"
    next_start, next_end = publish(e, sid, quantity=5)
    assert (next_end - next_start).days == 27
    summary = e.client.get(
        base + "/summary", params={"date_from": str(start), "date_to": str(end)}, headers=e.headers
    )
    assert summary.status_code == 200, summary.text
    assert summary.json()["status"] == "ready"
    assert summary.json()["totals"]["orders"] == 10
    assert summary.json()["previous"]["totals"]["orders"] == 5


def test_native_fbo_coverage_is_separate_from_fbs_and_uses_confirmed_warehouse_facts(ozon):
    e = ozon
    sid = connect(e)
    publish_catalog(e, sid)
    run, _ = queue(e, sid, "stock_cover")
    client = Mock(
        stock_cover=Mock(
            return_value=[
                stock_row(sku=101, available=8, ads="2", idc="4"),
                stock_row(sku=102, available=8, ads="2", idc="4"),
                stock_row(sku=103, available=8, ads="0", idc=None, grade="NO_SALES"),
            ]
        )
    )
    execute(
        e.engine, e.vault, e.workspace, sid, "stock_cover", e.owner, run, lambda cid, key: client
    )
    url = f"/api/v1/workspaces/{e.workspace}/inventory/overview"
    response = e.client.get(url, params={"store_id": str(sid), "limit": 30}, headers=e.headers)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["turnover_basis"] == "ozon_sales_28d_fbo" and data["turnover_days"] == "6.00"
    assert data["fbs"]["units"] == 6 and data["fbo"]["units"] == 24
    assert data["items"][0]["turnover_days"] == "4"
    assert data["items"][2]["turnover_status"] == "no_sales"
    mixed = e.client.get(url, headers=e.headers).json()
    assert mixed["turnover_days"] is None and not mixed["turnover_supported"]


def test_sales_scope_and_database_permissions_are_independent_of_inventory(ozon):
    e = ozon
    sid = connect(e)
    start, end = publish(e, sid)
    url = f"/api/v1/workspaces/{e.workspace}/stores/{sid}/insights/funnel"
    with Session(e.admin) as db, db.begin():
        member = db.get(Membership, (e.viewer, e.workspace))
        member.permissions = ["inventory.read"]
    headers = e.login(e.viewer)
    assert (
        e.client.get(
            url, params={"date_from": str(start), "date_to": str(end)}, headers=headers
        ).status_code
        == 403
    )
    with Session(e.engine) as db, db.begin():
        set_actor(db, e.viewer)
        assert db.get(MarketplaceSalesDay, (e.workspace, sid, end)) is None
    with Session(e.admin) as db, db.begin():
        member = db.get(Membership, (e.viewer, e.workspace))
        member.permissions = ["analytics.read"]
        member.store_ids = [str(e.store)]
    assert (
        e.client.get(
            url, params={"date_from": str(start), "date_to": str(end)}, headers=headers
        ).status_code
        == 404
    )


def test_more_history_keeps_background_owner_and_key_rotation_keeps_successful_days(ozon):
    e = ozon
    sid = connect(e)
    start, end = publish(e, sid)
    url = f"/api/v1/workspaces/{e.workspace}/stores/{sid}/insights/funnel"
    old_start = moscow_today() - timedelta(days=365)
    headers = e.login(e.viewer)
    response = e.client.get(
        url, params={"date_from": str(old_start), "date_to": str(end)}, headers=headers
    )
    assert response.status_code == 200, response.text
    with Session(e.admin) as db:
        job = db.get(OzonAnalyticsSync, (e.workspace, sid, "sales"))
        assert job.history_from == old_start and job.requested_by == e.owner
        old = db.get(MarketplaceSalesDay, (e.workspace, sid, end)).ciphertext

    def change_key():
        with Session(e.admin) as db, db.begin():
            credential = db.scalar(select(StoreCredential).where(StoreCredential.store_id == sid))
            credential.ciphertext = "synthetic-replaced-key"

    with pytest.raises(OzonImportError) as error:
        publish(e, sid, during=change_key)
    assert error.value.code == "credential_changed"
    with Session(e.admin) as db:
        assert db.get(MarketplaceSalesDay, (e.workspace, sid, end)).ciphertext == old


def test_duplicate_delivery_and_revoked_actor_never_call_provider(ozon):
    e = ozon
    sid = connect(e)
    run, _ = queue(e, sid)
    client = Mock()
    execute(e.engine, e.vault, e.workspace, sid, "sales", e.owner, uuid4(), client)
    assert not client.called
    with Session(e.admin) as db, db.begin():
        db.get(Membership, (e.owner, e.workspace)).role = "viewer"
    execute(e.engine, e.vault, e.workspace, sid, "sales", e.owner, run, client)
    assert not client.called
    with Session(e.admin) as db:
        assert db.get(OzonAnalyticsSync, (e.workspace, sid, "sales")).error_code == "access_revoked"
