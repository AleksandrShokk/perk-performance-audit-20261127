import json
from datetime import date, timedelta
from unittest.mock import Mock

from sqlalchemy.orm import Session
from test_insights_flow import env as env
from test_insights_flow import pytestmark as pytestmark
from test_ozon_analytics_flow import queue
from test_ozon_connection import connect
from test_ozon_connection import ozon as ozon
from test_ozon_operations import order_raw

from app.modules.insights.marketplace_models import MarketplaceSalesDay, OzonAnalyticsSync
from app.modules.insights.ozon_jobs import execute, sales_aad


def test_price_selection_applies_to_old_days_api_and_export_without_changing_quantities(ozon):
    e = ozon
    sid = connect(e)
    run, _ = queue(e, sid)
    old = date(2025, 5, 1)
    with Session(e.admin) as db, db.begin():
        job = db.get(OzonAnalyticsSync, (e.workspace, sid, "sales"))
        job.date_from = job.date_to = old
        job.history_from = old

    def sales(left, right, normalize, normalize_return, progress):
        raw = order_raw(day=str(old), quantity=3, price="700")
        raw["products"][0]["price"]["amount"] = "1000"
        return [normalize(raw, "fbo")], []

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
    path = f"/api/v1/workspaces/{e.workspace}/stores/{sid}/insights/funnel"
    params = {"date_from": str(old), "date_to": str(old)}
    for mode, expected in (("customer", "2100.00"), ("seller", "3000.00")):
        response = e.client.get(path, params={**params, "price_basis": mode}, headers=e.headers)
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["totals"]["orders"] == data["totals"]["buyouts"] == 3
        assert data["totals"]["orders_amount"] == expected
        assert data["daily"][0]["buyouts_amount"] == expected
        exported = e.client.get(
            f"/api/v1/workspaces/{e.workspace}/insights/funnel/export",
            params={
                **params,
                "store_id": str(sid),
                "price_basis": mode,
                "format": "csv",
                "granularity": "days",
            },
            headers=e.headers,
        )
        assert exported.status_code == 200, exported.text
        assert expected in exported.text


def test_price_upgrade_never_rewinds_an_existing_history_import(ozon):
    from test_ozon_analytics_flow import publish

    e = ozon
    sid = connect(e)
    start, end = publish(e, sid)
    with Session(e.admin) as db, db.begin():
        day = db.get(MarketplaceSalesDay, (e.workspace, sid, end))
        aad = sales_aad(e.workspace, sid, end)
        data = json.loads(e.vault.open(day.ciphertext, aad))
        data.pop("customer_prices_version")
        day.ciphertext = e.vault.seal(json.dumps(data), aad)
        job = db.get(OzonAnalyticsSync, (e.workspace, sid, "sales"))
        job.cursor = None
    path = f"/api/v1/workspaces/{e.workspace}/stores/{sid}/insights/funnel"
    params = {"date_from": str(start), "date_to": str(end)}
    assert e.client.get(path, params=params, headers=e.headers).status_code == 200
    cursor = start - timedelta(days=1)
    with Session(e.admin) as db, db.begin():
        job = db.get(OzonAnalyticsSync, (e.workspace, sid, "sales"))
        assert job.cursor == end
        job.cursor, job.status = cursor, "ready"
    assert e.client.get(path, params=params, headers=e.headers).status_code == 200
    with Session(e.admin) as db:
        assert db.get(OzonAnalyticsSync, (e.workspace, sid, "sales")).cursor == cursor
