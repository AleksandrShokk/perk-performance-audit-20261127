import json
from datetime import date
from uuid import uuid4

from sqlalchemy.orm import Session
from test_wb_sync_database import owner_client as owner_client
from test_wb_sync_database import pytestmark as pytestmark
from test_wb_sync_database import setup as setup

from app.integrations.wildberries.data import Source
from app.modules.accounts.models import Store
from app.modules.auth.dependencies import now
from app.modules.auth.models import Membership
from app.modules.sync.models import SyncRun, WBRecord
from app.modules.sync.service import context


def card(article="42", vendor="GLOVE", title="Перчатки", barcodes=None):
    return dict(
        nm_id=article,
        vendor_code=vendor,
        title=title,
        brand="PERK",
        subject="Перчатки",
        colors=["чёрный"],
        sizes=[
            dict(chrt_id="10", size="M", barcodes=barcodes or ["001"]),
            dict(chrt_id="11", size="L", barcodes=["002"]),
        ],
    )


def seed(s, source, rows, store_id=None):
    store_id = store_id or s.store_id
    with Session(s.admin) as db, db.begin():
        for key, row in rows:
            db.add(
                WBRecord(
                    workspace_id=s.workspace_id,
                    store_id=store_id,
                    source=source,
                    record_key=key,
                    ciphertext=s.vault.seal(
                        json.dumps(row), context(s.workspace_id, store_id, source, key)
                    ),
                    updated_at=now(),
                )
            )
        db.add(
            SyncRun(
                workspace_id=s.workspace_id,
                store_id=store_id,
                requested_by=s.user_id,
                source=source,
                task_id=str(uuid4()),
                date_from=date(2026, 1, 1),
                date_to=date(2026, 1, 1),
                status="succeeded",
                finished_at=now(),
            )
        )


def stock(article="42", chrt="10", warehouse="Коледино", quantity=3):
    return dict(
        nm_id=article,
        chrt_id=chrt,
        warehouse_id=warehouse,
        warehouse_name=warehouse,
        quantity=quantity,
        in_way_to_client=1,
        in_way_from_client=2,
    )


def root(s):
    return f"/api/v1/workspaces/{s.workspace_id}/products"


def save(client, path, **changes):
    payload = dict(
        nm_id="42", amount="120.50", barcode="", currency="RUB", effective_from="2025-01-01"
    )
    return client.post(path + "/costs", json=payload | changes)


def test_catalog_search_variants_and_stock_are_not_multiplied_by_barcode_aliases(
    setup, owner_client
):
    s = setup
    seed(s, Source.CATALOG, [("42", card(barcodes=["001", "alias"]))])
    seed(
        s,
        Source.STOCKS,
        [
            ("42:10:1", stock()),
            ("42:10:2", stock(warehouse="Казань", quantity=4)),
            ("42:11:1", stock(chrt="11", quantity=2)),
        ],
    )
    client, _ = owner_client
    result = client.get(root(s), params={"q": "PERK чёрный alias"}).json()
    assert result["total"] == 1 and result["total_variants"] == 2
    assert result["items"][0]["stock"] == result["stock_units"] == 9
    assert [row["stock"] for row in result["items"][0]["variants"]] == [7, 2]
    assert result["missing_cost_variants"] == 2
    assert client.get(root(s), params={"q": "GLoVe"}).json()["total"] == 1
    assert client.get(root(s), params={"q": "absent"}).json()["total"] == 0


def test_absent_stock_import_is_unknown_and_not_a_known_zero(setup, owner_client):
    s = setup
    seed(s, Source.CATALOG, [("42", card())])
    client, _ = owner_client
    result = client.get(root(s)).json()
    assert result["is_partial"] and result["items"][0]["stock"] is None
    assert result["items"][0]["variants"][0]["stock"] is None
    assert client.get(root(s), params={"in_stock": True}).json()["total"] == 0
    seed(s, Source.STOCKS, [])
    result = client.get(root(s)).json()
    assert not result["is_partial"] and result["items"][0]["stock"] == 0


