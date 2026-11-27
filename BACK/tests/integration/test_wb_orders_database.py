"""WB orders through the real pipeline: staging, publication, cancellation update, report."""

import json
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session
from test_wb_sync_database import make_run, process, requeue
from test_wb_sync_database import owner_client as owner_client
from test_wb_sync_database import pytestmark as pytestmark
from test_wb_sync_database import setup as setup

from app.db.session import set_actor
from app.integrations.wildberries.data import Page, Source
from app.modules.auth.dependencies import now
from app.modules.insights import compute
from app.modules.sync.models import SyncSchedule, WBRecord
from app.modules.sync.service import context


def order(srid, day, price, cancelled=False):
    return {
        "srid": srid,
        "nmId": 42,
        "date": f"{day}T10:00:00",
        "lastChangeDate": f"{day}T10:05:00",
        "finishedPrice": price,
        "priceWithDisc": price,
        "isCancel": cancelled,
        "cancelDate": f"{day}T12:00:00" if cancelled else "0001-01-01T00:00:00",
        "gNumber": "private-basket",
    }


def orders_report(s, day):
    with Session(s.engine) as db, db.begin():
        set_actor(db, s.user_id)
        params = {"date_from": day.isoformat(), "date_to": day.isoformat()}
        return compute.build("orders", params, db, None, s.vault, s.workspace_id, s.store_id)


def test_orders_publish_update_on_cancellation_and_feed_the_report(setup, owner_client):
    s = setup
    client, path = owner_client
    day = now().date() - timedelta(days=1)
    run_id, task_id = make_run(s, Source.ORDERS)
    rows = [order("o1", day, "1000"), order("o2", day, "500")]
    process(s, run_id, task_id, Page(rows, {"last_change": f"{day}T10:05:00"}, False))
    # Unpublished pages are not a known day yet.
    assert orders_report(s, day)["status"] == "no_data"
    process(s, run_id, requeue(s, run_id), Page([], {}, True))
    sales_id, sales_task = make_run(s, Source.SALES)
    sale = {"saleID": "S1", "nmId": 42, "date": day.isoformat(), "lastChangeDate": day.isoformat()}
    process(s, sales_id, sales_task, Page([{**sale, "finishedPrice": "1000"}], {}, True))

    report = orders_report(s, day)
    assert report["status"] == "ready"
    totals = report["totals"]
    assert totals["orders"] == 2 and totals["orders_amount"] == "1500.00"
    assert totals["cancellations"] == 0 and totals["buyouts"] == 1
    assert totals["buyout_rate_percent"] == "50.0"

    with Session(s.engine) as db:
        set_actor(db, s.user_id)
        stored = db.scalar(
            select(WBRecord).where(
                WBRecord.store_id == s.store_id,
                WBRecord.source == Source.ORDERS,
                WBRecord.record_key == "o1",
            )
        )
        plain = s.vault.open(
            stored.ciphertext, context(s.workspace_id, s.store_id, Source.ORDERS, "o1")
        )
    assert "private-basket" not in plain and json.loads(plain)["finished_price"] == "1000"

    # A refresh re-delivers o2 as cancelled: the same order moves, it is not counted twice.
    newer, newer_task = make_run(s, Source.ORDERS)
    process(s, newer, newer_task, Page([order("o2", day, "500", cancelled=True)], {}, True))
    totals = orders_report(s, day)["totals"]
    assert totals["orders"] == 2 and totals["cancellations"] == 1
    assert totals["cancellations_amount"] == "500.00" and totals["net_orders"] == 1
    assert totals["cancel_rate_percent"] == "50.0" and totals["buyout_rate_percent"] == "100.0"

    response = client.get(path + f"/insights/orders?date_from={day}&date_to={day}")
    assert response.status_code == 200, response.text
    assert response.json()["totals"]["orders"] == 2
    data = client.get(path + "/data/orders").json()
    assert data["total"] == 2 and {item["srid"] for item in data["items"]} == {"o1", "o2"}


def test_orders_schedule_is_created_with_defaults(setup, owner_client):
    s = setup
    client, path = owner_client
    response = client.put(path + "/sync-schedule", json={})
    assert response.status_code == 200, response.text
    with Session(s.engine) as db:
        set_actor(db, s.user_id)
        plan = db.get(SyncSchedule, (s.workspace_id, s.store_id, Source.ORDERS))
    assert plan is not None and plan.enabled and plan.history_from is not None
