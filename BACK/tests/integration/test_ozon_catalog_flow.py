from datetime import timedelta
from unittest.mock import Mock
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_insights_flow import env as env
from test_insights_flow import pytestmark as pytestmark
from test_ozon_catalog import payload
from test_ozon_connection import connect
from test_ozon_connection import ozon as ozon

from app.db.session import set_actor
from app.integrations.ozon.catalog_client import ImportError
from app.modules.accounts.models import StoreCredential
from app.modules.auth.dependencies import now
from app.modules.auth.models import Membership
from app.modules.catalog.marketplace_models import MarketplaceCatalogSnapshot, OzonCatalogSync
from app.modules.catalog.ozon_jobs import execute


def queued(e, sid):
    run = uuid4()
    with Session(e.admin) as db, db.begin():
        job = db.get(OzonCatalogSync, (e.workspace, sid))
        job.status, job.run_id = "queued", run
        job.next_attempt_at = now() + timedelta(minutes=10)
    return run


def publish(e, sid, rows=None, during=None):
    rows = rows if rows is not None else [payload(1, 5), payload(2, 5), payload(3, 9)]
    run = queued(e, sid)

    def fetch(_normalize, progress):
        if during:
            during()
        progress(len(rows))
        return rows

    execute(e.engine, e.vault, e.workspace, sid, e.owner, run, lambda cid, key: Mock(fetch=fetch))


def test_catalog_stock_and_native_grouping_share_neutral_identities(ozon):
    e = ozon
    sid = connect(e)
    publish(e, sid)
    base = f"/api/v1/workspaces/{e.workspace}"
    response = e.client.get(base + f"/product-models?store_id={sid}", headers=e.headers)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["total"] == 2 and data["total_products"] == 3
    assert sorted(len(model["products"]) for model in data["items"]) == [1, 2]
    first = data["items"][0]["products"][0]
    assert first["nm_id"] == "" and first["variants"][0]["chrt_id"] == ""
    assert first["id"] and first["variants"][0]["id"]
    assert first["marketplace_code"] != first["external_id"]
    assert first["photos"] and first["colors"] == ["чёрный"]
    assert not data["is_loading"] and not data["is_partial"]
    inventory = e.client.get(
        base + f"/inventory/overview?store_id={sid}&limit=30", headers=e.headers
    )
    assert inventory.status_code == 200, inventory.text
    stock = inventory.json()
    assert stock["fbo"]["units"] == 24 and stock["fbs"]["units"] == 6
    assert stock["fbo"]["retail_value"] == "2962.80"
    assert stock["fbs"]["retail_value"] == "740.70"
    assert stock["total"]["units"] == 30
    assert stock["total"]["cost_value"] is None
    assert stock["turnover_days"] is None and stock["turnover_supported"]
    assert stock["turnover_basis"] == "ozon_sales_28d_fbo"
    assert all(item["turnover_status"] == "loading" for item in stock["items"])
    assert stock["other_channels"] == ["rfbs"]
    assert stock["items"][0]["fbs_sizes"][0]["variant_id"]
    mixed = e.client.get(base + "/inventory/overview?limit=30", headers=e.headers).json()
    assert mixed["aggregation_status"] == "warehouse_mapping_required"
    assert mixed["fbs"]["units"] is None and mixed["total"]["units"] is None
    all_cards = e.client.get(base + "/product-models", headers=e.headers).json()
    assert {item["marketplace"] for item in all_cards["items"]} == {"ozon", "wildberries"}
    for path in ("/business?topic=finance",):
        # Unsupported mixed reports must never silently show a WB-only total.
        response = e.client.get(
            base + path,
            params={"date_from": "2026-10-01", "date_to": "2026-10-28"},
            headers=e.headers,
        )
        assert response.status_code == 409, response.text


def test_search_pagination_and_permissions(ozon):
    e = ozon
    sid = connect(e)
    publish(e, sid)
    base = f"/api/v1/workspaces/{e.workspace}"
    found = e.client.get(base + f"/products?store_id={sid}&q=102", headers=e.headers).json()
    assert found["total"] == 1 and found["items"][0]["external_id"] == "2"
    page = e.client.get(
        base + f"/products?store_id={sid}&limit=1&offset=1", headers=e.headers
    ).json()
    assert len(page["items"]) == 1 and page["total"] == 3
    with Session(e.admin) as db, db.begin():
        member = db.get(Membership, (e.viewer, e.workspace))
        member.store_ids = [str(e.store)]
    headers = e.login(e.viewer)
    assert e.client.get(base + f"/products?store_id={sid}", headers=headers).status_code == 404
    with Session(e.engine) as db, db.begin():
        set_actor(db, e.viewer)
        assert db.get(MarketplaceCatalogSnapshot, (e.workspace, sid)) is None
    assert e.client.post(base + f"/stores/{sid}/catalog-refresh", headers=headers).status_code in {
        403,
        404,
    }


def test_failed_import_does_not_erase_previous_published_snapshot(ozon):
    e = ozon
    sid = connect(e)
    publish(e, sid)
    with Session(e.admin) as db:
        old = db.get(MarketplaceCatalogSnapshot, (e.workspace, sid)).ciphertext
    run = queued(e, sid)
    with pytest.raises(ImportError):
        execute(
            e.engine,
            e.vault,
            e.workspace,
            sid,
            e.owner,
            run,
            lambda cid, key: Mock(fetch=Mock(side_effect=ImportError("ozon_rate_limited", 60))),
        )
    with Session(e.admin) as db:
        assert db.get(MarketplaceCatalogSnapshot, (e.workspace, sid)).ciphertext == old


def test_key_replacement_during_import_prevents_old_key_publication(ozon):
    e = ozon
    sid = connect(e)

    def replace_key():
        with Session(e.admin) as db, db.begin():
            row = db.scalar(select(StoreCredential).where(StoreCredential.store_id == sid))
            row.ciphertext = "synthetic-replaced-key"

    with pytest.raises(ImportError) as error:
        publish(e, sid, during=replace_key)
    assert error.value.code == "credential_changed"
    with Session(e.admin) as db:
        assert db.get(MarketplaceCatalogSnapshot, (e.workspace, sid)) is None


def test_revoked_actor_and_duplicate_delivery_do_not_call_seller(ozon):
    e = ozon
    sid = connect(e)
    run = queued(e, sid)
    client = Mock()
    execute(e.engine, e.vault, e.workspace, sid, e.owner, uuid4(), client)
    assert not client.called
    with Session(e.admin) as db, db.begin():
        db.get(Membership, (e.owner, e.workspace)).role = "viewer"
    execute(e.engine, e.vault, e.workspace, sid, e.owner, run, client)
    assert not client.called
    with Session(e.admin) as db:
        assert db.get(OzonCatalogSync, (e.workspace, sid)).error_code == "access_revoked"
        assert db.get(MarketplaceCatalogSnapshot, (e.workspace, sid)) is None
