from datetime import timedelta

from sqlalchemy.orm import Session
from test_wb_sync_database import make_run, process
from test_wb_sync_database import owner_client as owner_client
from test_wb_sync_database import pytestmark as pytestmark
from test_wb_sync_database import setup as setup

from app.db.session import set_actor
from app.integrations.wildberries.data import Page, Source
from app.modules.auth.dependencies import now
from app.modules.insights import compute
from app.modules.sync.models import SyncRun


def wb_row(day, **changes):
    return {
        "srid": "mp.abc.r",
        "shkId": 1001,
        "nmId": 42,
        "sku": "200",
        "techSize": "M",
        "subjectName": "Бирки",
        "brand": "dub",
        "returnType": "Возврат брака",
        "returnStatus": "Готов к выдаче",
        "orderDt": str(day - timedelta(days=20)),
        "readyToReturnDt": f"{day}T08:00:00",
        "completedDt": "",
        "expiredDt": f"{day + timedelta(days=10)}T08:00:00",
        "dstOfficeId": 310105,
        "dstOfficeAddress": "ПВЗ",
        "kiz": "private-marking-code",
        **changes,
    }


def report(s, day):
    with Session(s.engine) as db, db.begin():
        set_actor(db, s.user_id)
        params = {"date_from": str(day), "date_to": str(day)}
        return compute.build("returns", params, db, None, s.vault, s.workspace_id, s.store_id)


def test_returns_publish_and_status_update_without_duplicates(setup, owner_client):
    s = setup
    client, path = owner_client
    day = now().date() - timedelta(days=1)
    run_id, task = make_run(s, Source.RETURNS)
    process(s, run_id, task, Page([wb_row(day)], {}, True))
    result = report(s, day)
    assert result["status"] == "ready" and result["totals"]["returns"] == 1
    assert result["pickup"]["awaiting"] == 1 and result["pickup"]["items"][0]["days_left"] >= 9

    # Re-read: the seller collected the item. Same record, now completed.
    newer, task = make_run(s, Source.RETURNS)
    collected = wb_row(day, returnStatus="Выдан продавцу", completedDt=f"{day}T15:00:00")
    process(s, newer, task, Page([collected], {}, True))
    result = report(s, day)
    assert result["totals"]["returns"] == 1 and result["pickup"]["awaiting"] == 0
    assert result["by_status"] == [{"name": "Выдан продавцу", "count": 1}]
    with Session(s.engine) as db:
        set_actor(db, s.user_id)
        assert db.get(SyncRun, newer).status == "succeeded"

    response = client.get(path + f"/insights/returns?date_from={day}&date_to={day}")
    assert response.status_code == 200, response.text
    assert response.json()["date_basis"] == "ready_for_pickup"
    data = client.get(path + "/data/returns").json()
    assert data["total"] == 1 and "kiz" not in data["items"][0]
    assert "private-marking-code" not in str(data)
