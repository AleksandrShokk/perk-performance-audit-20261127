import csv
from io import StringIO
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from supply_plan_helpers import select_recommendations
from test_mobile_supplies_flow import prepare, root
from test_wb_sync_database import owner_client as owner_client
from test_wb_sync_database import pytestmark as pytestmark
from test_wb_sync_database import setup as setup

from app.db.session import set_actor
from app.modules.accounts.models import Store
from app.modules.auth.models import Membership
from app.modules.supplies.models import SupplyPlan


def create_url(s, store=None):
    return f"/api/v1/workspaces/{s.workspace_id}/stores/{store or s.store_id}/inventory/plans"


def plan_url(s, plan_id=None):
    return root(s) + "/plans" + (f"/{plan_id}" if plan_id else "")


def body(plan, **changes):
    return (
        dict(
            revision=plan["revision"],
            title=plan["title"],
            destination=plan["destination"],
            status=plan["status"],
            items=[
                dict(product_key=i["product_key"], quantity=i["quantity"]) for i in plan["items"]
            ],
        )
        | changes
    )


def create(s, c, **changes):
    response = c.post(
        create_url(s), json={"title": "Поставка для теста", "destination": "Коледино"} | changes
    )
    assert response.status_code == 201, response.text
    plan = response.json()
    return select_recommendations(c, plan_url(s, plan["id"]), plan)


def test_plan_captures_all_products_and_does_not_follow_live_recommendations(setup, owner_client):
    s, c = setup, owner_client[0]
    prepare(s)
    plan = create(s, c)
    assert plan["quantity"] == 235 and plan["product_count"] == 2
    assert plan["revision"] == 3 and plan["status"] == "draft"
    assert {row["product_key"] for row in plan["items"]} == {"42", "45"}
    c.put(
        f"/api/v1/workspaces/{s.workspace_id}/stores/{s.store_id}/inventory/packaging/42",
        json={"box_multiple": 100},
    )
    fetched = c.get(plan_url(s, plan["id"])).json()
    assert fetched == plan
    page = c.get(plan_url(s), params={"store_id": str(s.store_id), "limit": 1}).json()
    assert page["count"] == 1 and page["items"][0]["id"] == plan["id"]
    with Session(s.admin) as db:
        row = db.get(SupplyPlan, (s.workspace_id, plan["id"]))
        assert plan["title"] not in row.ciphertext and "Коледино" not in row.ciphertext


def test_quantities_round_trip_zeroes_and_revision_conflict(setup, owner_client):
    s, c = setup, owner_client[0]
    prepare(s)
    plan = create(s, c, target_days=14, lead_time_days=3)
    assert plan["quantity"] == 70 and plan["product_count"] == 1
    changes = body(plan, title="План на 14 дней", status="ready")
    changes["items"][0]["quantity"] = 60
    saved = c.put(plan_url(s, plan["id"]), json=changes)
    assert saved.status_code == 200, saved.text
    assert saved.json()["revision"] == plan["revision"] + 1 and saved.json()["quantity"] == 60
    assert saved.json()["items"][0]["recommended_quantity"] == 70
    assert c.put(plan_url(s, plan["id"]), json=changes).status_code == 409
    archived = c.put(plan_url(s, plan["id"]), json=body(saved.json(), status="archived"))
    assert archived.status_code == 200 and archived.json()["status"] == "archived"
    assert c.get(plan_url(s, plan["id"])).json()["quantity"] == 60


def test_invalid_quantities_and_product_metadata_cannot_corrupt_snapshot(setup, owner_client):
    s, c = setup, owner_client[0]
    prepare(s)
    c.put(
        f"/api/v1/workspaces/{s.workspace_id}/stores/{s.store_id}/inventory/packaging/42",
        json={"box_multiple": 6},
    )
    plan = create(s, c)
    data = body(plan)
    data["items"] = [{"product_key": "42", "quantity": 1}, {"product_key": "45", "quantity": 0}]
    assert c.put(plan_url(s, plan["id"]), json=data).status_code == 422
    for items in [
        [data["items"][0], data["items"][0]],
        [{"product_key": "42", "quantity": True}, {"product_key": "45", "quantity": 0}],
        [{"product_key": "42", "quantity": 1.5}, {"product_key": "45", "quantity": 0}],
        [
            {"product_key": "42", "quantity": 6, "title": "Injected"},
            {"product_key": "45", "quantity": 0},
        ],
        [{"product_key": "wrong", "quantity": 6}, {"product_key": "45", "quantity": 0}],
    ]:
        assert c.put(plan_url(s, plan["id"]), json=body(plan, items=items)).status_code == 422
    zeroes = [dict(product_key=i["product_key"], quantity=0) for i in plan["items"]]
    assert (
        c.put(plan_url(s, plan["id"]), json=body(plan, status="ready", items=zeroes)).status_code
        == 422
    )
    assert c.get(plan_url(s, plan["id"])).json()["revision"] == plan["revision"]


