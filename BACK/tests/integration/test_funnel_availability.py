from datetime import timedelta
from uuid import uuid4

from test_catalog import employee
from test_funnel_progress_database import configure_run
from test_wb_sync_database import make_run, process
from test_wb_sync_database import owner_client as owner_client
from test_wb_sync_database import pytestmark as pytestmark
from test_wb_sync_database import setup as setup

from app.integrations.wildberries.data import Page, Source
from app.modules.sync.schemas import history_limits, moscow_today


def test_availability_includes_provider_window_even_before_history_is_loaded(setup, owner_client):
    s = setup
    client, path = owner_client
    response = client.get(path + "/insights/funnel/availability")
    assert response.status_code == 200, response.text
    assert response.json() == {
        "date_from": str(history_limits()[Source.FUNNEL]["date_from"]),
        "date_to": str(moscow_today() - timedelta(days=1)),
    }
    assert "no-store" in response.headers["cache-control"]
    foreign = path.replace(str(s.store_id), str(uuid4()))
    assert client.get(foreign + "/insights/funnel/availability").status_code == 404


def test_retained_history_remains_selectable_outside_provider_window(setup, owner_client):
    s = setup
    client, path = owner_client
    day = moscow_today() - timedelta(days=500)
    run, task = make_run(s, Source.FUNNEL)
    configure_run(s, run, date_from=day, date_to=day)
    # A completed empty day is valid history too; no fake order is needed to unlock it.
    process(s, run, task, Page([], {}, True))
    data = client.get(path + "/insights/funnel/availability").json()
    assert data["date_from"] == str(day)
    employee(s, ["analytics.read"], [str(s.store_id)])
    assert client.get(path + "/insights/funnel/availability").json() == data
    progress = client.get(
        path + "/insights/funnel/progress", params={"date_from": str(day), "date_to": str(day)}
    )
    assert progress.status_code == 200, progress.text


def test_availability_requires_analytics_access(setup, owner_client):
    s = setup
    client, path = owner_client
    employee(s, ["finance.read"], [str(s.store_id)])
    assert client.get(path + "/insights/funnel/availability").status_code == 403


def test_analytics_reader_cannot_read_another_stores_availability(setup, owner_client):
    s = setup
    client, path = owner_client
    employee(s, ["analytics.read"], [str(uuid4())])
    assert client.get(path + "/insights/funnel/availability").status_code == 404
