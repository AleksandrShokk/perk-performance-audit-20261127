"""Buyouts older than 90 days from financial reports, grouped by sale date."""

import json
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session
from test_wb_sync_database import make_run, process
from test_wb_sync_database import owner_client as owner_client
from test_wb_sync_database import pytestmark as pytestmark
from test_wb_sync_database import setup as setup

from app.db.session import set_actor
from app.integrations.wildberries.data import Page, Source
from app.modules.auth.dependencies import now
from app.modules.insights import compute
from app.modules.sync import analytics
from app.modules.sync.models import SyncRun, WBDailyMetric, WBMetricVersion


def buyouts(s, start, end):
    with Session(s.engine) as db, db.begin():
        set_actor(db, s.user_id)
        params = {"date_from": start.isoformat(), "date_to": end.isoformat()}
        return compute.build("buyouts", params, db, None, s.vault, s.workspace_id, s.store_id)


def test_old_buyouts_come_from_reports_by_sale_date(setup, owner_client):
    s = setup
    client, path = owner_client
    sold = now().date() - timedelta(days=200)
    reported = sold + timedelta(days=8)
    start, end = sold - timedelta(days=40), now().date() - timedelta(days=100)
    row = {
        "rrdId": 1,
        "reportId": 7,
        "nmId": 42,
        "quantity": 2,
        "rrDate": str(reported),
        "saleDt": f"{sold}T15:00:00",
        "currency": "RUB",
        "docTypeName": "Продажа",
        "sellerOperName": "Продажа",
        "retailAmount": "300.00",
        "forPay": "250.00",
    }
    run_id, task_id = make_run(s, Source.FINANCE)
    with Session(s.engine) as db, db.begin():
        set_actor(db, s.user_id)
        run = db.get(SyncRun, run_id)
        run.date_from, run.date_to = start, end
    process(
        s,
        run_id,
        task_id,
        Page(
            [
                row,
                {
                    **row,
                    "rrdId": 2,
                    "quantity": 1,
                    "docTypeName": "Возврат",
                    "sellerOperName": "Возврат",
                    "retailAmount": "150.00",
                },
                {**row, "rrdId": 3, "sellerOperName": "Логистика", "quantity": 0},
            ],
            {},
            True,
        ),
    )
    result = buyouts(s, sold, sold)
    assert result["status"] == "ready" and result["daily"][0]["source"] == "finance_report"
    assert result["totals"] == {"sales": 2, "returns": 1, "net_units": 1}
    assert result["amounts"][0]["basis"] == "retail_price"
    assert result["amounts"][0]["net_amount"] == "150.00"
    # The report date has no buyouts in this report: they belong to the sale date.
    assert buyouts(s, reported, reported)["totals"]["sales"] == 0
    assert result["products"][0]["nm_id"] == "42"

    # The existing analytics endpoint is unchanged: report date, no extra zero days.
    legacy = client.get(
        path + f"/analytics?date_from={start}&date_to={end}&sales_basis=reports"
    ).json()
    assert legacy["sales"]["sales"] == 2
    assert [day["day"] for day in legacy["financial_daily"]] == [str(reported)]
    response = client.get(path + f"/insights/buyouts?date_from={sold}&date_to={sold}")
    assert response.status_code == 200, response.text
    assert response.json()["totals"]["net_units"] == 1

    # Older aggregates (format 2) are upgraded from retained rows, without a WB download.
    with Session(s.engine) as db, db.begin():
        set_actor(db, s.user_id)
        db.get(WBMetricVersion, (s.workspace_id, s.store_id)).format_version = 2
        for metric in db.scalars(select(WBDailyMetric).where(WBDailyMetric.day == sold)):
            db.delete(metric)
    assert buyouts(s, sold, sold)["status"] == "preparing"
    with Session(s.engine) as db, db.begin():
        set_actor(db, s.user_id)
        analytics.rebuild_store(db, s.vault, s.workspace_id, s.store_id)
        metric = db.scalar(select(WBDailyMetric).where(WBDailyMetric.day == sold))
        aad = analytics.metric_context(
            metric.workspace_id,
            metric.store_id,
            metric.source,
            metric.dataset,
            metric.day,
            metric.nm_id,
            metric.currency,
        )
        assert json.loads(s.vault.open(metric.ciphertext, aad))["report_bydate_sales"] == "2"
    assert buyouts(s, sold, sold)["totals"]["net_units"] == 1
