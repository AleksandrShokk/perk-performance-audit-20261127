import json
import os
import re
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import build_engine, set_actor
from app.main import create_app
from app.modules.accounts.models import Store, StoreCredential, Workspace
from app.modules.auth.dependencies import now
from app.modules.auth.models import Membership, OtpChallenge, User
from app.modules.insights.compute import period_params
from app.modules.inventory.projection import build_snapshot
from app.modules.notifications import service as notifications
from app.modules.notifications.models import NotificationSettings
from app.modules.sync.analytics import rebuild_store, record_context
from app.modules.sync.models import SyncRun, WBRecord
from app.modules.sync.schemas import moscow_today
from app.security.crypto import PASSWORD_HASHER, SecretVault

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("PERK_INTEGRATION_TESTS") != "1",
        reason="Requires disposable PostgreSQL test stack",
    ),
]
PASSWORD = "correct horse battery staple"


class Inbox:
    def __init__(self):
        self.emails, self.messages, self.pushes = [], [], []

    def phone_channels(self):
        return ["telegram", "sms"]

    def send_email(self, to, subject, body, *, html=None):
        self.emails.append((to, body))

    def send_phone_code(self, channel, phone, code, ttl):
        pass

    def send_message(self, chat_id, text):
        self.messages.append((chat_id, text))

    def send_push(self, tokens, title, body, data):
        self.pushes.append((tokens, title))
        return []

    def code(self, to):
        body = next(body for address, body in reversed(self.emails) if address == to)
        return re.search(r": (\d{6})", body)[1]


def seal(vault, workspace_id, store_id, source, key, value):
    return WBRecord(
        workspace_id=workspace_id,
        store_id=store_id,
        source=source,
        record_key=key,
        updated_at=now(),
        ciphertext=vault.seal(
            json.dumps(value), record_context(workspace_id, store_id, source, key)
        ),
    )


