from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from starlette.applications import Starlette
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse
from starlette.routing import Route

from app.integrations.notifications import ExpoPush, TelegramBot
from app.modules.finance.schemas import ProfitProduct, ProfitReport, ProfitValues
from app.modules.insights import service as insights
from app.modules.insights.compute import period_params, warm_defaults
from app.modules.inventory import service as inventory
from app.modules.notifications.service import digest_section, rub
from app.security.middleware import CompressionMiddleware, SecurityMiddleware


def stock_item(**values):
    return {
        "nm_id": "1",
        "stock": 10,
        "daily_rate": "2.00",
        "demand_by_warehouse": {"Коледино": 3, "Казань": 1},
        "demand_by_size": {"M": 1, "L": 1},
        **values,
    }


def test_split_keeps_total_and_follows_demand():
    assert inventory.split(10, {"a": 3, "b": 1}) == {"a": 8, "b": 2}
    assert sum(inventory.split(7, {"a": 1, "b": 1, "c": 1}).values()) == 7
    assert inventory.split(5, {}) == {}
    assert inventory.split(0, {"a": 1}) == {}


def test_supply_plan_covers_lead_time_cover_and_safety():
    plan = inventory.supply_plan([stock_item()], lead_time_days=7, cover_days=30, safety_days=3)
    row = plan[0]
    assert row["quantity"] == 70  # 2/day × 40 days − 10 in stock
    assert row["stockout_before_arrival"] is True  # 10 − 2×7 < 0
    # 52.5 / 17.5: equal remainders, the tie goes deterministically to the first name.
    assert row["by_warehouse"] == {"Коледино": 52, "Казань": 18}
    assert sum(row["by_size"].values()) == 70
    assert "2.00 шт./день × 40 дн." in row["explanation"]


def test_supply_plan_skips_items_without_sales_and_sorts_urgent_first():
    plan = inventory.supply_plan(
        [
            stock_item(nm_id="slow", stock=500, daily_rate="1.00"),
            stock_item(nm_id="dead", daily_rate="0.00"),
            stock_item(nm_id="urgent", stock=0),
        ],
        lead_time_days=5,
        cover_days=10,
        safety_days=0,
    )
    assert [row["nm_id"] for row in plan] == ["urgent", "slow"]
    assert plan[1]["quantity"] == 0


@pytest.mark.parametrize(
    "stock,rate,cover,status",
    [
        (0, Decimal(0), None, "inactive"),
        (5, Decimal(0), None, "no_sales"),
        (0, Decimal(1), Decimal(0), "out_of_stock"),
        (5, Decimal(1), Decimal(5), "critical"),
        (12, Decimal(1), Decimal(12), "low"),
        (50, Decimal(1), Decimal(50), "ok"),
    ],
)
def test_stock_status(stock, rate, cover, status):
    assert inventory.status_for(stock, rate, cover) == status


def finance_report(products, **summary):
    return ProfitReport(
        date_from=date(2026, 9, 1),
        date_to=date(2026, 9, 30),
        currency="RUB",
        status="ready",
        is_partial=False,
        summary=ProfitValues(**summary),
        products=products,
        product_count=len(products),
        limit=100,
        offset=0,
    )


def product(nm_id, **values):
    return ProfitProduct(nm_id=nm_id, **values)


def test_money_audit_findings_cite_amounts_and_items():
    report = finance_report(
        [
            product(
                "loser",
                revenue="1000",
                contribution_before_external_expenses="-250",
                wb_expenses={"penalty": "300", "deduction": "0", "delivery_service": "400"},
                sales=20,
                returns=10,
            ),
            product("nocost", revenue="5000", issues={"missing_cost_units": 3}),
        ],
        revenue="10000",
        wb_expenses={
            "penalty": "300",
            "deduction": "200",
            "paid_storage": "150",
            "delivery_service": "2000",
        },
    )
    previous = finance_report([], revenue="9000", wb_expenses={"penalty": "100", "deduction": "0"})
    forecast = [
        {
            "nm_id": "dead",
            "status": "no_sales",
            "stock": 40,
            "lost_revenue_estimate": None,
            "days_of_cover": None,
        },
        {
            "nm_id": "gone",
            "status": "out_of_stock",
            "stock": 0,
            "lost_revenue_estimate": "700",
            "days_of_cover": 0,
        },
    ]
    findings = {item["code"]: item for item in insights.audit(report, previous, forecast)}
    assert findings["penalties"]["amount"] == "500.00"
    assert findings["penalties"]["severity"] == "high"  # 500 > 1.5 × 100
    assert findings["penalties"]["share_of_revenue_percent"] == "5.0"
    assert findings["loss_making"]["amount"] == "250.00"
    assert findings["loss_making"]["items"][0]["nm_id"] == "loser"
    assert findings["missing_cost"]["amount"] == "5000.00"
    assert findings["storage"]["dead_stock_units"] == 40
    assert findings["stockouts"]["amount"] == "700.00"
    assert findings["stockouts"]["is_estimate"] is True
    assert findings["logistics"]["share_of_revenue_percent"] == "20.0"
    assert findings["returns"]["items"][0]["return_rate_percent"] == "50.0"
    severities = [item["severity"] for item in insights.audit(report, previous, forecast)]
    assert severities == sorted(severities, key={"high": 0, "medium": 1, "info": 2}.get)