def test_manual_cost_is_idempotent_dated_and_rejects_rewriting_history(setup, owner_client):
    s = setup
    seed(s, Source.CATALOG, [("42", card())])
    client, path = owner_client
    assert save(client, path).status_code == 200
    assert save(client, path).status_code == 200
    assert save(client, path, amount="99").status_code == 409
    assert save(client, path, amount="140", effective_from="2025-02-01").status_code == 200
    assert save(client, path, amount="1000", effective_from="2099-01-01").status_code == 200
    before = client.get(
        path + "/costs/calculate", params={"nm_id": "42", "at": "2025-01-15", "currency": "RUB"}
    ).json()
    assert before["unit_cost"] == "120.50"
    after = client.get(root(s)).json()
    assert after["items"][0]["variants"][0]["unit_cost"] == "140"
    assert after["missing_cost_variants"] == 0
    assert len(client.get(path + "/costs", params={"nm_id": "42"}).json()) == 3
    assert client.get(path + "/costs", params={"nm_id": "99"}).json() == []
    assert client.get(root(s), params={"missing_cost": True}).json()["total"] == 0


def test_size_specific_zero_cost_overrides_the_general_price(setup, owner_client):
    s = setup
    seed(s, Source.CATALOG, [("42", card())])
    client, path = owner_client
    assert save(client, path).status_code == 200
    assert save(client, path, barcode="001", amount="0").status_code == 200
    assert save(client, path, barcode="not-this-product").status_code == 409
    item = client.get(root(s)).json()["items"][0]
    assert [row["unit_cost"] for row in item["variants"]] == ["0", "120.50"]


def test_all_stores_keep_identical_articles_separate_and_pagination_counts_matches(
    setup, owner_client
):
    s = setup
    second = uuid4()
    with Session(s.admin) as db, db.begin():
        db.add(
            Store(id=second, workspace_id=s.workspace_id, name="Второй", marketplace="wildberries")
        )
    seed(s, Source.CATALOG, [("42", card())])
    seed(s, Source.CATALOG, [("42", card(vendor="OTHER"))], second)
    client, _ = owner_client
    first = client.get(root(s), params={"limit": 1}).json()
    second_page = client.get(root(s), params={"limit": 1, "offset": 1}).json()
    assert first["total"] == second_page["total"] == 2
    assert first["items"][0]["store_id"] != second_page["items"][0]["store_id"]
    assert client.get(root(s), params={"store_id": str(uuid4())}).status_code == 404


def employee(s, permissions, stores=None):
    with Session(s.admin) as db, db.begin():
        db.add(
            Membership(
                user_id=s.other_id,
                workspace_id=s.workspace_id,
                role="manager",
                permissions=permissions,
                store_ids=stores,
            )
        )
    s.user_id = s.other_id


def test_manager_cannot_read_or_filter_costs_and_is_scoped_to_granted_store(setup, owner_client):
    s = setup
    seed(s, Source.CATALOG, [("42", card())])
    client, path = owner_client
    assert save(client, path).status_code == 200
    second = uuid4()
    with Session(s.admin) as db, db.begin():
        db.add(
            Store(id=second, workspace_id=s.workspace_id, name="Closed", marketplace="wildberries")
        )
    seed(s, Source.CATALOG, [("42", card())], second)
    employee(s, ["inventory.read"], [str(s.store_id)])
    result = client.get(root(s)).json()
    assert result["total"] == 1 and result["missing_cost_variants"] is None
    assert result["items"][0]["variants"][0]["unit_cost"] is None
    assert client.get(root(s), params={"missing_cost": True}).status_code == 403
    assert client.get(root(s), params={"store_id": str(second)}).status_code == 404
    assert save(client, path).status_code == 403
    assert client.get(path + "/costs").status_code == 403


def test_accountant_can_set_prices_without_inventory_access(setup, owner_client):
    s = setup
    seed(s, Source.CATALOG, [("42", card())])
    seed(s, Source.STOCKS, [("42:10:1", stock())])
    employee(s, ["finance.read", "profit.read", "costs.write"])
    client, path = owner_client
    assert save(client, path).status_code == 200
    result = client.get(root(s))
    assert result.status_code == 200, result.text
    item = result.json()["items"][0]
    assert item["stock"] is None and item["variants"][0]["warehouses"] == []
    assert item["variants"][0]["unit_cost"] == "120.50"
    assert client.get(root(s), params={"in_stock": True}).status_code == 403
