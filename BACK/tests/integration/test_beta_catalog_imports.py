import json
from uuid import uuid4

from sqlalchemy.orm import Session
from test_catalog import card, seed
from test_ozon_catalog import payload
from test_wb_sync_database import owner_client as owner_client
from test_wb_sync_database import pytestmark as pytestmark
from test_wb_sync_database import setup as setup

from app.integrations.wildberries.data import Source
from app.modules.accounts.models import Store
from app.modules.auth.dependencies import now
from app.modules.catalog.import_service import MATCH_HEADERS, PACKAGING_HEADERS
from app.modules.catalog.marketplace_models import MarketplaceCatalogSnapshot
from app.modules.catalog.ozon_jobs import aad
from app.modules.finance.xlsx import HEADERS, build_template, read_rows


def base(s):
    return f"/api/v1/workspaces/{s.workspace_id}"


def seed_pair(s):
    seed(s, Source.CATALOG, [("42", card(barcodes=["001", "alias"]))])
    sid = uuid4()
    rows = [payload(1, 5), payload(2, 5)]
    rows[0]["barcodes"] = ["001"]
    rows[1]["barcodes"] = ["002"]
    with Session(s.admin) as db, db.begin():
        db.add(
            Store(
                id=sid,
                workspace_id=s.workspace_id,
                name="Other marketplace",
                marketplace="ozon",
                external_seller_id=str(sid),
                connection_status="connected",
            )
        )
        db.flush()
        db.add(
            MarketplaceCatalogSnapshot(
                workspace_id=s.workspace_id,
                store_id=sid,
                ciphertext=s.vault.seal(json.dumps(rows), aad(s.workspace_id, sid)),
                updated_at=now(),
            )
        )
    return sid


def test_size_cost_is_read_after_saving_one_of_its_barcodes(setup, owner_client):
    s = setup
    owner_client, _ = owner_client
    seed(s, Source.CATALOG, [("42", card(barcodes=["001", "alias"]))])
    path = base(s) + f"/stores/{s.store_id}"
    response = owner_client.post(
        path + "/costs",
        json={
            "nm_id": "42",
            "barcode": "001",
            "amount": "123.45",
            "currency": "RUB",
            "effective_from": "2025-01-01",
        },
    )
    assert response.status_code == 200, response.text
    products = owner_client.get(base(s) + "/products").json()["items"]
    sizes = {v["size"]: v["unit_cost"] for v in products[0]["variants"]}
    assert sizes == {"M": "123.45", "L": None}
    prices = owner_client.get(path + "/costs", params={"nm_id": "42"}).json()
    assert {row["barcode"] for row in prices} == {"001", "alias"}


def test_seller_article_cost_template_and_preview_resolve_inside_store(setup, owner_client):
    s = setup
    owner_client, _ = owner_client
    seed(s, Source.CATALOG, [("42", card(vendor="000-TWL"))])
    path = base(s) + f"/stores/{s.store_id}/cost-imports"
    template = owner_client.get(path.replace("/cost-imports", "/costs/template"))
    assert template.status_code == 200
    assert read_rows(template.content) == []
    file = build_template(HEADERS, [["000-TWL", "001", "75", "01.10.2026", "RUB"]])
    response = owner_client.post(path, files={"file": ("costs.xlsx", file)})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["can_apply"] and result["items"][0]["nm_id"] == "42"


def test_packaging_preview_apply_is_scoped_validated_and_idempotent(setup, owner_client):
    s = setup
    owner_client, _ = owner_client
    seed(s, Source.CATALOG, [("42", card(vendor="BOX"))])
    root = base(s) + f"/stores/{s.store_id}/inventory/packaging"
    file = build_template(PACKAGING_HEADERS, [["BOX", "", "6"]], sheet_name="Вложимость")
    response = owner_client.post(root + "/import/preview", files={"file": ("box.xlsx", file)})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["can_apply"] and result["items"][0]["box_multiple"] == 6
    for _ in range(2):
        applied = owner_client.post(root + f"/import/{result['preview_id']}/apply")
        assert applied.status_code == 200, applied.text
        assert applied.json()["applied"] == 1
    bad = build_template(PACKAGING_HEADERS, [["BOX", "", "0"]], sheet_name="Вложимость")
    response = owner_client.post(root + "/import/preview", files={"file": ("box.xlsx", bad)}).json()
    assert not response["can_apply"] and response["errors"]


def test_barcode_matches_preview_apply_list_and_delete(setup, owner_client):
    s = setup
    owner_client, _ = owner_client
    sid = seed_pair(s)
    root = base(s) + "/catalog/matches"
    pair = {"left_store_id": str(s.store_id), "right_store_id": str(sid)}
    preview = owner_client.post(root + "/automatic", json=pair)
    assert preview.status_code == 200, preview.text
    result = preview.json()
    assert result["can_apply"] and result["valid_count"] == 2
    wrong = owner_client.post(
        root + f"/{result['preview_id']}/apply", json={**pair, "right_store_id": str(uuid4())}
    )
    assert wrong.status_code == 404
    for _ in range(2):
        response = owner_client.post(root + f"/{result['preview_id']}/apply", json=pair)
        assert response.status_code == 200, response.text
    saved = owner_client.get(root, params=pair).json()
    assert saved["count"] == 2
    assert all(row["source"] == "barcode" for row in saved["items"])
    response = owner_client.delete(root + "/" + saved["items"][0]["id"])
    assert response.status_code == 200, response.text
    assert owner_client.get(root, params=pair).json()["count"] == 1


