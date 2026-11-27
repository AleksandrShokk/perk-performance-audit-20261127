from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session
from test_wb_sync_database import make_run, process, requeue
from test_wb_sync_database import owner_client as owner_client
from test_wb_sync_database import pytestmark as pytestmark
from test_wb_sync_database import setup as setup

from app.db.session import set_actor
from app.integrations.wildberries.data import Page, Source, WBError
from app.modules.auth.dependencies import now
from app.modules.insights import compute
from app.modules.sync.models import SyncSchedule, WBRecord


def row(day, nm=42, **changes):
    return {
        "day": str(day),
        "nmId": nm,
        "currency": "RUB",
        "vendorCode": "a",
        "openCount": 100,
        "cartCount": 20,
        "orderCount": 10,
        "buyoutCount": 6,
        "cancelCount": 2,
        "addToWishlist": 5,
        "orderSum": 1000,
        "buyoutSum": 600,
        "cancelSum": 200,
        **changes,
    }


def report(s, day):
    with Session(s.engine) as db, db.begin():
        set_actor(db, s.user_id)
        return compute.build(
            "funnel",
            {"date_from": str(day), "date_to": str(day)},
            db,
            None,
            s.vault,
            s.workspace_id,
            s.store_id,
        )


def test_funnel_staged_publication_and_empty_refresh_remove_old_data(setup, owner_client):
    s = setup
    client, path = owner_client
    day = now().date() - timedelta(days=1)
    run_id, task = make_run(s, Source.FUNNEL)
    process(s, run_id, task, Page([row(day)], {}, False))
    assert report(s, day)["status"] == "no_data"
    # Redelivery must not double the figures.
    process(s, run_id, requeue(s, run_id), Page([row(day)], {}, False))
    process(s, run_id, requeue(s, run_id), Page([], {}, True))
    result = report(s, day)
    assert result["status"] == "ready" and result["known_days"] == 1
    assert result["totals"]["opens"] == 100 and result["totals"]["buyout_percent"] == "75.0"
    assert result["buyouts_by"] == "order_date"
    endpoint = path + f"/insights/funnel?date_from={day}&date_to={day}"
    response = client.get(endpoint)
    assert response.status_code == 200, response.text
    assert response.json()["totals"]["orders"] == 10
    data = client.get(path + "/data/funnel")
    assert data.status_code == 200 and data.json()["total"] == 1

    # Refresh: previous data remains visible until all pages are published.
    newer, task = make_run(s, Source.FUNNEL)
    process(s, newer, task, Page([], {}, False))
    assert report(s, day)["totals"]["opens"] == 100
    process(s, newer, requeue(s, newer), Page([], {}, True))
    result = report(s, day)
    assert result["status"] == "ready" and result["totals"]["opens"] == 0
    assert result["products"] == []
    with Session(s.engine) as db:
        set_actor(db, s.user_id)
        assert db.scalar(select(WBRecord).where(WBRecord.source == Source.FUNNEL)) is None


def test_funnel_failed_refresh_preserves_published_and_currency_is_not_mixed(setup):
    s = setup
    day = now().date() - timedelta(days=1)
    run_id, task = make_run(s, Source.FUNNEL)
    process(s, run_id, task, Page([row(day), row(day, nm=43, currency="KZT")], {}, True))
    result = report(s, day)
    assert result["totals"]["opens"] == 200
    assert result["currency"] is None and result["totals"]["orders_amount"] is None
    newer, task = make_run(s, Source.FUNNEL)
    process(s, newer, task, error=WBError("wb_invalid_response"))
    assert report(s, day)["totals"]["orders"] == 20


def test_funnel_default_schedule_publishes_history_weekly(setup, owner_client):
    s = setup
    client, path = owner_client
    response = client.put(path + "/sync-schedule", json={})
    assert response.status_code == 200, response.text
    with Session(s.engine) as db:
        set_actor(db, s.user_id)
        schedule = db.get(SyncSchedule, (s.workspace_id, s.store_id, Source.FUNNEL))
        assert schedule.enabled and schedule.backfill_chunk_days == 7
