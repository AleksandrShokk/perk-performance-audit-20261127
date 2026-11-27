from datetime import timedelta

from test_wb_funnel_database import row
from test_wb_sync_database import make_run, process
from test_wb_sync_database import owner_client as owner_client
from test_wb_sync_database import pytestmark as pytestmark
from test_wb_sync_database import setup as setup

from app.integrations.wildberries.data import Page, Source
from app.modules.sync.schemas import moscow_today
from app.workers import tasks


def test_year_during_import_queues_once_then_serves_the_saved_report(
    setup, owner_client, monkeypatch, isolated_settings
):
    s = setup
    client, path = owner_client
    end = moscow_today() - timedelta(days=1)
    run_id, task = make_run(s, Source.FUNNEL)
    process(s, run_id, task, Page([row(end)], {}, True))
    # A new import must not make every reader reprocess the whole year inline.
    make_run(s, Source.FUNNEL)
    queued = []
    monkeypatch.setattr(
        tasks.compute_insight, "apply_async", lambda **kw: queued.append(kw["args"])
    )
    params = {"date_from": str(end - timedelta(days=358)), "date_to": str(end)}
    endpoint = path + "/insights/funnel"
    for _ in range(2):
        response = client.get(endpoint, params=params)
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["status"] == "preparing" and data["totals"]["orders"] is None
    assert len(queued) == 1  # Redis lease covers concurrent and repeated reads.
    # The test API uses the per-test vault; the worker must use that same key.
    worker_settings = s.settings.model_copy(
        update={"security_file": isolated_settings.security_file}
    )
    monkeypatch.setattr(tasks, "get_settings", lambda: worker_settings)
    tasks.compute_insight.run(*queued[0])
    ready = client.get(endpoint, params=params)
    assert ready.status_code == 200, ready.text
    data = ready.json()
    assert data["status"] == "partial" and data["known_days"] == 1
    assert data["totals"]["orders"] == 10
    assert data["daily"][-1]["orders"] == 10
    assert data["daily"][0]["orders"] is None
    assert data["products"][0]["vendor_code"] == "a"
    assert len(queued) == 1