@pytest.fixture
def env():
    settings = get_settings().model_copy(update={"auth_limit_per_minute": 100})
    admin = build_engine(
        settings.model_copy(
            update={
                "postgres_user": os.environ["TEST_ADMIN_USER"],
                "postgres_password_file": Path(os.environ["TEST_ADMIN_PASSWORD_FILE"]),
            }
        )
    )
    engine = build_engine(settings)
    vault = SecretVault(settings.security_file)
    owner_id, viewer_id, workspace_id, store_id = uuid4(), uuid4(), uuid4(), uuid4()
    emails = {owner_id: f"{owner_id.hex}@example.com", viewer_id: f"{viewer_id.hex}@example.com"}
    with Session(admin) as db, db.begin():
        for user_id, email in emails.items():
            db.add(
                User(
                    id=user_id,
                    email=email,
                    password_hash=PASSWORD_HASHER.hash(PASSWORD),
                    email_verified_at=now(),
                )
            )
        db.flush()
        db.add(Workspace(id=workspace_id, name="Insights", owner_user_id=owner_id))
        db.flush()
        db.add(Membership(user_id=owner_id, workspace_id=workspace_id, role="owner"))
        db.add(Membership(user_id=viewer_id, workspace_id=workspace_id, role="viewer"))
        db.add(
            Store(
                id=store_id,
                workspace_id=workspace_id,
                name="Тестовый WB",
                marketplace="wildberries",
                external_seller_id=str(uuid4()),
                connection_status="connected",
            )
        )
        db.flush()
        db.add(
            StoreCredential(
                workspace_id=workspace_id,
                store_id=store_id,
                ciphertext="unused",
                scopes="statistics",
                expires_at=now() + timedelta(days=3),
            )
        )
    today = moscow_today()
    with Session(engine) as db, db.begin():
        set_actor(db, owner_id)
        for source in ("stocks", "sales"):
            db.add(
                SyncRun(
                    workspace_id=workspace_id,
                    store_id=store_id,
                    source=source,
                    status="succeeded",
                    requested_by=owner_id,
                    date_from=today - timedelta(days=30),
                    date_to=today,
                    finished_at=now(),
                )
            )
        records = [
            seal(
                vault,
                workspace_id,
                store_id,
                "catalog",
                "101",
                {
                    "nm_id": "101",
                    "vendor_code": "A",
                    "title": "Куртка",
                    "brand": "B",
                    "subject": "Куртки",
                    "sizes": [
                        {"chrt_id": "1", "size": "M", "barcodes": ["b1"]},
                        {"chrt_id": "2", "size": "L", "barcodes": ["b2"]},
                    ],
                },
            ),
            seal(
                vault,
                workspace_id,
                store_id,
                "stocks",
                "101:1:10",
                {
                    "nm_id": "101",
                    "chrt_id": "1",
                    "warehouse_id": "10",
                    "warehouse_name": "Коледино",
                    "quantity": 1,
                    "in_way_to_client": 1,
                    "in_way_from_client": 0,
                },
            ),
            seal(
                vault,
                workspace_id,
                store_id,
                "stocks",
                "101:2:10",
                {
                    "nm_id": "101",
                    "chrt_id": "2",
                    "warehouse_id": "10",
                    "warehouse_name": "Коледино",
                    "quantity": 1,
                    "in_way_to_client": 0,
                    "in_way_from_client": 0,
                },
            ),
            seal(
                vault,
                workspace_id,
                store_id,
                "stocks",
                "202:3:10",
                {
                    "nm_id": "202",
                    "chrt_id": "3",
                    "warehouse_id": "10",
                    "warehouse_name": "Казань",
                    "quantity": 50,
                    "in_way_to_client": 0,
                    "in_way_from_client": 0,
                },
            ),
        ]
        for index in range(20):
            day = today - timedelta(days=1 + index % 10)
            records.append(
                seal(
                    vault,
                    workspace_id,
                    store_id,
                    "sales",
                    f"S{index}",
                    {
                        "sale_id": f"S{index}",
                        "nm_id": "101",
                        "kind": "sale",
                        "date": f"{day}T12:00:00",
                        "last_change_date": f"{day}T12:00:00",
                        "vendor_code": "A",
                        "barcode": "b1" if index % 4 else "b2",
                        "warehouse_name": "Коледино" if index % 2 else "Казань",
                        "price_with_discount": "1000",
                        "finished_price": "1000",
                        "for_pay": "700",
                        "preliminary": True,
                    },
                )
            )
        db.add_all(records)
        db.flush()
        rebuild_store(db, vault, workspace_id, store_id)
        assert build_snapshot(db, vault, workspace_id, store_id)

    with TestClient(create_app(settings)) as client:
        inbox = Inbox()
        client.app.state.notifier = inbox
        client.app.state.telegram_bot = inbox

        def reset_limits():
            redis = client.app.state.redis
            keys = list(redis.scan_iter("perk:limit:*"))
            if keys:
                redis.delete(*keys)

        def login(user_id):
            reset_limits()
            email = emails[user_id]
            pending = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
            full = client.post(
                "/api/v1/auth/mfa/verify",
                json={"code": inbox.code(email)},
                headers={"Authorization": "Bearer " + pending.json()["access_token"]},
            )
            assert full.status_code == 200, full.text
            return {"Authorization": "Bearer " + full.json()["access_token"]}

        def password_only(user_id):
            reset_limits()
            pending = client.post(
                "/api/v1/auth/login", json={"email": emails[user_id], "password": PASSWORD}
            )
            return {"Authorization": "Bearer " + pending.json()["access_token"]}

        reset_limits()
        yield type(
            "Env",
            (),
            dict(
                client=client,
                inbox=inbox,
                engine=engine,
                admin=admin,
                vault=vault,
                owner=owner_id,
                viewer=viewer_id,
                workspace=workspace_id,
                store=store_id,
                base=f"/api/v1/workspaces/{workspace_id}/stores/{store_id}",
                login=login,
                password_only=password_only,
                emails=emails,
            ),
        )
    with Session(admin) as db, db.begin():
        db.execute(delete(Workspace).where(Workspace.id == workspace_id))
        db.execute(delete(User).where(User.id.in_(list(emails))))
    engine.dispose()
    admin.dispose()


def test_forecast_supply_plan_history_and_etag(env):
    headers = env.login(env.owner)
    response = env.client.get(env.base + "/inventory/forecast", headers=headers)
    assert response.status_code == 200, response.text
    data = response.json()
    items = {item["nm_id"]: item for item in data["items"]}
    jacket = items["101"]
    assert jacket["stock"] == 2 and jacket["sold_units"] == 20
    assert jacket["daily_rate"] == "0.67"
    assert jacket["days_of_cover"] == 3 and jacket["status"] == "critical"
    assert jacket["sizes"] == {"M": 1, "L": 1}
    assert jacket["demand_by_warehouse"] == {"Коледино": 10, "Казань": 10}
    assert items["202"]["status"] == "no_sales"
    assert data["freshness"]["stale"] is False

    etag = response.headers["etag"]
    again = env.client.get(
        env.base + "/inventory/forecast", headers={**headers, "If-None-Match": etag}
    )
    assert again.status_code == 304 and not again.content

    plan = env.client.post(env.base + "/inventory/supply-plan", json={}, headers=headers).json()
    row = next(item for item in plan["items"] if item["nm_id"] == "101")
    assert row["quantity"] == 25  # ceil(0.6667 × 40 − 2)
    assert sum(row["by_warehouse"].values()) == 25
    assert row["stockout_before_arrival"] is True

    today = moscow_today()
    history = env.client.get(
        env.base + "/inventory/history",
        params={"date_from": str(today - timedelta(days=7)), "date_to": str(today)},
        headers=headers,
    ).json()
    assert history[-1]["stock"] == 52


