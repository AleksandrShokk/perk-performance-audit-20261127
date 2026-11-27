from datetime import timedelta
from uuid import uuid4

from test_funnel_progress_database import configure_run
from test_wb_funnel_database import row
from test_wb_sync_database import make_run, process, requeue
from test_wb_sync_database import owner_client as owner_client
from test_wb_sync_database import pytestmark as pytestmark
from test_wb_sync_database import setup as setup

from app.integrations.wildberries.data import Page, Source
from app.modules.sync.schemas import moscow_today


def test_light_progress_and_report_publish_complete_days_before_run_finishes(setup, owner_client):
    s = setup
    client, path = owner_client
    end = moscow_today() - timedelta(days=1)
    start = end - timedelta(days=6)
    params = {"date_from": str(start), "date_to": str(end)}
    run, task = make_run(s, Source.FUNNEL)
    configure_run(s, run, date_from=start, cursor={"direction": "desc"})
    base = path + "/insights/funnel"
    before = client.get(base + "/progress", params=params)
    assert before.status_code == 200, before.text
    assert before.json()["is_loading"] and before.json()["known_days"] == 0
    cursor = {"direction": "desc", "day": str(end - timedelta(days=1)), "offset": 0}
    process(s, run, task, Page([row(end)], cursor, False))
    live = client.get(base + "/progress", params=params).json()
    assert live["known_days"] == 1 and live["records_processed"] == 1
    assert live["revision"] != before.json()["revision"]
    data = client.get(base, params=params)
    assert data.status_code == 200, data.text
    assert data.json()["daily"][-1]["orders"] == 10
    assert data.json()["daily"][0]["orders"] is None
    cursor = {"direction": "desc", "day": str(end - timedelta(days=2)), "offset": 0}
    process(s, run, requeue(s, run), Page([row(end - timedelta(days=1))], cursor, False))
    assert client.get(base + "/progress", params=params).json()["known_days"] == 2
    assert client.get(base, params=params).json()["daily"][-2]["orders"] == 10
    foreign = path.replace(str(s.store_id), str(uuid4()))
    assert client.get(foreign + "/insights/funnel/progress", params=params).status_code == 404
