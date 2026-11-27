import csv
import json
from io import StringIO

import pytest
from sqlalchemy.orm import Session
from test_mobile_supplies_flow import prepare
from test_supply_plans_flow import body, create, plan_url
from test_wb_sync_database import owner_client as owner_client
from test_wb_sync_database import pytestmark as pytestmark
from test_wb_sync_database import setup as setup

from app.modules.auth.models import Membership
from app.modules.supplies.models import SupplyPlan
from app.modules.supplies.plans import aad


def distributed(plan):
    data = body(plan)
    for i, item in enumerate(plan["items"]):
        data["items"][i]["quantity"] = item["quantity"] if i == 0 else 0
        data["items"][i]["variants"] = [
            dict(
                variant_id=v["variant_id"],
                quantity=(item["quantity"] if i == 0 and j == 0 else 0),
                barcode=v["barcodes"][0],
            )
            for j, v in enumerate(item["variants"])
        ]
    return data


def test_snapshot_uses_native_catalog_variant_identities_and_persists_distribution(
    setup, owner_client
):
    s, c = setup, owner_client[0]
    prepare(s)
    plan = create(s, c)
    catalog = c.get(f"/api/v1/workspaces/{s.workspace_id}/products").json()
    for row in plan["items"]:
        product = next(item for item in catalog["items"] if item["nm_id"] == row["nm_id"])
        assert {v["variant_id"] for v in row["variants"]} == {v["id"] for v in product["variants"]}
        assert len(row["variants"]) == 2
    assert plan["allocated_quantity"] == 0 and not plan["allocation_complete"]
    data = distributed(plan)
    response = c.put(plan_url(s, plan["id"]), json=data)
    assert response.status_code == 200, response.text
    saved = response.json()
    assert (
        saved["allocation_complete"] and saved["allocated_quantity"] == plan["items"][0]["quantity"]
    )
    assert c.get(plan_url(s, plan["id"])).json() == saved
    export = c.get(plan_url(s, plan["id"]) + "/items-export")
    assert export.status_code == 200 and "no-store" in export.headers["cache-control"]
    rows = list(csv.DictReader(StringIO(export.content.decode("utf-8-sig")), delimiter=";"))
    assert len(rows) == 1 and rows[0]["Штрихкод"].startswith("'00")
    assert int(rows[0]["Количество, шт."]) == saved["quantity"]
    assert rows[0]["ID варианта"] == "'" + saved["items"][0]["variants"][0]["external_id"]


@pytest.mark.parametrize("problem", ["extra", "duplicate", "foreign_barcode", "over", "metadata"])
def test_bad_variant_updates_do_not_change_a_saved_plan(setup, owner_client, problem):
    s, c = setup, owner_client[0]
    prepare(s)
    plan = create(s, c)
    data = distributed(plan)
    variants = data["items"][0]["variants"]
    if problem == "extra":
        variants[0]["variant_id"] = plan["items"][1]["variants"][0]["variant_id"]
    if problem == "duplicate":
        variants[1]["variant_id"] = variants[0]["variant_id"]
    if problem == "foreign_barcode":
        variants[0]["barcode"] = "99999999"
    if problem == "over":
        variants[0]["quantity"] += 1
    if problem == "metadata":
        variants[0]["size"] = "Injected"
    assert c.put(plan_url(s, plan["id"]), json=data).status_code == 422
    assert c.get(plan_url(s, plan["id"])).json()["revision"] == plan["revision"]


def test_incomplete_and_ambiguous_barcodes_cannot_be_exported_but_drafts_can_be_saved(
    setup, owner_client
):
    s, c = setup, owner_client[0]
    prepare(s)
    plan = create(s, c)
    assert c.get(plan_url(s, plan["id"]) + "/items-export").status_code == 409
    data = distributed(plan)
    data["items"][0]["variants"][0]["barcode"] = ""
    saved = c.put(plan_url(s, plan["id"]), json=data).json()
    assert not saved["allocation_complete"] and "штрихкод" in saved["allocation_error"]
    assert c.get(plan_url(s, plan["id"]) + "/items-export").status_code == 409
    data = distributed(saved)
    # Both catalog cards deliberately contain the same native barcode; never merge them.
    data["items"][1]["quantity"] = 1
    data["items"][1]["variants"][0]["quantity"] = 1
    saved = c.put(plan_url(s, plan["id"]), json=data).json()
    assert "нескольких" in saved["allocation_error"]
    assert c.get(plan_url(s, plan["id"]) + "/items-export").status_code == 409


def test_legacy_plans_load_sizes_explicitly_and_keep_their_quantities(setup, owner_client):
    s, c = setup, owner_client[0]
    prepare(s)
    plan = create(s, c)
    with Session(s.admin) as db, db.begin():
        row = db.get(SupplyPlan, (s.workspace_id, plan["id"]))
        payload = json.loads(s.vault.open(row.ciphertext, aad(row)))
        for item in payload["items"]:
            item.pop("variants")
        row.ciphertext = s.vault.seal(json.dumps(payload), aad(row))
    url = plan_url(s, plan["id"])
    legacy = c.get(url).json()
    assert all(not item["variants"] for item in legacy["items"])
    assert legacy["quantity"] == plan["quantity"]
    loaded = c.post(url + "/variants", json={"revision": plan["revision"]})
    assert loaded.status_code == 200, loaded.text
    assert (
        loaded.json()["revision"] == plan["revision"] + 1
        and loaded.json()["quantity"] == plan["quantity"]
    )
    assert all(item["variants"] for item in loaded.json()["items"])
    assert c.post(url + "/variants", json={"revision": plan["revision"]}).status_code == 409
    assert c.post(url + "/variants", json={"revision": plan["revision"] + 1}).status_code == 409


def test_loading_sizes_and_export_respect_employee_permissions(setup, owner_client):
    s, c = setup, owner_client[0]
    prepare(s)
    plan = create(s, c)
    with Session(s.admin) as db, db.begin():
        member = db.get(Membership, (s.user_id, s.workspace_id))
        member.role, member.permissions = "manager", ["inventory.read"]
    assert c.post(
        plan_url(s, plan["id"]) + "/variants", json={"revision": plan["revision"]}
    ).status_code in {
        403,
        404,
    }
    assert c.get(plan_url(s, plan["id"]) + "/items-export").status_code == 403
    assert c.get(plan_url(s, plan["id"])).status_code == 200