def test_snapshot_is_served_stale_then_refreshed_in_background(env):
    from app.workers.tasks import compute_insight

    headers = env.login(env.owner)
    first = env.client.get(env.base + "/dashboard", headers=headers)
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["freshness"]["stale"] is False
    assert body["stock"]["counts"]["critical"] == 1
    assert body["stock"]["urgent"][0]["nm_id"] == "101"
    assert sum(day["units"] for day in body["sales"]["last_7_days"]) == 14

    saved = env.client.put(
        env.base + "/tax-settings",
        json={"effective_from": "2024-01-01", "regime": "usn_income", "rate": "6"},
        headers=headers,
    )
    assert saved.status_code == 200, saved.text
    stale = env.client.get(env.base + "/dashboard", headers=headers).json()
    assert stale["freshness"]["stale"] is True
    assert stale["freshness"]["computed_at"] == body["freshness"]["computed_at"]

    compute_insight(
        str(env.workspace),
        str(env.store),
        str(env.owner),
        "dashboard",
        period_params(None, None),
        "test-lease",
    )
    fresh = env.client.get(env.base + "/dashboard", headers=headers).json()
    assert fresh["freshness"]["stale"] is False
    assert fresh["freshness"]["computed_at"] > body["freshness"]["computed_at"]


def test_viewer_reads_snapshots_but_cannot_change_store_settings(env):
    headers = env.login(env.viewer)
    assert env.client.get(env.base + "/inventory/forecast", headers=headers).status_code == 200
    assert env.client.get(env.base + "/insights/audit", headers=headers).status_code == 200
    denied = env.client.put(
        env.base + "/tax-settings",
        json={"effective_from": "2024-01-01", "regime": "none", "rate": "0"},
        headers=headers,
    )
    assert denied.status_code == 403
    other = f"/api/v1/workspaces/{uuid4()}/stores/{env.store}/dashboard"
    assert env.client.get(other, headers=headers).status_code == 404


def test_events_journal_and_goals(env):
    headers = env.login(env.owner)
    today = moscow_today()
    for nm_id, title in ((None, "Распродажа"), ("101", "Сменили фото"), ("202", "Чужой")):
        created = env.client.post(
            env.base + "/events",
            json={"day": str(today), "kind": "content", "title": title, "nm_id": nm_id},
            headers=headers,
        )
        assert created.status_code == 201, created.text
    events = env.client.get(
        env.base + "/events",
        params={"date_from": str(today), "date_to": str(today), "nm_id": "101"},
        headers=headers,
    ).json()
    assert sorted(item["title"] for item in events) == ["Распродажа", "Сменили фото"]

    goal = env.client.put(
        env.base + "/goals",
        json={"month": str(today), "metric": "revenue", "target": "100000"},
        headers=headers,
    )
    assert goal.status_code == 200
    progress = env.client.get(env.base + "/goals", headers=headers).json()
    revenue = next(item for item in progress["metrics"] if item["metric"] == "revenue")
    assert revenue["target"] == "100000.00"
    assert progress["forecast_method"] == "linear_run_rate"


