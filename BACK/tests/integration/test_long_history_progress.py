from datetime import timedelta
from unittest.mock import Mock

from sqlalchemy.orm import Session
from test_insights_flow import env as env
from test_insights_flow import pytestmark as pytestmark
from test_ozon_analytics_flow import publish as publish_sales
from test_ozon_analytics_flow import queue
from test_ozon_connection import connect
from test_ozon_connection import ozon as ozon

from app.db.session import set_actor
from app.modules.insights.extra_jobs import execute
from app.modules.insights.marketplace_models import OzonAnalyticsSync
from app.modules.insights.ozon_read import ensure_range
from app.modules.sync.schemas import moscow_today


def test_ozon_shows_received_traffic_without_invalid_full_period_conversion(ozon):
    e = ozon
    sid = connect(e)
    start, end = publish_sales(e, sid)
    run, _ = queue(e, sid, "traffic")
    execute(
        e.engine,
        e.vault,
        e.workspace,
        sid,
        "traffic",
        e.owner,
        run,
        lambda cid, key: Mock(
            days=lambda left, right: {
                start + timedelta(days=i): {"opens": 100, "carts": 20} for i in range(7)
            }
        ),
    )
    response = e.client.get(
        f"/api/v1/workspaces/{e.workspace}/stores/{sid}/insights/funnel",
        params={"date_from": str(start - timedelta(days=7)), "date_to": str(end)},
        headers=e.headers,
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["totals"]["opens"] == 700 and data["traffic_known_days"] == 7
    assert data["totals"]["carts"] == 140
    assert data["totals"]["cart_to_order_percent"] is None
    assert data["is_loading"]
    assert "opens" in data["available_metrics"]


def test_older_ozon_sales_request_includes_history_for_confirmed_buyer_prices(ozon):
    e = ozon
    sid = connect(e)
    start = moscow_today() - timedelta(days=600)
    with Session(e.engine) as db, db.begin():
        set_actor(db, e.owner)
        ensure_range(db, e.workspace, sid, start)
    with Session(e.admin) as db:
        for source in ("sales", "traffic", "finance"):
            job = db.get(OzonAnalyticsSync, (e.workspace, sid, source))
            assert job.history_from == start
