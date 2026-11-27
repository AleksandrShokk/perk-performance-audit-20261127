from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session
from test_wb_funnel_database import report, row
from test_wb_sync_database import make_run, process, requeue
from test_wb_sync_database import owner_client as owner_client
from test_wb_sync_database import pytestmark as pytestmark
from test_wb_sync_database import setup as setup

from app.db.session import set_actor
from app.integrations.wildberries.data import Page, Source, WBError
from app.modules.sync import funnel_summary
from app.modules.sync.models import SyncRun, WBDailyMetric, WBRecord
from app.modules.sync.schemas import moscow_today


def configure_run(s, run_id, **changes):
    changes.setdefault("date_to", moscow_today() - timedelta(days=1))
    with Session(s.engine) as db, db.begin():
        set_actor(db, s.user_id)
        run = db.get(SyncRun, run_id)
        for key, value in changes.items():
            setattr(run, key, value)


def test_complete_day_is_visible_while_other_days_are_loading(setup):
    s = setup
    last = moscow_today() - timedelta(days=1)
    run_id, task = make_run(s, Source.FUNNEL)
    configure_run(s, run_id, date_from=last - timedelta(days=6), cursor={"direction": "desc"})
    next_cursor = {"direction": "desc", "day": str(last - timedelta(days=1)), "offset": 0}
    page = Page([row(last)], next_cursor, False)
    process(s, run_id, task, page)
    assert report(s, last)["totals"]["orders"] == 10
    assert report(s, last - timedelta(days=1))["status"] == "no_data"
    # A repeated page replaces its contribution instead of counting it twice.
    process(s, run_id, requeue(s, run_id), page)
    assert report(s, last)["totals"]["orders"] == 10
    empty_day = {"direction": "desc", "day": str(last - timedelta(days=2)), "offset": 0}
    process(s, run_id, requeue(s, run_id), Page([], empty_day, False))
    assert report(s, last - timedelta(days=1))["totals"]["orders"] == 0


def test_a_day_is_not_visible_until_all_of_its_product_pages_arrive(setup):
    s = setup
    last = moscow_today() - timedelta(days=1)
    run_id, task = make_run(s, Source.FUNNEL)
    configure_run(s, run_id, date_from=last - timedelta(days=6), cursor={"direction": "desc"})
    cursor = {"direction": "desc", "day": str(last), "offset": 1000}
    process(s, run_id, task, Page([row(last)], cursor, False))
    assert report(s, last)["status"] == "no_data"
    cursor = {"direction": "desc", "day": str(last - timedelta(days=1)), "offset": 0}
    process(s, run_id, requeue(s, run_id), Page([row(last, nm=43)], cursor, False))
    assert report(s, last)["totals"]["orders"] == 20


def test_failed_preview_returns_to_previous_successful_day(setup):
    s = setup
    last = moscow_today() - timedelta(days=1)
    old, task = make_run(s, Source.FUNNEL)
    configure_run(s, old, date_from=last)
    process(s, old, task, Page([row(last)], {}, True))
    run_id, task = make_run(s, Source.FUNNEL)
    configure_run(s, run_id, date_from=last - timedelta(days=6), cursor={"direction": "desc"})
    cursor = {"direction": "desc", "day": str(last - timedelta(days=1)), "offset": 0}
    process(s, run_id, task, Page([row(last, orderCount=20)], cursor, False))
    assert report(s, last)["totals"]["orders"] == 20
    process(s, run_id, requeue(s, run_id), error=WBError("wb_invalid_response"))
    assert report(s, last)["totals"]["orders"] == 10


def test_period_totals_publish_atomically_and_never_turn_into_daily_values(setup):
    s = setup
    last = moscow_today() - timedelta(days=1)
    start = last - timedelta(days=27)
    before_start, before_end = funnel_summary.previous(start, last)
    run_id, task = make_run(s, funnel_summary.SOURCE)
    configure_run(s, run_id, date_from=start, sync_mode="summary", cursor={"summary": True})

    def period_row(first, end, orders):
        data = row(first, orderCount=orders)
        del data["day"]
        return {**data, "period_from": str(first), "period_to": str(end)}

    data = [period_row(start, last, 10), period_row(before_start, before_end, 5)]
    cursor = {"summary": True, "offset": 1, "currency": "RUB"}
    process(s, run_id, task, Page(data, cursor, False))
    with Session(s.engine) as db:
        set_actor(db, s.user_id)
        assert (
            funnel_summary.read(db, s.vault, s.workspace_id, s.store_id, start, last)["status"]
            == "preparing"
        )
    process(s, run_id, requeue(s, run_id), Page([], cursor, True))
    with Session(s.engine) as db:
        set_actor(db, s.user_id)
        result = funnel_summary.read(db, s.vault, s.workspace_id, s.store_id, start, last)
        assert result["totals"]["orders"] == 10 and result["previous"]["totals"]["orders"] == 5
        assert result["freshness"]["stale"] is False
        assert db.scalar(select(func.count()).select_from(WBDailyMetric)) == 0
        assert db.scalar(select(func.count()).select_from(WBRecord)) == 0
        assert report(s, last)["status"] == "no_data"


def test_empty_successful_period_confirms_zero_and_summary_route_uses_cache(setup, owner_client):
    s = setup
    client, path = owner_client
    last = moscow_today() - timedelta(days=1)
    start = last - timedelta(days=6)
    run_id, task = make_run(s, funnel_summary.SOURCE)
    configure_run(s, run_id, date_from=start, sync_mode="summary", cursor={"summary": True})
    process(s, run_id, task, Page([], {"summary": True, "currency": "RUB"}, True))
    response = client.get(path + f"/insights/funnel/summary?date_from={start}&date_to={last}")
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["totals"]["orders"] == 0 and result["totals"]["orders_amount"] == "0.00"
    assert result["previous"]["totals"]["orders"] == 0 and result["currency"] == "RUB"
