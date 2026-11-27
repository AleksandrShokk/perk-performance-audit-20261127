from sqlalchemy.orm import Session
from test_profit_rules import finance_row
from test_wb_sync_database import import_profit_facts, prepare_profit
from test_wb_sync_database import owner_client as owner_client
from test_wb_sync_database import pytestmark as pytestmark
from test_wb_sync_database import setup as setup

from app.modules.finance.models import FinanceProjection


def test_missing_cost_counts_variants_once_while_units_count_the_whole_period(setup, owner_client):
    s = setup
    import_profit_facts(
        s,
        [
            finance_row(barcode="0001", quantity=2),
            finance_row(barcode="0001", quantity=3, report_date="2026-10-02"),
            finance_row(barcode="0002", quantity=4),
            finance_row(nm_id="43", barcode="0003", quantity=1),
        ],
    )
    assert prepare_profit(s)
    client, path = owner_client
    response = client.get(
        path + "/finance/summary", params={"date_from": "2026-10-01", "date_to": "2026-10-03"}
    )
    assert response.status_code == 200
    summary = response.json()["summary"]
    assert summary["issues"]["missing_cost_units"] == 10
    assert summary["financial_details"]["missing_cost_skus"] == "3"


def test_finance_keeps_loading_until_the_published_import_is_projected(setup, owner_client):
    s = setup
    import_profit_facts(s, [finance_row()])
    assert prepare_profit(s)
    with Session(s.admin) as db, db.begin():
        state = db.get(FinanceProjection, (s.workspace_id, s.store_id))
        state.updated_at = state.updated_at.replace(year=2020)
    client, path = owner_client
    root = path.rsplit("/stores", 1)[0] + "/finance/overview"
    response = client.get(root, params={"date_from": "2026-10-01", "date_to": "2026-10-03"})
    assert response.status_code == 200
    assert response.json()["is_loading"]
