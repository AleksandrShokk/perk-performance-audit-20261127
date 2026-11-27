from datetime import timedelta
from unittest.mock import Mock

from sqlalchemy import select
from sqlalchemy.orm import Session
from test_funnel_progress_database import configure_run
from test_wb_funnel_database import report, row
from test_wb_sync_database import owner_client as owner_client
from test_wb_sync_database import process
from test_wb_sync_database import pytestmark as pytestmark
from test_wb_sync_database import setup as setup

from app.db.session import set_actor
from app.integrations.wildberries.data import Page, Source, WBError
from app.modules.auth.models import Membership
from app.modules.sync import funnel_summary
from app.modules.sync.models import SyncRun, SyncSchedule
from app.modules.sync.schemas import moscow_today
from app.workers import tasks


def test_connect_starts_week_and_comparison_without_a_gap_before_history(setup, owner_client):
    s = setup
    client, path = owner_client
    response = client.put(path + "/sync-schedule", json={"sources": ["funnel"]})
    assert response.status_code == 200, response.text
    with Session(s.engine) as db:
        set_actor(db, s.user_id)
        plan = db.get(SyncSchedule, (s.workspace_id, s.store_id, Source.FUNNEL))
        runs = db.scalars(select(SyncRun).order_by(SyncRun.created_at)).all()
        daily = next(run for run in runs if run.source == Source.FUNNEL)
        summary = next(run for run in runs if run.source == funnel_summary.SOURCE)
        assert (daily.date_to - daily.date_from).days == 6
        assert plan.backfill_to == daily.date_from - timedelta(days=1)
        assert plan.history_from == daily.date_to - timedelta(days=27)
        assert summary.date_from == daily.date_from and summary.date_to == daily.date_to
        daily_id, end = daily.id, daily.date_to
    configure_run(s, daily_id, task_id="synthetic-page")
    process(s, daily_id, "synthetic-page", Page([row(end)], {}, True))
    with Session(s.engine) as db:
        set_actor(db, s.user_id)
        plan = db.get(SyncSchedule, (s.workspace_id, s.store_id, Source.FUNNEL))
        assert plan.recent_completed
        assert plan.backfill_to == end - timedelta(days=7)


def test_summary_enqueue_is_deduplicated_and_allows_other_periods(setup):
    s = setup
    last = moscow_today() - timedelta(days=1)
    with Session(s.engine) as db, db.begin():
        set_actor(db, s.user_id)
        for days in (7, 7, 28):
            funnel_summary.enqueue(
                db,
                s.vault,
                s.workspace_id,
                s.store_id,
                s.user_id,
                last - timedelta(days=days - 1),
                last,
            )
        assert len(db.scalars(select(SyncRun)).all()) == 2


def test_member_can_request_period_only_while_membership_and_owner_plan_are_valid(
    setup, owner_client, monkeypatch
):
    s = setup
    client, path = owner_client
    assert client.put(path + "/sync-schedule", json={"sources": ["funnel"]}).status_code == 200
    with Session(s.admin) as db, db.begin():
        db.add(Membership(workspace_id=s.workspace_id, user_id=s.other_id, role="viewer"))
    monkeypatch.setattr(tasks, "build_engine", lambda _: s.engine)
    last = moscow_today() - timedelta(days=1)
    args = (
        str(s.workspace_id),
        str(s.store_id),
        str(s.other_id),
        str(last - timedelta(days=27)),
        str(last),
    )
    tasks.request_funnel_summary.run(*args)
    with Session(s.engine) as db:
        set_actor(db, s.user_id)
        runs = db.scalars(select(SyncRun).where(SyncRun.source == funnel_summary.SOURCE)).all()
        assert len(runs) == 2 and all(run.requested_by == s.user_id for run in runs)
    with Session(s.engine) as db:
        set_actor(db, s.user_id)
        plan = db.get(SyncSchedule, (s.workspace_id, s.store_id, Source.FUNNEL))
        assert plan.history_from == last - timedelta(days=27)
    tasks.request_funnel_summary.run(*args, True)
    with Session(s.engine) as db:
        set_actor(db, s.user_id)
        plan = db.get(SyncSchedule, (s.workspace_id, s.store_id, Source.FUNNEL))
        assert plan.history_from == last - timedelta(days=55)
    with Session(s.admin) as db, db.begin():
        member = db.get(Membership, (s.workspace_id, s.other_id))
        # Locate by columns: membership primary-key order is not part of this test.
        if member is None:
            member = db.scalar(
                select(Membership).where(
                    Membership.workspace_id == s.workspace_id, Membership.user_id == s.other_id
                )
            )
        db.delete(member)
    rejected = (*args[:3], str(last - timedelta(days=13)), str(last))
    tasks.request_funnel_summary.run(*rejected)
    with Session(s.engine) as db:
        set_actor(db, s.user_id)
        assert (
            len(db.scalars(select(SyncRun).where(SyncRun.source == funnel_summary.SOURCE)).all())
            == 2
        )


def test_summary_api_checks_access_and_validates_period_before_queueing(
    setup, owner_client, monkeypatch
):
    client, path = owner_client
    send = Mock()
    monkeypatch.setattr(tasks.request_funnel_summary, "apply_async", send)
    last = moscow_today() - timedelta(days=1)
    response = client.get(
        path + f"/insights/funnel/summary?date_from={last - timedelta(days=27)}&date_to={last}"
    )
    assert response.status_code == 200 and response.json()["status"] == "preparing"
    assert send.call_count == 1
    response = client.get(
        path + f"/insights/funnel/summary?date_from={last - timedelta(days=28)}&date_to={last}"
    )
    assert response.status_code == 422 and send.call_count == 1


def test_terminal_initial_error_does_not_leave_the_chart_loading_for_six_hours(setup, owner_client):
    s = setup
    client, path = owner_client
    assert client.put(path + "/sync-schedule", json={"sources": ["funnel"]}).status_code == 200
    with Session(s.engine) as db:
        set_actor(db, s.user_id)
        run = db.scalar(select(SyncRun).where(SyncRun.source == Source.FUNNEL))
        run_id, end = run.id, run.date_to
    configure_run(s, run_id, task_id="synthetic-failed-page")
    process(s, run_id, "synthetic-failed-page", error=WBError("wb_invalid_response"))
    result = report(s, end)
    assert result["status"] == "no_data" and result["is_loading"] is False