def test_manual_matches_require_size_when_article_has_multiple_variants(setup, owner_client):
    s = setup
    owner_client, _ = owner_client
    sid = seed_pair(s)
    path = base(s) + "/catalog/matches/preview"
    file = build_template(
        MATCH_HEADERS, [["GLOVE", "", "Article-1", "001"]], sheet_name="Соответствия"
    )
    response = owner_client.post(
        path,
        params={"left_store_id": str(s.store_id), "right_store_id": str(sid)},
        files={"file": ("pairs.xlsx", file)},
    )
    assert response.status_code == 200, response.text
    assert not response.json()["can_apply"]


def test_user_can_split_and_restore_marketplace_groups_on_ozon(setup, owner_client):
    s = setup
    owner_client, _ = owner_client
    sid = seed_pair(s)
    path = base(s) + f"/stores/{sid}/product-grouping"
    response = owner_client.post(
        path, json={"action": "split", "articles": ["1", "2"], "title": ""}
    )
    assert response.status_code == 200, response.text
    query = base(s) + f"/product-models?store_id={sid}"
    assert owner_client.get(query).json()["total"] == 2
    response = owner_client.post(
        path, json={"action": "merge", "articles": ["1", "2"], "title": "My model"}
    )
    assert response.status_code == 200, response.text
    models = owner_client.get(query).json()["items"]
    assert len(models) == 1 and models[0]["title"] == "My model"
    response = owner_client.post(
        path, json={"action": "reset", "articles": ["1", "2"], "title": ""}
    )
    assert response.status_code == 200, response.text
    assert owner_client.get(query).json()["items"][0]["grouping"] == "marketplace"


def test_custom_expense_title_survives_read_and_idempotent_create(setup, owner_client):
    s = setup
    owner_client, _ = owner_client
    path = base(s) + f"/stores/{s.store_id}/expenses"
    data = {
        "expense_date": "2026-10-01",
        "amount": "100",
        "currency": "RUB",
        "category": "other",
        "custom_category": "Фотосъёмка",
        "comment": "Студия",
        "request_id": str(uuid4()),
    }
    response = owner_client.post(path, json=data)
    assert response.status_code == 201, response.text
    assert response.json()["custom_category"] == "Фотосъёмка"
    second = owner_client.post(path, json=data)
    assert second.status_code in (200, 201) and second.json()["id"] == response.json()["id"]
    changed = owner_client.post(path, json={**data, "custom_category": "Другая статья"})
    assert changed.status_code == 409


def test_new_exports_do_not_require_marketplace_network(setup, owner_client):
    s = setup
    owner_client, _ = owner_client
    path = base(s) + "/insights/funnel/export"
    for format in ["csv", "xlsx"]:
        response = owner_client.get(
            path,
            params={
                "store_id": str(s.store_id),
                "date_from": "2026-10-01",
                "date_to": "2026-10-02",
                "format": format,
            },
        )
        assert response.status_code == 200, response.text
        assert "no-store" in response.headers["cache-control"]
        if format == "xlsx":
            assert response.content.startswith(b"PK")


def test_conditional_funnel_read_returns_304_without_reenriching_a_response(setup, owner_client):
    s = setup
    client, _ = owner_client
    response = client.get(
        base(s) + f"/stores/{s.store_id}/insights/funnel",
        params={"date_from": "2026-11-01", "date_to": "2026-11-02"},
    )
    assert response.status_code == 200, response.text
    cached = client.get(
        base(s) + f"/stores/{s.store_id}/insights/funnel",
        params={"date_from": "2026-11-01", "date_to": "2026-11-02"},
        headers={"If-None-Match": response.headers["etag"]},
    )
    assert cached.status_code == 304 and cached.content == b""


def test_long_funnel_read_extends_history_without_changing_the_owner_actor(setup, owner_client):
    from datetime import timedelta

    from sqlalchemy import select

    from app.modules.sync.models import SyncSchedule
    from app.modules.sync.schemas import moscow_today

    s = setup
    client, _ = owner_client
    old = moscow_today() - timedelta(days=28)
    start = old - timedelta(days=40)
    with Session(s.admin) as db, db.begin():
        db.add(
            SyncSchedule(
                workspace_id=s.workspace_id,
                store_id=s.store_id,
                source=Source.FUNNEL,
                requested_by=s.user_id,
                enabled=True,
                recent_completed=True,
                history_from=old,
                next_attempt_at=now(),
                next_refresh_at=now(),
                reconcile_at=now(),
            )
        )
    from sqlalchemy import text

    from app.db.session import set_actor

    with Session(s.engine) as db, db.begin():
        set_actor(db, s.other_id)
        denied = db.scalar(
            text("SELECT perk_request_funnel_history(:wid,:sid,:start)"),
            {"wid": s.workspace_id, "sid": s.store_id, "start": start - timedelta(days=20)},
        )
        assert denied is False
    response = client.get(
        base(s) + f"/stores/{s.store_id}/insights/funnel",
        params={"date_from": str(start), "date_to": str(old)},
    )
    assert response.status_code == 200, response.text
    with Session(s.admin) as db:
        plan = db.scalar(
            select(SyncSchedule).where(
                SyncSchedule.workspace_id == s.workspace_id,
                SyncSchedule.store_id == s.store_id,
                SyncSchedule.source == Source.FUNNEL,
            )
        )
        assert plan.history_from == start and plan.backfill_to == old - timedelta(days=1)
        assert plan.requested_by == s.user_id
