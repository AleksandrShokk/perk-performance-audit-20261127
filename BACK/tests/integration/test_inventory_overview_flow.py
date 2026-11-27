import json

from sqlalchemy.orm import Session
from test_catalog import card, save, seed, stock
from test_wb_sync_database import owner_client as owner_client
from test_wb_sync_database import pytestmark as pytestmark
from test_wb_sync_database import setup as setup

from app.integrations.wildberries.data import Source
from app.modules.auth.models import Membership
from app.modules.inventory.channel_history import channel_aad
from app.modules.inventory.models import InventorySnapshot
from app.modules.sync.models import SyncRun
from app.modules.sync.schemas import moscow_today


def path(s):
    return f"/api/v1/workspaces/{s.workspace_id}/inventory/overview"


def prepare(s):
    seed(s, Source.CATALOG, [("42", card())])
    seed(
        s,
        Source.STOCKS,
        [("42:10:1", stock(quantity=3)), ("42:11:1", stock(chrt="11", quantity=2))],
    )
    seed(s, Source.FBS, [("42:10:2", stock(warehouse="Свой склад", quantity=4))])
    seed(
        s,
        Source.PRICES,
        [("42", {"nm_id": "42", "currency": "RUB", "prices": {"10": "100", "11": "200"}})],
    )


def test_inventory_summary_and_positions_use_all_sizes_and_mark_partial_cost(setup, owner_client):
    s, c = setup, owner_client[0]
    prepare(s)
    result = save(
        c, f"/api/v1/workspaces/{s.workspace_id}/stores/{s.store_id}", barcode="001", amount="10"
    )
    assert result.status_code == 200, result.text
    result = c.get(path(s), params={"coverage_channel": "all", "store_id": str(s.store_id)})
    assert result.status_code == 200, result.text
    data = result.json()
    assert data["items"] == [] and data["count"] == 1
    assert data["fbo"]["units"] == 5 and data["fbs"]["units"] == 4
    assert data["total"]["retail_value"] == "1100.00" and data["total"]["retail_complete"]
    assert data["total"]["cost_value"] == "70.00" and not data["total"]["cost_complete"]
    assert data["turnover_days"] is None
    page = c.get(
        path(s),
        params={"coverage_channel": "all", "store_id": str(s.store_id), "limit": 1, "q": "002"},
    ).json()
    assert page["items"][0]["product"]["nm_id"] == "42"
    assert page["items"][0]["fbs_sizes"][0]["quantity"] == 4
    assert (
        c.get(
            path(s),
            params={
                "coverage_channel": "all",
                "store_id": str(s.store_id),
                "limit": 1,
                "offset": 1,
            },
        ).json()["items"]
        == []
    )


def test_inventory_missing_fbs_never_invents_zero_and_employee_cannot_read_cost(
    setup, owner_client
):
    s, c = setup, owner_client[0]
    seed(s, Source.CATALOG, [("42", card())])
    seed(s, Source.STOCKS, [("42:10:1", stock(quantity=3))])
    with Session(s.admin) as db, db.begin():
        member = db.get(Membership, (s.user_id, s.workspace_id))
        member.role = "manager"
        member.permissions = ["inventory.read"]
    result = c.get(
        path(s), params={"coverage_channel": "all", "store_id": str(s.store_id), "limit": 1}
    )
    assert result.status_code == 200, result.text
    data = result.json()
    assert data["fbs"]["units"] is None and data["total"]["units"] is None
    assert not data["can_cost"] and data["total"]["cost_value"] is None
    assert all(row["unit_cost"] is None for row in data["items"][0]["product"]["variants"])
    assert set(data["missing_sources"]) >= {"fbs", "prices"}
    with Session(s.admin) as db, db.begin():
        db.get(Membership, (s.user_id, s.workspace_id)).permissions = []
    assert c.get(path(s)).status_code == 403


