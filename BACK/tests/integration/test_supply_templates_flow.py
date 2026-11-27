from io import BytesIO
from uuid import uuid4
from zipfile import ZipFile

import pytest
from sqlalchemy.orm import Session
from test_mobile_supplies_flow import prepare
from test_supply_plans_flow import create, plan_url
from test_supply_templates import template, values
from test_supply_variants_flow import distributed
from test_wb_sync_database import owner_client as owner_client
from test_wb_sync_database import pytestmark as pytestmark
from test_wb_sync_database import setup as setup

from app.modules.auth.models import Membership


def file(raw):
    return {
        "file": (
            "original.xlsx",
            raw,
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    }


def prepared(s, c):
    prepare(s)
    plan = create(s, c)
    result = c.put(plan_url(s, plan["id"]), json=distributed(plan))
    assert result.status_code == 200, result.text
    return result.json(), plan_url(s, plan["id"]) + "/template"


def params(meta, **changes):
    choice = next(row for row in meta["choices"] if row["value"] == "barcode")
    return {
        **meta["suggested"],
        "revision": meta["revision"],
        "digest": meta["digest"],
        "data_digest": choice["data_digest"],
    } | changes


def test_upload_inspect_fill_preserves_the_original_template_and_plan(setup, owner_client):
    s, c = setup, owner_client[0]
    plan, url = prepared(s, c)
    # A valid 80 KB workbook crosses the ordinary 64 KB body limit only on upload routes.
    raw = template(
        extra={"docProps/custom.xml": b"<Properties><!--" + b"a" * 80000 + b"--></Properties>"}
    )
    inspected = c.post(url + "/inspect", files=file(raw))
    assert inspected.status_code == 200, inspected.text
    meta = inspected.json()
    assert (
        meta["suggested"]["identifier_column"] == "A"
        and meta["suggested"]["quantity_column"] == "B"
    )
    assert meta["choices"][0]["count"] == 1
    filled = c.post(url + "/fill", params=params(meta), files=file(raw))
    assert filled.status_code == 200, filled.text
    assert "no-store" in filled.headers["cache-control"]
    grid = values(filled.content)
    assert grid[2] == {"A": plan["items"][0]["variants"][0]["barcode"], "B": str(plan["quantity"])}
    with ZipFile(BytesIO(filled.content)) as book, ZipFile(BytesIO(raw)) as before:
        assert book.read("docProps/custom.xml") == before.read("docProps/custom.xml")
    assert c.get(plan_url(s, plan["id"])).json()["revision"] == plan["revision"]


@pytest.mark.parametrize("problem", ["revision", "digest", "data_digest", "columns", "first_row"])
def test_stale_or_incorrect_mapping_does_not_create_a_file(setup, owner_client, problem):
    s, c = setup, owner_client[0]
    _, url = prepared(s, c)
    raw = template()
    meta = c.post(url + "/inspect", files=file(raw)).json()
    changes = {
        "revision": {"revision": 999},
        "digest": {"digest": "0" * 64},
        "data_digest": {"data_digest": "0" * 64},
        "columns": {"quantity_column": "A"},
        "first_row": {"first_row": 1},
    }[problem]
    result = c.post(url + "/fill", params=params(meta, **changes), files=file(raw))
    assert result.status_code == (
        409 if problem in {"revision", "digest", "data_digest"} else 422
    ), result.text


def test_read_only_export_permission_is_required_and_store_scope_is_preserved(setup, owner_client):
    s, c = setup, owner_client[0]
    _, url = prepared(s, c)
    with Session(s.admin) as db, db.begin():
        member = db.get(Membership, (s.user_id, s.workspace_id))
        member.role, member.permissions = "manager", ["inventory.read", "reports.export"]
    raw = template()
    response = c.post(url + "/inspect", files=file(raw))
    assert response.status_code == 200, response.text
    assert c.post(url + "/fill", params=params(response.json()), files=file(raw)).status_code == 200
    with Session(s.admin) as db, db.begin():
        db.get(Membership, (s.user_id, s.workspace_id)).permissions = ["inventory.read"]
    assert c.post(url + "/inspect", files=file(raw)).status_code == 403
    with Session(s.admin) as db, db.begin():
        member = db.get(Membership, (s.user_id, s.workspace_id))
        member.permissions, member.store_ids = ["inventory.read", "reports.export"], [str(uuid4())]
    assert c.post(url + "/inspect", files=file(raw)).status_code == 404


def test_malformed_and_oversized_files_are_explained_without_unbounded_uploads(setup, owner_client):
    s, c = setup, owner_client[0]
    _, url = prepared(s, c)
    assert c.post(url + "/inspect", files=file(b"not-a-zip")).status_code == 422
    assert c.post(url + "/inspect", files=file(b"x" * (257 * 1024))).status_code == 422
    assert c.post(url + "/inspect", files=file(b"x" * (321 * 1024))).status_code == 413
    unrelated = plan_url(s)
    assert (
        c.post(
            unrelated, content=b"x" * 70000, headers={"content-type": "application/octet-stream"}
        ).status_code
        == 413
    )