def test_export_uses_saved_quantities_and_protects_identifiers_and_cache(setup, owner_client):
    s, c = setup, owner_client[0]
    prepare(s)
    plan = create(s, c, title="=test", destination="+formula")
    changes = body(plan)
    changes["items"][0]["quantity"] = 0
    assert c.put(plan_url(s, plan["id"]), json=changes).status_code == 200
    result = c.get(plan_url(s, plan["id"]) + "/export")
    assert result.status_code == 200 and "no-store" in result.headers["cache-control"]
    rows = list(csv.DictReader(StringIO(result.content.decode("utf-8-sig")), delimiter=";"))
    assert len(rows) == 1
    assert rows[0]["План"] == "'=test" and rows[0]["Склад / кластер"] == "'+formula"
    assert rows[0]["Артикул площадки"].startswith("'")
    assert int(rows[0]["К поставке, шт."]) == changes["items"][1]["quantity"]


@pytest.mark.parametrize("role", ["manager", "viewer", "admin"])
def test_plan_permissions_and_read_only_access(setup, owner_client, role):
    s, c = setup, owner_client[0]
    prepare(s)
    plan = create(s, c)
    with Session(s.admin) as db, db.begin():
        member = db.get(Membership, (s.user_id, s.workspace_id))
        member.role = role
        member.permissions = ["inventory.read"]
    assert c.get(plan_url(s)).status_code == 200
    assert c.get(plan_url(s, plan["id"])).status_code == 200
    expected = 200 if role == "admin" else 403
    assert c.put(plan_url(s, plan["id"]), json=body(plan)).status_code in (
        {200} if role == "admin" else {403, 404}
    )
    assert c.post(create_url(s), json={"title": "Новый"}).status_code in (
        {201} if role == "admin" else {403, 404}
    )
    assert c.get(plan_url(s, plan["id"]) + "/export").status_code == expected


def test_store_restriction_is_enforced_by_api_and_rls(setup, owner_client):
    s, c = setup, owner_client[0]
    prepare(s)
    plan = create(s, c)
    other = uuid4()
    with Session(s.admin) as db, db.begin():
        db.add(
            Store(
                id=other,
                workspace_id=s.workspace_id,
                name="Other",
                marketplace="wildberries",
                external_seller_id=str(other),
                connection_status="connected",
            )
        )
        member = db.get(Membership, (s.user_id, s.workspace_id))
        member.role, member.permissions, member.store_ids = (
            "manager",
            ["inventory.read", "reports.export"],
            [str(other)],
        )
    assert c.get(plan_url(s)).json()["count"] == 0
    assert c.get(plan_url(s, plan["id"])).status_code == 404
    assert c.get(plan_url(s, plan["id"]) + "/export").status_code == 404
    assert c.get(plan_url(s), params={"store_id": str(s.store_id)}).status_code == 404
    with Session(s.engine) as db, db.begin():
        set_actor(db, s.user_id)
        assert (
            db.scalar(select(SupplyPlan).where(SupplyPlan.workspace_id == s.workspace_id)) is None
        )
    with Session(s.admin) as db, db.begin():
        db.get(Membership, (s.user_id, s.workspace_id)).permissions = []
    assert c.get(plan_url(s)).status_code == 403
    assert c.get(plan_url(s, plan["id"])).status_code == 403


def test_no_report_or_invalid_parameters_do_not_create_a_plan(setup, owner_client):
    s, c = setup, owner_client[0]
    response = c.post(create_url(s), json={"title": "Test"})
    assert response.status_code == 201
    assert response.json()["items"] == []
    for values in [
        {"title": " "},
        {"title": "x", "target_days": 0},
        {"title": "x", "lead_time_days": 91},
        {"title": "x", "target_days": True},
    ]:
        assert c.post(create_url(s), json=values).status_code == 422
    assert c.get(plan_url(s)).json()["count"] == 1
    assert c.get(plan_url(s, uuid4())).status_code == 404
