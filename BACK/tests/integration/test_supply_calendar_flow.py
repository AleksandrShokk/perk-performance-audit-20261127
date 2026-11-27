from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session
from test_catalog import card, seed
from test_stock_cover import report
from test_wb_sync_database import owner_client as owner_client
from test_wb_sync_database import pytestmark as pytestmark
from test_wb_sync_database import setup as setup

from app.integrations.wildberries.data import Source
from app.modules.sync.models import SyncRun


def test_all_channel_demand_uses_fbo_stock_and_optional_fbs_credit_before_packaging(
    setup, owner_client
):
    s, c = setup, owner_client[0]
    seed(s, Source.CATALOG, [("42", card())])
    seed(s, Source.STOCK_HISTORY, [("42", report(orders=41, stock=9, missing_hours=653))])
    seed(s, Source.SUPPLY_DEMAND, [("42", report(orders=14, stock=0, missing_hours=653))])
    seed(s, Source.FBS, [("42:a", {"nm_id": "42", "quantity": 9})])
    with Session(s.admin) as db, db.begin():
        for run in db.scalars(
            select(SyncRun).where(
                SyncRun.store_id == s.store_id,
                SyncRun.source.in_([Source.STOCK_HISTORY, Source.SUPPLY_DEMAND]),
            )
        ):
            run.date_from, run.date_to = date(2026, 10, 1), date(2026, 10, 28)
    url = f"/api/v1/workspaces/{s.workspace_id}/inventory/replenishment"
    plain = c.get(url).json()
    assert plain["items"][0]["quantity"] == 44
    assert plain["items"][0]["stock"] == 0
    reduced = c.get(url, params={"include_fbs": True}).json()
    assert reduced["include_fbs"]
    assert reduced["items"][0]["quantity"] == 35
    assert reduced["items"][0]["fbs_reduction"] == 9
    target = f"/api/v1/workspaces/{s.workspace_id}/stores/{s.store_id}/inventory/packaging/42"
    assert c.put(target, json={"box_multiple": 6}).status_code == 200
    packed = c.get(url, params={"include_fbs": True}).json()["items"][0]
    assert packed["required_quantity"] == 35 and packed["quantity"] == 36
    created = c.post(
        f"/api/v1/workspaces/{s.workspace_id}/stores/{s.store_id}/inventory/plans",
        json={"title": "FBS credit", "include_fbs": True},
    )
    assert created.status_code == 201, created.text
    assert created.json()["include_fbs"] and created.json()["items"] == []