def test_inventory_channel_history_is_independent_and_preserves_fbo_projection(setup, owner_client):
    from sqlalchemy import select

    from app.db.session import set_actor
    from app.modules.inventory.channel_history import record_stock
    from app.modules.inventory.service import snapshots

    s = setup
    prepare(s)
    with Session(s.engine) as db, db.begin():
        set_actor(db, s.user_id)
        for source in (Source.STOCKS, Source.FBS):
            run = db.scalar(
                select(SyncRun).where(SyncRun.store_id == s.store_id, SyncRun.source == source)
            )
            record_stock(db, s.vault, run)
        day = moscow_today()
        fbo = list(snapshots(db, s.vault, s.workspace_id, s.store_id, day, day))
        assert len(fbo) == 1 and fbo[0][2]["stock"] == 5
        fbs = db.scalar(
            select(InventorySnapshot).where(
                InventorySnapshot.store_id == s.store_id, InventorySnapshot.channel == "fbs"
            )
        )
        assert (
            json.loads(
                s.vault.open(
                    fbs.ciphertext, channel_aad(s.workspace_id, s.store_id, day, "42", "fbs")
                )
            )["stock"]
            == 4
        )


def test_inventory_cover_is_available_from_wb_without_a_single_local_snapshot(setup, owner_client):
    from datetime import date

    from sqlalchemy import func, select
    from test_stock_cover import report

    s, c = setup, owner_client[0]
    prepare(s)
    row = report()
    seed(s, Source.STOCK_HISTORY, [("42", row)])
    with Session(s.admin) as db, db.begin():
        run = db.scalar(
            select(SyncRun).where(
                SyncRun.store_id == s.store_id, SyncRun.source == Source.STOCK_HISTORY
            )
        )
        run.date_from, run.date_to = (
            date.fromisoformat(row["date_from"]),
            date.fromisoformat(row["date_to"]),
        )
        assert db.scalar(select(func.count()).select_from(InventorySnapshot)) == 0
    result = c.get(
        path(s), params={"coverage_channel": "all", "store_id": str(s.store_id), "limit": 1}
    ).json()
    assert result["turnover_days"] == "20.00" and result["observed_days"] == 28
    assert result["items"][0]["turnover_days"] == "20.00"
    assert result["turnover_updated_at"] and not result["turnover_loading"]


def test_inventory_retains_old_price_snapshot_but_marks_value_stale(setup, owner_client):
    from datetime import timedelta

    from sqlalchemy import select

    from app.modules.auth.dependencies import now

    s, c = setup, owner_client[0]
    prepare(s)
    with Session(s.admin) as db, db.begin():
        run = db.scalar(
            select(SyncRun).where(SyncRun.store_id == s.store_id, SyncRun.source == Source.PRICES)
        )
        run.finished_at = now() - timedelta(days=3)
    result = c.get(path(s), params={"coverage_channel": "all", "store_id": str(s.store_id)}).json()
    assert result["total"]["retail_value"] == "1100.00" and result["total"]["stale"]


def test_inventory_pages_match_the_full_list_and_cached_answers(setup, owner_client):
    s, c = setup, owner_client[0]
    seed(s, Source.CATALOG, [(str(n), card(article=str(n), vendor=f"V{n % 7}")) for n in range(30)])
    seed(
        s,
        Source.STOCKS,
        [(f"{n}:10:1", stock(article=str(n), quantity=n % 4)) for n in range(30)],
    )
    params = {"coverage_channel": "fbo", "store_id": str(s.store_id)}
    full = c.get(path(s), params={**params, "limit": 100}).json()
    assert full["count"] == 30 and len(full["items"]) == 30
    pages = [
        c.get(path(s), params={**params, "limit": 7, "offset": offset}).json()
        for offset in range(0, 30, 7)
    ]
    assert [item for page in pages for item in page["items"]] == full["items"]
    assert all(page["fbo"] == full["fbo"] and page["count"] == 30 for page in pages)
    # A repeated read (served from the cache) is identical; new stock replaces it.
    assert c.get(path(s), params={**params, "limit": 100}).json() == full
    # A new publication (new successful run) adds stock in another warehouse.
    seed(s, Source.STOCKS, [("0:10:2", stock(article="0", warehouse="Казань", quantity=50))])
    changed = c.get(path(s), params={**params, "limit": 100}).json()
    assert changed["fbo"]["units"] != full["fbo"]["units"]
