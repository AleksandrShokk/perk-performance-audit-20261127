from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session
from test_catalog import card, seed
from test_stock_cover import report
from test_wb_sync_database import owner_client as owner_client
from test_wb_sync_database import pytestmark as pytestmark
from test_wb_sync_database import setup as setup

from app.integrations.wildberries.data import Source
from app.modules.accounts.models import Store
from app.modules.auth.models import Membership
from app.modules.sync.models import SyncRun


def root(s):
    return f"/api/v1/workspaces/{s.workspace_id}/inventory"


def prepare(s):
    rows = [
        report(),
        report(nm_id="43", orders=0),
        report(nm_id="44", orders=None),
        report(nm_id="45", stock=0),
    ]
    seed(s, Source.CATALOG, [(row["nm_id"], card(article=row["nm_id"])) for row in rows])
    seed(s, Source.SUPPLY_DEMAND, [(row["nm_id"], {**row, "orders": 1}) for row in rows])
    seed(
        s,
        Source.STOCK_HISTORY,
        [(row["nm_id"], {**row, "stock": 9999}) for row in rows],
    )
    with Session(s.admin) as db, db.begin():
        runs = db.scalars(
            select(SyncRun).where(
                SyncRun.source.in_([Source.SUPPLY_DEMAND, Source.STOCK_HISTORY]),
                SyncRun.store_id == s.store_id,
            )
        )
        for run in runs:
            run.date_from = date(2026, 10, 1)
            run.date_to = date(2026, 10, 28)


def plan():
    return dict(
        external_id="p:7",
        supply_id="8",
        preorder_id="7",
        status="planned",
        planned_date="2026-11-09",
        actual_date=None,
        created_date="2026-11-01",
        destination="Пункт отгрузки",
        quantity=120,
        accepted_quantity=0,
        rejected=False,
    )


def test_replenishment_is_fbo_only_and_total_is_not_limited_to_preview(setup, owner_client):
    s, c = setup, owner_client[0]
    prepare(s)
    result = c.get(root(s) + "/replenishment", params={"limit": 1, "urgent_only": True})
    assert result.status_code == 200, result.text
    data = result.json()
    assert (
        data["recommended_units"] == 235
        and data["product_count"] == 2
        and data["urgent_count"] == 1
    )
    assert data["unknown_count"] == 1 and data["no_orders_count"] == 1 and data["partial"]
    assert data["items"][0]["nm_id"] == "45" and data["items"][0]["quantity"] == 150
    assert data["target_days"] == 30 and data["lead_time_days"] == 7
    page = c.get(root(s) + "/replenishment", params={"limit": 1, "offset": 1}).json()
    assert page["items"][0]["nm_id"] == "42" and page["items"][0]["quantity"] == 85


def test_no_feed_is_unknown_not_zero_and_confirmed_empty_supplies_are_empty(setup, owner_client):
    s, c = setup, owner_client[0]
    data = c.get(root(s) + "/replenishment").json()
    assert data["recommended_units"] is None and data["partial"]
    empty = c.get(root(s) + "/supplies").json()
    assert empty["incomplete"]
    seed(s, Source.SUPPLIES, [])
    empty = c.get(root(s) + "/supplies").json()
    assert not empty["incomplete"] and empty["count"] == 0 and not empty["items"]


def test_supply_permissions_and_employee_store_scope_apply_before_aggregation(setup, owner_client):
    from uuid import uuid4

    s, c = setup, owner_client[0]
    other_store = uuid4()
    with Session(s.admin) as db, db.begin():
        db.add(
            Store(
                id=other_store,
                workspace_id=s.workspace_id,
                name="Скрытый",
                marketplace="wildberries",
                external_seller_id=str(uuid4()),
                connection_status="connected",
            )
        )
    seed(s, Source.SUPPLIES, [("p:7", plan())])
    seed(s, Source.SUPPLIES, [("p:7", {**plan(), "quantity": 999})], store_id=other_store)
    with Session(s.admin) as db, db.begin():
        member = db.get(Membership, (s.user_id, s.workspace_id))
        member.role = "manager"
        member.permissions = ["inventory.read"]
        member.store_ids = [str(s.store_id)]
    data = c.get(root(s) + "/supplies").json()
    assert data["count"] == 1 and data["items"][0]["quantity"] == 120
    assert c.get(root(s) + "/supplies", params={"store_id": str(other_store)}).status_code == 404
    assert (
        c.get(f"/api/v1/workspaces/{s.workspace_id}/stores/{s.store_id}/data/supplies").status_code
        == 200
    )
    with Session(s.admin) as db, db.begin():
        db.get(Membership, (s.user_id, s.workspace_id)).permissions = []
    assert c.get(root(s) + "/supplies").status_code == 403
    assert c.get(root(s) + "/replenishment").status_code == 403