def test_unknown_amounts_produce_no_finding():
    report = finance_report([], revenue=None, wb_expenses={"penalty": None, "deduction": "5"})
    assert insights.audit(report, None, []) == []


def test_default_snapshot_params_match_endpoint_defaults():
    defaults = dict(warm_defaults())
    assert defaults["dashboard"] == period_params(None, None)
    assert defaults["unit_economics"]["margin_target"] == "15"
    assert defaults["forecast"] == {"window": inventory.WINDOW}


def test_digest_text_is_readable():
    store = SimpleNamespace(name="Мой WB")
    text = digest_section(
        store,
        {
            "currency": "RUB",
            "sales": {"yesterday": {"units": 12, "amount": "15400.5"}},
            "finance": {"net_profit": "88000", "profit_before_tax": "100000"},
            "stock": {"counts": {"critical": 2, "out_of_stock": 1}},
            "top_findings": [{"title": "Штрафы и удержания", "amount": "5000"}],
        },
    )
    assert "Вчера: 12 выкупов на 15 400 ₽" in text
    assert "88 000 ₽ (после налогов)" in text
    assert "Заканчиваются: 3" in text
    assert rub(None, "RUB") == "—"


def test_compression_skips_auth_responses():
    payload = {"value": "x" * 5000}

    async def endpoint(request):
        return JSONResponse(payload)

    app = CompressionMiddleware(
        Starlette(routes=[Route("/api/v1/auth/me", endpoint), Route("/api/v1/data", endpoint)])
    )
    client = TestClient(app)
    headers = {"Accept-Encoding": "gzip"}
    assert client.get("/api/v1/data", headers=headers).headers.get("content-encoding") == "gzip"
    assert "content-encoding" not in client.get("/api/v1/auth/me", headers=headers).headers


def test_rate_limited_response_keeps_cors_headers(isolated_settings):
    app = Starlette()
    app.state.redis = Mock()
    app.state.redis.eval.return_value = 10_000
    app.state.vault = Mock()
    app.state.vault.digest.return_value = "key"
    app.add_middleware(SecurityMiddleware, settings=isolated_settings)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=isolated_settings.cors_origins,
        allow_credentials=True,
        expose_headers=["Retry-After"],
    )
    origin = isolated_settings.cors_origins[0]
    response = TestClient(app).get("/api/v1/anything", headers={"Origin": origin})
    assert response.status_code == 429
    assert response.headers["access-control-allow-origin"] == origin
    assert "Retry-After" in response.headers["access-control-expose-headers"]


def test_telegram_bot_and_expo_push_requests(tmp_path):
    import json

    import httpx

    seen = []

    def handler(request):
        seen.append((str(request.url), json.loads(request.content)))
        if "exp.host" in str(request.url):
            return httpx.Response(
                200,
                json={
                    "data": [
                        {"status": "ok"},
                        {"status": "error", "details": {"error": "DeviceNotRegistered"}},
                    ]
                },
            )
        return httpx.Response(200, json={"ok": True, "result": {}})

    token = tmp_path / "bot"
    token.write_text("123:abc")
    transport = httpx.MockTransport(handler)
    TelegramBot(token, transport=transport).send_message("555", "Привет")
    stale = ExpoPush(transport=transport).send_push(
        ["ExponentPushToken[aaaaaaaaaaaa]", "ExponentPushToken[bbbbbbbbbbbb]"],
        "Заголовок",
        "Текст",
        {"kind": "digest"},
    )
    assert seen[0][0] == "https://api.telegram.org/bot123:abc/sendMessage"
    assert seen[0][1]["chat_id"] == "555"
    assert seen[1][0] == "https://exp.host/--/api/v2/push/send"
    assert stale == ["ExponentPushToken[bbbbbbbbbbbb]"]


def test_forecast_response_accepts_both_demand_bases():
    from datetime import UTC, datetime

    from app.modules.inventory.router import StockForecast

    for basis in ("orders", "buyouts"):
        value = StockForecast(
            status="no_data",
            snapshot_day=None,
            window_days=30,
            items=[],
            counts={},
            freshness={"computed_at": datetime.now(UTC), "stale": False},
            stock_as_of=None,
            observed_days=0,
            source_stale=True,
            demand_basis=basis,
        )
        assert value.demand_basis == basis
