import csv
from io import StringIO
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session
from test_mobile_supplies_flow import prepare, root
from test_wb_sync_database import owner_client as owner_client
from test_wb_sync_database import pytestmark as pytestmark
from test_wb_sync_database import setup as setup

from app.db.session import set_actor
from app.modules.accounts.models import Store
from app.modules.auth.models import Membership
from app.modules.supplies.models import SupplyPackaging


def packaging(s, store=None, key="42"):
    store_id = store or s.store_id
    return f"/api/v1/workspaces/{s.workspace_id}/stores/{store_id}/inventory/packaging/{key}"


def test_persistent_packaging_and_custom_horizon_are_applied_before_summary_filter_and_pagination(
    setup,
    owner_client,
):
    s, c = setup, owner_client[0]
    prepare(s)
    saved = c.put(packaging(s), json={"box_multiple": 6})
    assert saved.status_code == 200, saved.text
    assert c.put(packaging(s), json={"box_multiple": 6}).status_code == 200
    data = c.get(
        root(s) + "/replenishment", params={"limit": 1, "target_days": 14, "lead_time_days": 3}
    ).json()
    # Product 42: 5 * 14 - max(100 - 5 * 3, 0) = 0; out-of-stock product 45 needs 70.
    assert data["recommended_units"] == 70 and data["count"] == 1
    assert data["target_days"] == 14 and data["lead_time_days"] == 3
    normal = c.get(root(s) + "/replenishment", params={"limit": 1}).json()
    assert normal["recommended_units"] == 240  # 85 rounded to 90 + 150.
    second = c.get(root(s) + "/replenishment", params={"limit": 1, "offset": 1}).json()["items"][0]
    assert second["nm_id"] == "42" and second["required_quantity"] == 85
    assert second["quantity"] == 90 and second["box_multiple"] == 6
    with Session(s.admin) as db:
        assert (
            len(
                db.scalars(
                    select(SupplyPackaging).where(SupplyPackaging.workspace_id == s.workspace_id)
                ).all()
            )
            == 1
        )


def test_export_contains_every_filtered_item_and_needs_export_permission(setup, owner_client):
    s, c = setup, owner_client[0]
    prepare(s)
    c.put(packaging(s), json={"box_multiple": 6})
    response = c.get(root(s) + "/replenishment/export")
    assert response.status_code == 200, response.text
    assert all(
        value.strip() == "no-store" for value in response.headers["cache-control"].split(",")
    )
    rows = list(csv.DictReader(StringIO(response.content.decode("utf-8-sig")), delimiter=";"))
    assert len(rows) == 2 and sum(int(row["К поставке, шт."]) for row in rows) == 240
    urgent = c.get(root(s) + "/replenishment/export", params={"urgent_only": True})
    assert (
        len(list(csv.DictReader(StringIO(urgent.content.decode("utf-8-sig")), delimiter=";"))) == 1
    )
    with Session(s.admin) as db, db.begin():
        member = db.get(Membership, (s.user_id, s.workspace_id))
        member.role = "manager"
        member.permissions = ["inventory.read"]
    assert c.get(root(s) + "/replenishment/export").status_code == 403
    assert c.put(packaging(s), json={"box_multiple": 5}).status_code in {403, 404}
    assert c.get(root(s) + "/replenishment").status_code == 200


def test_packaging_is_scoped_to_store_and_rls_prevents_outside_access(setup, owner_client):
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
    assert c.put(packaging(s, other), json={"box_multiple": 100}).status_code == 200
    data = c.get(root(s) + "/replenishment", params={"store_id": str(s.store_id)}).json()
    assert data["recommended_units"] == 235
    with Session(s.admin) as db, db.begin():
        member = db.get(Membership, (s.user_id, s.workspace_id))
        member.role = "manager"
        member.permissions = ["inventory.read"]
        member.store_ids = [str(s.store_id)]
    assert c.put(packaging(s, other), json={"box_multiple": 5}).status_code == 404
    with Session(s.engine) as db, db.begin():
        set_actor(db, s.user_id)
        assert db.scalar(select(SupplyPackaging).where(SupplyPackaging.store_id == other)) is None


def test_bad_parameters_and_unknown_report_do_not_export_made_up_data(setup, owner_client):
    s, c = setup, owner_client[0]
    for params in [
        {"target_days": 0},
        {"target_days": 181},
        {"lead_time_days": -1},
        {"lead_time_days": 91},
        {"target_days": "1.5"},
    ]:
        assert c.get(root(s) + "/replenishment", params=params).status_code == 422
        assert c.get(root(s) + "/replenishment/export", params=params).status_code == 422
    assert c.get(root(s) + "/replenishment/export").status_code == 409
    for value in [0, -1, 10001, 1.5, True]:
        assert c.put(packaging(s), json={"box_multiple": value}).status_code == 422


def test_admin_can_configure_packaging(setup, owner_client):
    s, c = setup, owner_client[0]
    with Session(s.admin) as db, db.begin():
        db.get(Membership, (s.user_id, s.workspace_id)).role = "admin"
    response = c.put(packaging(s), json={"box_multiple": 5})
    assert response.status_code == 200, response.text
