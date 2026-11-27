import json
from unittest.mock import patch

from sqlalchemy.orm import Session
from test_ozon_connection import connect
from test_ozon_finance_flow import env as env
from test_ozon_finance_flow import ozon as ozon
from test_ozon_finance_flow import publish, url
from test_ozon_finance_flow import pytestmark as pytestmark

from app.modules.finance.marketplace_models import MarketplaceFinanceDay
from app.modules.finance.overview import FinanceOverview
from app.modules.finance.ozon_jobs import aad
from app.modules.finance.ozon_read import merge


def test_saved_services_move_without_reimport_or_changing_any_report_total(ozon):
    e = ozon
    sid = connect(e)
    start, end = publish(e, sid)
    services = [
        ("ReturnFlowLogistic", "Обратная логистика", "-50.00"),
        ("PushCampaign", "Пуш-рассылка", "-20.00"),
        ("PremiumSubscription", "Premium Plus", "-30.00"),
        ("AnalyticsPlus", "Аналитика Plus", "-25.00"),
        ("LabelBrandVerified", "Бейдж", "-40.00"),
    ]
    with Session(e.admin) as db, db.begin():
        row = db.get(MarketplaceFinanceDay, (e.workspace, sid, end))
        value = json.loads(e.vault.open(row.ciphertext, aad(e.workspace, sid, end)))
        facts = value["currencies"]["RUB"]
        facts["settlement"] = "585.00"
        facts["lines"].extend(
            {"key": "ozon_" + name, "group": "other", "title": title, "amount": amount}
            for name, title, amount in services
        )
        row.ciphertext = e.vault.seal(json.dumps(value), aad(e.workspace, sid, end))
        original = row.ciphertext
    params = {"store_id": str(sid), "date_from": str(start), "date_to": str(end)}
    with patch("app.modules.finance.ozon_read.line_group", lambda line: line["group"]):
        before = e.client.get(url(e), params=params, headers=e.headers).json()
    response = e.client.get(url(e), params=params, headers=e.headers)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["totals"] == before["totals"]
    assert data["totals"]["settlement"] == "585.00"
    assert data["totals"]["expenses_before_tax"] == "415.00"
    groups = {g["key"]: g for g in data["groups"]}
    assert groups["logistics"]["amount"] == "100.00"
    assert groups["advertising"]["amount"] == "20.00"
    assert groups["subscriptions"]["amount"] == "55.00"
    assert groups["subscriptions"]["title"] == "Подписка"
    assert groups["other"]["amount"] == "40.00"
    assert [line["key"] for line in groups["other"]["lines"]] == ["ozon_LabelBrandVerified"]
    with Session(e.admin) as db:
        assert db.get(MarketplaceFinanceDay, (e.workspace, sid, end)).ciphertext == original

    combined = merge([FinanceOverview.model_validate(data), FinanceOverview.model_validate(data)])
    assert combined.totals.settlement == "1170.00"
    assert combined.totals.expenses_before_tax == "830.00"
    assert next(g for g in combined.groups if g.key == "subscriptions").amount == "110.00"
    assert len(combined.groups) == len({g.key for g in combined.groups})
