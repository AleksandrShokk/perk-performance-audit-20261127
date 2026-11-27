import json
from unittest.mock import Mock
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session
from supply_plan_helpers import select_recommendations
from test_mobile_supplies_flow import prepare, root
from test_supply_destinations import END, START, office
from test_wb_sync_database import owner_client as owner_client
from test_wb_sync_database import pytestmark as pytestmark
from test_wb_sync_database import setup as setup

from app.db.session import set_actor
from app.integrations.wildberries.data import Source
from app.modules.auth.dependencies import now
from app.modules.auth.models import Membership
from app.modules.supplies.destinations.jobs import aad, execute
from app.modules.supplies.destinations.models import (
    SupplyDestinationSnapshot,
    SupplyDestinationSync,
)
from app.modules.supplies.destinations.normalize import wb_regions
from app.modules.sync.models import SyncSchedule


def seed_regions(s, key="42", values=None):
    values = values or wb_regions(
        {"offices": [office(stock=10, orders=140), office(2, "Сибирь", 100, 28)]},
        START,
        END,
    )
    with Session(s.admin) as db, db.begin():
        db.add(
            SupplyDestinationSnapshot(
                workspace_id=s.workspace_id,
                store_id=s.store_id,
                product_key=key,
                ciphertext=s.vault.seal(json.dumps(values), aad(s.workspace_id, s.store_id, key)),
                updated_at=now(),
            )
        )
    return values


def test_regional_need_is_calculated_independently_and_can_be_saved_as_a_native_plan(
    setup, owner_client
):
    s, c = setup, owner_client[0]
    prepare(s)
    seed_regions(s)
    path = root(s) + "/replenishment"
    summary = c.get(path + "/destinations").json()
    assert summary["loaded_products"] == 1 and summary["total_products"] == 2
    region = next(r for r in summary["items"] if r["name"] == "Центр")
    assert region["recommended_units"] == 125
    data = c.get(path, params={"store_id": str(s.store_id), "destination_id": region["id"]}).json()
    assert data["recommended_units"] == 125 and data["items"][0]["stock"] == 10
    assert data["items"][0]["destination_name"] == "Центр"
    created = c.post(
        f"/api/v1/workspaces/{s.workspace_id}/stores/{s.store_id}/inventory/plans",
        json={
            "title": "Центральный регион",
            "destination_id": region["id"],
            "destination": "ignored client text",
        },
    )
    assert created.status_code == 201, created.text
    plan = created.json()
    plan = select_recommendations(c, root(s) + "/plans/" + plan["id"], plan)
    assert (
        plan["destination"] == "Центр"
        and plan["destination_id"] == region["id"]
        and plan["quantity"] == 125
    )
    from test_supply_plans_flow import body

    changed = c.put(root(s) + "/plans/" + plan["id"], json=body(plan, destination="Сибирь"))
    assert changed.status_code == 409
    exported = c.get(
        path + "/export",
        params={"store_id": str(s.store_id), "destination_id": region["id"]},
    )
    assert exported.status_code == 200 and "Центр" in exported.content.decode("utf-8-sig")
    assert (
        c.get(path, params={"store_id": str(s.store_id), "destination_id": "not-real"}).status_code
        == 404
    )


def test_wb_refresh_is_idempotent_and_does_not_run_network_requests_in_api(setup, owner_client):
    s, c = setup, owner_client[0]
    prepare(s)
    with Session(s.admin) as db, db.begin():
        db.add(
            SyncSchedule(
                workspace_id=s.workspace_id,
                store_id=s.store_id,
                source=Source.SUPPLY_DEMAND,
                requested_by=s.user_id,
                enabled=True,
                next_refresh_at=now(),
                next_attempt_at=now(),
                reconcile_at=now(),
            )
        )
    path = root(s) + "/replenishment/destinations/refresh"
    first = c.post(path, params={"store_id": str(s.store_id)})
    assert first.status_code == 200, first.text
    assert first.json()["queued"] == 2
    assert c.post(path, params={"store_id": str(s.store_id)}).json()["queued"] == 0
    with Session(s.admin) as db:
        jobs = db.scalars(select(SupplyDestinationSync)).all()
        assert len(jobs) == 2 and all(job.status == "pending" for job in jobs)