def test_alerts_digest_delivery_feed_and_telegram_link(env):
    headers = env.login(env.owner)
    # Snapshots the generator reads; the warm task creates them after each import.
    env.client.get(env.base + "/inventory/forecast", headers=headers)
    env.client.get(env.base + "/dashboard", headers=headers)
    device = env.client.post(
        "/api/v1/notifications/devices",
        json={"token": "ExponentPushToken[abcdefghijklmnop]", "platform": "ios"},
        headers=headers,
    )
    assert device.status_code == 204

    link = env.client.post("/api/v1/notifications/telegram/link", headers=headers).json()
    code = link["url"].rsplit("start=", 1)[1]
    hook = env.client.post(
        "/api/v1/integrations/telegram/webhook",
        json={"message": {"text": f"/start {code}", "chat": {"id": 777}}},
        headers={"X-Telegram-Bot-Api-Secret-Token": "dev"},
    )
    assert hook.status_code == 200
    assert (
        env.client.post(
            "/api/v1/integrations/telegram/webhook",
            json={},
            headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"},
        ).status_code
        == 404
    )
    settings = env.client.get("/api/v1/notifications/settings", headers=headers).json()
    assert settings["telegram_linked"] is True

    with Session(env.engine) as db, db.begin():
        set_actor(db, env.owner)
        row = db.get(NotificationSettings, env.owner)
        row.digest_hour = 0
    with Session(env.engine) as db, db.begin():
        set_actor(db, env.owner)
        created = notifications.generate(db, env.vault, env.owner)
    assert created == 3  # stock alert, token expiry, digest
    with Session(env.engine) as db, db.begin():
        set_actor(db, env.owner)
        assert notifications.generate(db, env.vault, env.owner) == 0  # deduplicated
    with Session(env.engine) as db, db.begin():
        sent = notifications.deliver(db, env.vault, env.owner, env.inbox, env.inbox)
    assert sent == 3
    assert any("Утренняя сводка" in text for _, text in env.inbox.messages)
    assert env.inbox.pushes[0][0] == ["ExponentPushToken[abcdefghijklmnop]"]

    feed = env.client.get("/api/v1/notifications", headers=headers).json()
    assert feed["unread_count"] == 3
    assert {item["kind"] for item in feed["items"]} == {"stock", "token_expiring", "digest"}
    env.client.post("/api/v1/notifications/read-all", headers=headers)
    assert env.client.get("/api/v1/notifications", headers=headers).json()["unread_count"] == 0


def test_cleanup_removes_only_expired_rows(env):
    marker = uuid4().hex * 2
    with Session(env.admin) as db, db.begin():
        for expires in (now() - timedelta(days=2), now() + timedelta(minutes=5)):
            db.add(
                OtpChallenge(
                    purpose="password_reset",
                    channel="email",
                    destination_digest=marker,
                    code_digest="y" * 64,
                    last_sent_at=now(),
                    expires_at=expires,
                )
            )
    with Session(env.engine) as db, db.begin():
        assert db.scalar(text("SELECT perk_cleanup_expired()")) >= 1
    with Session(env.admin) as db:
        remaining = db.scalars(
            select(OtpChallenge.expires_at).where(OtpChallenge.destination_digest == marker)
        ).all()
    assert len(remaining) == 1 and remaining[0] > now()


# Regressions for the 21 October 2026 audit: expectations are the corrected behaviour.


def test_a01_editing_a_tax_rate_marks_snapshots_stale_and_refresh_applies_it(env):
    from app.workers.tasks import compute_insight

    headers = env.login(env.owner)
    body = {"effective_from": "2024-01-01", "regime": "usn_income", "rate": "6"}
    assert env.client.put(env.base + "/tax-settings", json=body, headers=headers).status_code == 200
    first = env.client.get(env.base + "/finance/net-profit", headers=headers).json()
    assert first["tax_setting"]["rate"] == "6.00"
    edited = env.client.put(
        env.base + "/tax-settings", json={**body, "rate": "15"}, headers=headers
    )
    assert edited.status_code == 200
    stale = env.client.get(env.base + "/finance/net-profit", headers=headers).json()
    assert stale["freshness"]["stale"] is True  # same row, new value: no longer "fresh"
    compute_insight(
        str(env.workspace),
        str(env.store),
        str(env.owner),
        "net_profit",
        period_params(None, None),
        "test-lease",
    )
    fresh = env.client.get(env.base + "/finance/net-profit", headers=headers).json()
    assert fresh["freshness"]["stale"] is False
    assert fresh["tax_setting"]["rate"] == "15.00"


def test_a02_concurrent_first_reads_compute_once_without_errors(env):
    from concurrent.futures import ThreadPoolExecutor

    from app.modules.insights.models import InsightSnapshot

    headers = env.login(env.owner)
    today = moscow_today()
    params = {
        "date_from": str(today - timedelta(days=20)),
        "date_to": str(today - timedelta(days=2)),
    }

    def read(_):
        return env.client.get(env.base + "/insights/audit", params=params, headers=headers)

    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(read, range(4)))
    assert [response.status_code for response in responses] == [200] * 4
    times = {response.json()["freshness"]["computed_at"] for response in responses}
    assert len(times) == 1  # one computation, reused by the readers that waited
    with Session(env.admin) as db:
        rows = db.scalars(
            select(InsightSnapshot).where(
                InsightSnapshot.store_id == env.store, InsightSnapshot.kind == "audit"
            )
        ).all()
    assert len(rows) == 1


