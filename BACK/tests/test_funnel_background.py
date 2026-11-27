from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import Mock

from fastapi import Response

from app.modules.insights import funnel, snapshots
from app.modules.insights.router import FunnelReport


def test_preparing_year_has_unknown_values_instead_of_zero_sales():
    start, end = date(2025, 11, 30), date(2026, 11, 23)
    report = FunnelReport.model_validate(
        {
            **funnel.preparing(start, end),
            "date_from": start,
            "date_to": end,
            "freshness": {"computed_at": datetime.now(UTC), "stale": True},
        }
    )
    assert report.status == "preparing"
    assert len(report.daily) == report.period_days == 359
    assert report.known_days == 0
    assert report.totals.orders is report.totals.orders_amount is None
    assert all(day.orders is day.orders_amount is None for day in report.daily)
    # Report polling continues; import-progress polling must not suppress it.
    assert report.is_loading is False


def test_cold_background_report_does_not_compute_or_wait_for_a_database_lock(monkeypatch):
    monkeypatch.setattr(snapshots, "params_key", lambda *_: "period-key")
    monkeypatch.setattr(snapshots, "store_revision", lambda *_: "revision")
    monkeypatch.setattr(snapshots, "meta", lambda *_: None)
    schedule = Mock(return_value=True)
    monkeypatch.setattr(snapshots, "schedule", schedule)
    db, compute = Mock(), Mock(side_effect=AssertionError("must run in worker"))
    state = SimpleNamespace(redis=object(), vault=object())
    request = SimpleNamespace(app=SimpleNamespace(state=state))
    identity = SimpleNamespace(user=SimpleNamespace(id="owner"))
    params = {"date_from": "2025-11-30", "date_to": "2026-11-23"}
    data, fresh = snapshots.serve(
        request,
        Response(),
        db,
        identity,
        "workspace",
        "store",
        "funnel",
        params,
        compute,
        cold_start=lambda: {"status": "preparing"},
    )
    assert data == {"status": "preparing"} and fresh["stale"]
    compute.assert_not_called()
    db.execute.assert_not_called()
    db.commit.assert_not_called()
    schedule.assert_called_once_with(
        state.redis, state.vault, "workspace", "store", "owner", "funnel", params
    )


def test_old_snapshot_stays_readable_while_background_refresh_is_pending(monkeypatch):
    current = SimpleNamespace(revision="old", computed_at=datetime.now(UTC))
    monkeypatch.setattr(snapshots, "params_key", lambda *_: "period-key")
    monkeypatch.setattr(snapshots, "store_revision", lambda *_: "new")
    monkeypatch.setattr(snapshots, "meta", lambda *_: current)
    existing = {"status": "ready", "totals": {"orders": 41}}
    monkeypatch.setattr(snapshots, "load", lambda *_: (current, existing))
    schedule = Mock(return_value=False)
    monkeypatch.setattr(snapshots, "schedule", schedule)
    state = SimpleNamespace(redis=object(), vault=object())
    response = Response()
    result, freshness = snapshots.serve(
        SimpleNamespace(app=SimpleNamespace(state=state), headers={}),
        response,
        Mock(),
        SimpleNamespace(user=SimpleNamespace(id="owner")),
        "workspace",
        "store",
        "funnel",
        {},
        Mock(side_effect=AssertionError("must not recompute")),
        cold_start=Mock(side_effect=AssertionError("must not replace saved report")),
    )
    assert result == existing and freshness["stale"]
    assert "etag" in response.headers
    schedule.assert_called_once()
