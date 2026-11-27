from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session
from test_catalog import seed
from test_mobile_supplies_flow import plan, prepare, root
from test_wb_sync_database import owner_client as owner_client
from test_wb_sync_database import pytestmark as pytestmark
from test_wb_sync_database import setup as setup

from app.integrations.wildberries.data import Source
from app.modules.auth.dependencies import now
from app.modules.sync.models import SyncRun
from app.modules.sync.schemas import moscow_today


def native(s, **changes):
    row = {
        **plan(),
        "planned_date": str(moscow_today()),
        "goods_complete": True,
        "goods": [{"product_key": "42", "quantity": 50}],
        "checked_at": now().isoformat(),
        **changes,
    }
    seed(s, Source.SUPPLIES, [("p:7", row)])
    with Session(s.admin) as db, db.begin():
        run = db.scalar(
            select(SyncRun).where(SyncRun.store_id == s.store_id, SyncRun.source == Source.SUPPLIES)
        )
        run.started_at = now()


def test_native_incoming_reduces_before_box_rounding_summary_export_and_plan_snapshot(
    setup, owner_client
):
    s, c = setup, owner_client[0]
    prepare(s)
    native(s)
    c.put(
        f"/api/v1/workspaces/{s.workspace_id}/stores/{s.store_id}/inventory/packaging/42",
        json={"box_multiple": 6},
    )
    response = c.get(root(s) + "/replenishment", params={"limit": 1, "offset": 1})
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["recommended_units"] == 186 and data["incoming_units"] == 50
    item = data["items"][0]
    assert item["nm_id"] == "42" and item["quantity"] == 36 and item["required_quantity"] == 35
    assert item["incoming_quantity"] == 50 and item["incoming_reduction"] == 50
    urgent = c.get(root(s) + "/replenishment", params={"urgent_only": True}).json()
    assert urgent["recommended_units"] == 186 and urgent["items"][0]["quantity"] == 150
    exported = c.get(root(s) + "/replenishment/export")
    assert exported.status_code == 200 and "Снижение потребности" in exported.content.decode(
        "utf-8-sig"
    )


def test_missing_stale_and_past_shipments_do_not_invent_zeroes_or_reduce_need(setup, owner_client):
    s, c = setup, owner_client[0]
    prepare(s)
    data = c.get(root(s) + "/replenishment").json()
    assert not data["incoming_complete"] and data["incoming_units"] is None
    native(s, planned_date=str(moscow_today() - timedelta(days=1)))
    data = c.get(root(s) + "/replenishment").json()
    assert data["recommended_units"] == 235 and data["incoming_units"] == 50
    with Session(s.admin) as db, db.begin():
        run = db.scalar(
            select(SyncRun).where(SyncRun.store_id == s.store_id, SyncRun.source == Source.SUPPLIES)
        )
        run.started_at = run.finished_at = now() - timedelta(hours=3)
    data = c.get(root(s) + "/replenishment").json()
    assert data["incoming_units"] is None and data["recommended_units"] == 235


def test_terminal_shipment_removes_incoming_without_changing_stock(setup, owner_client):
    s, c = setup, owner_client[0]
    prepare(s)
    native(s, status="accepted", accepted_quantity=50)
    data = c.get(root(s) + "/replenishment").json()
    assert data["incoming_units"] == 0 and data["recommended_units"] == 235


def test_saved_perk_plans_never_count_as_native_shipments_and_new_snapshots_freeze_the_deduction(
    setup, owner_client
):
    from test_supply_plans_flow import create, plan_url

    s, c = setup, owner_client[0]
    prepare(s)
    internal = create(s, c)
    assert c.get(root(s) + "/replenishment").json()["recommended_units"] == 235
    native(s)
    saved = create(s, c)
    assert saved["quantity"] == 185
    first = next(row for row in saved["items"] if row["nm_id"] == "42")
    assert first["incoming_quantity"] == 50 and first["incoming_reduction"] == 50
    assert c.get(plan_url(s, internal["id"])).json()["quantity"] == 235
    with Session(s.admin) as db, db.begin():
        run = db.scalar(
            select(SyncRun).where(SyncRun.store_id == s.store_id, SyncRun.source == Source.SUPPLIES)
        )
        run.started_at = run.finished_at = now() - timedelta(hours=3)
    assert c.get(plan_url(s, saved["id"])).json() == saved
    assert c.get(root(s) + "/replenishment").json()["recommended_units"] == 235


def test_incoming_never_leaks_between_cabinets_or_to_an_employee_without_store_access(
    setup, owner_client
):
    from uuid import uuid4

    from app.modules.accounts.models import Store
    from app.modules.auth.models import Membership

    s, c = setup, owner_client[0]
    prepare(s)
    other = uuid4()
    with Session(s.admin) as db, db.begin():
        db.add(
            Store(
                id=other,
                workspace_id=s.workspace_id,
                name="Other",
                marketplace="wildberries",
                external_seller_id=str(uuid4()),
                connection_status="connected",
            )
        )
    seed(
        s,
        Source.SUPPLIES,
        [
            (
                "p:7",
                {
                    **plan(),
                    "goods_complete": True,
                    "goods": [{"product_key": "42", "quantity": 999}],
                    "planned_date": str(moscow_today()),
                },
            )
        ],
        store_id=other,
    )
    response = c.get(root(s) + "/replenishment", params={"store_id": str(s.store_id)})
    assert response.json()["recommended_units"] == 235
    with Session(s.admin) as db, db.begin():
        member = db.get(Membership, (s.user_id, s.workspace_id))
        member.role, member.permissions, member.store_ids = (
            "manager",
            ["inventory.read"],
            [str(s.store_id)],
        )
    assert c.get(root(s) + "/replenishment", params={"store_id": str(other)}).status_code == 404
    assert c.get(root(s) + "/replenishment").json()["incoming_units"] is None