def test_a03_old_stock_import_is_never_recorded_as_a_new_day(env):
    from app.modules.inventory.models import InventorySnapshot

    headers = env.login(env.owner)
    old = now() - timedelta(days=10)
    with Session(env.engine) as db, db.begin():
        set_actor(db, env.owner)
        # Already recorded: a later warm-up for another source writes nothing.
        assert build_snapshot(db, env.vault, env.workspace, env.store) is False
        db.execute(delete(InventorySnapshot).where(InventorySnapshot.store_id == env.store))
        run = db.scalar(
            select(SyncRun).where(SyncRun.store_id == env.store, SyncRun.source == "stocks")
        )
        run.finished_at = old
    with Session(env.engine) as db, db.begin():
        set_actor(db, env.owner)
        assert build_snapshot(db, env.vault, env.workspace, env.store) is True
        days = db.scalars(
            select(InventorySnapshot.day).where(InventorySnapshot.store_id == env.store)
        ).all()
    assert set(days) == {(old + timedelta(hours=3)).date()}  # the day it was taken
    forecast = env.client.get(env.base + "/inventory/forecast", headers=headers).json()
    assert forecast["source_stale"] is True
    assert forecast["stock_as_of"].startswith(old.date().isoformat()[:7])


def test_a04_password_only_session_cannot_revoke_other_sessions(env):
    full = env.login(env.owner)
    pending = env.password_only(env.owner)
    assert env.client.post("/api/v1/auth/logout-all", headers=pending).status_code == 403
    assert env.client.get("/api/v1/workspaces", headers=full).status_code == 200
    # The limited session can still end itself.
    assert env.client.post("/api/v1/auth/logout", headers=pending).status_code == 200


def test_a05_first_read_reports_a_tax_change_inside_the_period(env):
    headers = env.login(env.owner)
    today = moscow_today()
    for offset, rate in ((60, "6"), (10, "15")):
        env.client.put(
            env.base + "/tax-settings",
            json={
                "effective_from": str(today - timedelta(days=offset)),
                "regime": "usn_income",
                "rate": rate,
            },
            headers=headers,
        )
    params = {
        "date_from": str(today - timedelta(days=30)),
        "date_to": str(today - timedelta(days=1)),
    }
    first = env.client.get(env.base + "/finance/net-profit", params=params, headers=headers)
    second = env.client.get(env.base + "/finance/net-profit", params=params, headers=headers)
    assert first.json()["tax_setting_changed_in_period"] is True
    assert second.json()["tax_setting_changed_in_period"] is True


def test_a06_unknown_sales_days_are_null_not_zero(env):
    empty_store = uuid4()
    with Session(env.admin) as db, db.begin():
        db.add(
            Store(
                id=empty_store,
                workspace_id=env.workspace,
                name="Пустой",
                marketplace="wildberries",
                external_seller_id=str(uuid4()),
                connection_status="connected",
            )
        )
    headers = env.login(env.owner)
    path = f"/api/v1/workspaces/{env.workspace}/stores/{empty_store}/dashboard"
    sales = env.client.get(path, headers=headers).json()["sales"]
    assert sales["status"] == "no_data"
    assert all(day["units"] is None and day["amount"] is None for day in sales["last_7_days"])
    known = env.client.get(env.base + "/dashboard", headers=headers).json()["sales"]
    assert known["status"] == "ready"
    assert all(day["known"] for day in known["last_7_days"])


def test_a07_browser_can_use_etag_cross_origin(env):
    origin = env.client.app.state.settings.cors_origins[0]
    preflight = env.client.options(
        env.base + "/dashboard",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization,if-none-match",
        },
    )
    assert preflight.status_code == 200
    assert "if-none-match" in preflight.headers["access-control-allow-headers"].lower()
    headers = env.login(env.owner)
    response = env.client.get(env.base + "/dashboard", headers={**headers, "Origin": origin})
    assert "etag" in response.headers["access-control-expose-headers"].lower()
    cached = env.client.get(
        env.base + "/dashboard",
        headers={**headers, "Origin": origin, "If-None-Match": response.headers["etag"]},
    )
    assert cached.status_code == 304


def test_a08_new_reports_reject_invalid_periods(env):
    headers = env.login(env.owner)
    for params in (
        {"date_from": "2026-05-02", "date_to": "2026-05-01"},
        {"date_from": "0001-01-01", "date_to": "0001-01-02"},
        {"date_from": "2026-01-01"},
    ):
        for path in ("/finance/net-profit", "/insights/audit", "/finance/unit-economics"):
            response = env.client.get(env.base + path, params=params, headers=headers)
            assert response.status_code == 422, (path, params, response.text)
