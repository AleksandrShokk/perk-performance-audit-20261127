from datetime import timedelta
from uuid import uuid4

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_catalog import card, seed
from test_stock_cover import wb_row
from test_wb_sync_database import owner_client as owner_client
from test_wb_sync_database import pytestmark as pytestmark
from test_wb_sync_database import setup as setup

from app.db.session import set_actor
from app.integrations.wildberries.data import Page, Source, WBDataClient, WBError
from app.modules.sync.models import SyncRun, WBRecord
from app.modules.sync.schemas import moscow_today
from app.modules.sync.service import run_page


def run(s):
    end = moscow_today() - timedelta(days=1)
    with Session(s.admin) as db, db.begin():
        row = SyncRun(
            workspace_id=s.workspace_id,
            store_id=s.store_id,
            source=Source.STOCK_HISTORY,
            requested_by=s.user_id,
            date_from=end - timedelta(days=27),
            date_to=end,
            task_id=str(uuid4()),
        )
        db.add(row)
        db.flush()
        return row.id, row.task_id


def test_transport_publication_and_refresh_preserve_the_previous_success(setup, owner_client):
    from unittest.mock import Mock

    s, c = setup, owner_client[0]
    seed(s, Source.CATALOG, [("42", card())])
    run_id, task_id = run(s)
    response = WBDataClient(
        httpx.MockTransport(
            lambda request: httpx.Response(200, json={"data": {"items": [wb_row()]}})
        )
    )
    run_page(s.engine, s.redis, s.vault, s.settings, run_id, task_id, response)
    path = f"/api/v1/workspaces/{s.workspace_id}/inventory/overview"
    result = c.get(
        path, params={"coverage_channel": "all", "store_id": str(s.store_id), "limit": 1}
    ).json()
    assert result["turnover_days"] == "20.00" and result["items"][0]["turnover_days"] == "20.00"
    assert not result["turnover_loading"]
    assert not result["turnover_stale"]
    run_id, task_id = run(s)
    partial = Mock()
    partial.page.return_value = Page(
        [
            {
                **wb_row(),
                "periodStart": (moscow_today() - timedelta(days=28)).isoformat(),
                "periodEnd": (moscow_today() - timedelta(days=1)).isoformat(),
            }
        ],
        {"offset": 1},
        False,
    )
    run_page(s.engine, s.redis, s.vault, s.settings, run_id, task_id, partial)
    during = c.get(
        path, params={"coverage_channel": "all", "store_id": str(s.store_id), "limit": 1}
    ).json()
    assert during["turnover_loading"] and during["turnover_days"] == "20.00"
    with Session(s.admin) as db, db.begin():
        active = db.get(SyncRun, run_id)
        active.task_id = task_id = str(uuid4())
    failed = Mock()
    failed.page.side_effect = WBError("wb_access_denied")
    run_page(s.engine, s.redis, s.vault, s.settings, run_id, task_id, failed)
    after = c.get(
        path, params={"coverage_channel": "all", "store_id": str(s.store_id), "limit": 1}
    ).json()
    assert after["turnover_days"] == "20.00" and not after["turnover_loading"]
    assert after["turnover_updated_at"] == result["turnover_updated_at"]
    with Session(s.engine) as db:
        set_actor(db, s.other_id)
        assert (
            db.scalars(select(WBRecord).where(WBRecord.source == Source.STOCK_HISTORY)).all() == []
        )


def test_empty_success_replaces_the_old_report_instead_of_retaining_deleted_rows(
    setup, owner_client
):
    s, c = setup, owner_client[0]
    seed(s, Source.CATALOG, [("42", card())])
    for items in ([wb_row()], []):
        run_id, task_id = run(s)
        transport = WBDataClient(
            httpx.MockTransport(
                lambda request, items=items: httpx.Response(200, json={"data": {"items": items}})
            )
        )
        run_page(s.engine, s.redis, s.vault, s.settings, run_id, task_id, transport)
    result = c.get(
        f"/api/v1/workspaces/{s.workspace_id}/inventory/overview",
        params={"coverage_channel": "all", "store_id": str(s.store_id), "limit": 1},
    ).json()
    assert result["turnover_days"] is None and result["items"][0]["turnover_days"] is None
    assert "stock_history" not in result["missing_sources"]


def test_raw_history_requires_inventory_permission(setup, owner_client):
    from app.modules.auth.models import Membership

    s, c = setup, owner_client[0]
    path = f"/api/v1/workspaces/{s.workspace_id}/stores/{s.store_id}/data/stock_history"
    assert c.get(path).status_code == 200
    with Session(s.admin) as db, db.begin():
        member = db.get(Membership, (s.user_id, s.workspace_id))
        member.role, member.permissions = "manager", ["analytics.read"]
    assert c.get(path).status_code == 403


def test_wb_duration_anomaly_does_not_block_good_products_and_marks_partial_total(
    setup, owner_client
):
    s, c = setup, owner_client[0]
    seed(s, Source.CATALOG, [("42", card()), ("43", card(article="43"))])
    bad = {**wb_row(officeMissingTime={"days": 0, "hours": -4}), "nmID": 43}
    run_id, task_id = run(s)
    transport = WBDataClient(
        httpx.MockTransport(
            lambda request: httpx.Response(200, json={"data": {"items": [wb_row(), bad]}})
        )
    )
    run_page(s.engine, s.redis, s.vault, s.settings, run_id, task_id, transport)
    result = c.get(
        f"/api/v1/workspaces/{s.workspace_id}/inventory/overview",
        params={"coverage_channel": "all", "store_id": str(s.store_id), "limit": 2},
    ).json()
    assert result["turnover_days"] == "20.00" and result["turnover_partial"]
    by_id = {row["product"]["nm_id"]: row for row in result["items"]}
    assert by_id["42"]["turnover_days"] == "20.00" and by_id["43"]["turnover_days"] is None


def test_product_status_explains_zero_orders_without_guessing_absent_or_invalid_data(
    setup, owner_client
):
    s, c = setup, owner_client[0]
    seed(s, Source.CATALOG, [(article, card(article=article)) for article in ("42", "43", "44")])
    run_id, task_id = run(s)
    path = f"/api/v1/workspaces/{s.workspace_id}/inventory/overview"
    params = {"coverage_channel": "all", "store_id": str(s.store_id), "limit": 3}
    loading = c.get(path, params=params).json()
    assert all(item["turnover_status"] == "loading" for item in loading["items"])
    transport = WBDataClient(
        httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={
                    "data": {
                        "items": [
                            wb_row(ordersCount=0),
                            {**wb_row(officeMissingTime={"days": 0, "hours": -4}), "nmID": 43},
                        ]
                    }
                },
            )
        )
    )
    run_page(s.engine, s.redis, s.vault, s.settings, run_id, task_id, transport)
    result = c.get(path, params=params).json()
    by_id = {item["product"]["nm_id"]: item for item in result["items"]}
    assert by_id["42"]["turnover_status"] == "no_orders"
    assert by_id["43"]["turnover_status"] == by_id["44"]["turnover_status"] == "no_data"
    assert all(item["turnover_days"] is None for item in by_id.values())
    run(s)
    refreshing = c.get(path, params=params).json()
    assert refreshing["turnover_loading"]
    by_id = {item["product"]["nm_id"]: item for item in refreshing["items"]}
    assert by_id["42"]["turnover_status"] == "no_orders"
    assert by_id["43"]["turnover_status"] == "no_data"