def test_background_job_publishes_after_native_read_and_keeps_previous_data_on_error(
    setup,
):
    s = setup
    run = uuid4()
    with Session(s.admin) as db, db.begin():
        db.add(
            SupplyDestinationSync(
                workspace_id=s.workspace_id,
                store_id=s.store_id,
                product_key="42",
                requested_by=s.user_id,
                status="queued",
                run_id=run,
                date_from=START,
                date_to=END,
                next_attempt_at=now(),
            )
        )
    reader = Mock(cooldown_seconds=0, request=Mock(return_value={"data": {"offices": [office()]}}))
    execute(
        s.engine,
        s.redis,
        s.vault,
        s.settings,
        s.workspace_id,
        s.store_id,
        "42",
        s.user_id,
        run,
        reader,
    )
    assert reader.request.call_count == 1
    assert reader.request.call_args.kwargs["body"]["stockType"] == "wb"
    with Session(s.admin) as db:
        row = db.get(SupplyDestinationSnapshot, (s.workspace_id, s.store_id, "42"))
        assert row and "Центр" not in row.ciphertext
        assert (
            json.loads(s.vault.open(row.ciphertext, aad(s.workspace_id, s.store_id, "42")))[0][
                "stock"
            ]
            == 10
        )


def test_destination_snapshots_are_hidden_from_other_cabinets_and_staff_without_inventory_access(
    setup, owner_client
):
    s, c = setup, owner_client[0]
    prepare(s)
    seed_regions(s)
    with Session(s.admin) as db, db.begin():
        member = db.get(Membership, (s.user_id, s.workspace_id))
        member.role, member.permissions = "manager", ["finance.read"]
    assert c.get(root(s) + "/replenishment/destinations").status_code == 403
    assert c.post(root(s) + "/replenishment/destinations/refresh").status_code == 403
    with Session(s.engine) as db, db.begin():
        set_actor(db, s.user_id)
        assert not db.scalars(select(SupplyDestinationSnapshot)).all()


def test_global_reads_take_priority_over_regional_background_requests(setup):
    from app.modules.sync.models import SyncRun

    s = setup
    run = uuid4()
    with Session(s.admin) as db, db.begin():
        db.add(
            SupplyDestinationSync(
                workspace_id=s.workspace_id,
                store_id=s.store_id,
                product_key="42",
                requested_by=s.user_id,
                status="queued",
                run_id=run,
                date_from=START,
                date_to=END,
                next_attempt_at=now(),
            )
        )
        db.add(
            SyncRun(
                workspace_id=s.workspace_id,
                store_id=s.store_id,
                source=Source.SUPPLY_DEMAND,
                requested_by=s.user_id,
                status="queued",
                date_from=START,
                date_to=END,
            )
        )
    reader = Mock()
    execute(
        s.engine,
        s.redis,
        s.vault,
        s.settings,
        s.workspace_id,
        s.store_id,
        "42",
        s.user_id,
        run,
        reader,
    )
    reader.request.assert_not_called()
    with Session(s.admin) as db:
        assert db.get(SupplyDestinationSync, (s.workspace_id, s.store_id, "42")).status == "pending"


def test_failed_regional_refresh_preserves_the_published_snapshot(setup):
    import pytest

    from app.integrations.wildberries.data import WBError

    s = setup
    seed_regions(s)
    run = uuid4()
    with Session(s.admin) as db, db.begin():
        db.add(
            SupplyDestinationSync(
                workspace_id=s.workspace_id,
                store_id=s.store_id,
                product_key="42",
                requested_by=s.user_id,
                status="queued",
                run_id=run,
                date_from=START,
                date_to=END,
                next_attempt_at=now(),
            )
        )
        previous = db.get(SupplyDestinationSnapshot, (s.workspace_id, s.store_id, "42")).ciphertext
    reader = Mock(request=Mock(side_effect=WBError("wb_rate_limited", retry_after=60)))
    with pytest.raises(WBError):
        execute(
            s.engine,
            s.redis,
            s.vault,
            s.settings,
            s.workspace_id,
            s.store_id,
            "42",
            s.user_id,
            run,
            reader,
        )
    with Session(s.admin) as db:
        assert (
            db.get(SupplyDestinationSnapshot, (s.workspace_id, s.store_id, "42")).ciphertext
            == previous
        )
    assert s.redis.eval.call_args.args[-1] == 60
