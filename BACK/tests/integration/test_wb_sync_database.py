import base64
import json
import os
import time
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, event, func, select, text
from sqlalchemy.exc import IntegrityError, ProgrammingError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import build_engine, set_actor
from app.integrations.wildberries.data import Page, Source, WBError
from app.main import create_app
from app.modules.accounts.models import Store, StoreCredential, Workspace
from app.modules.auth.dependencies import Identity, full_identity, now
from app.modules.auth.models import AuthSession, Membership, User
from app.modules.sync.models import SyncRun, WBRecord, WBStagedRecord
from app.modules.sync.schemas import FINANCE_START, history_limits
from app.modules.sync.service import context, run_page

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("PERK_INTEGRATION_TESTS") != "1",
        reason="Requires disposable PostgreSQL test stack",
    ),
]


@pytest.fixture
def setup(vault):
    settings = get_settings()
    admin_settings = settings.model_copy(
        update={
            "postgres_user": os.environ["TEST_ADMIN_USER"],
            "postgres_password_file": Path(os.environ["TEST_ADMIN_PASSWORD_FILE"]),
        }
    )
    admin = build_engine(admin_settings)
    engine = build_engine(settings)
    user_id, workspace_id, store_id, other_id = uuid4(), uuid4(), uuid4(), uuid4()
    seller_id = str(uuid4())

    def encode(data):
        return base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=")

    # Synthetic token; external calls in these tests are mocked.
    token = (
        encode({"alg": "HS256"})
        + "."
        + encode(
            {
                "s": (1 << 30) | (1 << 1) | (1 << 2) | (1 << 5) | (1 << 13),
                "exp": int(time.time()) + 3600,
                "sid": seller_id,
                "t": False,
                "acc": 3,
            }
        )
        + ".synthetic-signature"
    )
    with Session(admin) as db, db.begin():
        db.add_all(
            [
                User(
                    id=user_id,
                    email=f"{user_id}@example.test",
                    password_hash="unused",
                    email_verified_at=now(),
                ),
                User(
                    id=other_id,
                    email=f"{other_id}@example.test",
                    password_hash="unused",
                    email_verified_at=now(),
                ),
            ]
        )
        db.flush()
        db.add(Workspace(id=workspace_id, name="Isolated sync test", owner_user_id=user_id))
        db.flush()
        db.add(Membership(user_id=user_id, workspace_id=workspace_id, role="owner"))
        db.add(
            Store(
                id=store_id,
                workspace_id=workspace_id,
                name="Synthetic WB",
                marketplace="wildberries",
                external_seller_id=seller_id,
                connection_status="connected",
            )
        )
        db.flush()
        db.add(
            StoreCredential(
                workspace_id=workspace_id,
                store_id=store_id,
                ciphertext=vault.seal(token, f"wb:{workspace_id}:{store_id}"),
                scopes="content,statistics,analytics,finance",
                expires_at=now() + timedelta(hours=1),
            )
        )
    redis = Mock()
    redis.set.return_value = True
    redis.ttl.return_value = 0
    obj = SimpleNamespace(
        engine=engine,
        admin=admin,
        settings=settings,
        vault=vault,
        redis=redis,
        user_id=user_id,
        workspace_id=workspace_id,
        store_id=store_id,
        other_id=other_id,
        seller_id=seller_id,
    )
    try:
        yield obj
    finally:
        with Session(admin) as db, db.begin():
            db.execute(delete(Workspace).where(Workspace.id == workspace_id))
            db.execute(delete(User).where(User.id.in_([user_id, other_id])))
        engine.dispose()
        admin.dispose()


def make_run(s, source):
    with Session(s.engine) as db, db.begin():
        set_actor(db, s.user_id)
        run = SyncRun(
            id=uuid4(),
            workspace_id=s.workspace_id,
            store_id=s.store_id,
            requested_by=s.user_id,
            source=source,
            task_id=str(uuid4()),
            date_from=now().date() - timedelta(days=1),
            date_to=now().date() - timedelta(days=1),
        )
        db.add(run)
        return run.id, run.task_id


def test_success_headers_extend_only_remaining_cooldown(setup):
    s = setup
    run_id, task_id = make_run(s, Source.SALES)
    transport = Mock()
    transport.page.return_value = Page([], {}, True, cooldown_seconds=30)
    run_page(s.engine, s.redis, s.vault, s.settings, run_id, task_id, client=transport)
    # The minimum interval was already reserved before sending the request. Receiving
    # a short remaining provider wait must not reserve another whole minute.
    assert s.redis.eval.call_args.args[-1] == 30


def process(s, run_id, task_id, page=None, error=None):
    client = Mock()
    if error:
        client.page.side_effect = error
    else:
        client.page.return_value = page
    run_page(s.engine, s.redis, s.vault, s.settings, run_id, task_id, client)
    return client


def requeue(s, run_id):
    with Session(s.engine) as db, db.begin():
        set_actor(db, s.user_id)
        run = db.get(SyncRun, run_id)
        run.task_id = str(uuid4())
        return run.task_id


def records(s):
    with Session(s.engine) as db:
        set_actor(db, s.user_id)
        return db.scalars(select(WBRecord).where(WBRecord.workspace_id == s.workspace_id)).all()


@pytest.fixture
def owner_client(setup):
    from app.db.session import get_db

    s = setup
    app = create_app(s.settings)

    def test_db():
        with Session(s.engine, expire_on_commit=False) as db:
            set_actor(db, s.user_id)
            yield db

    app.dependency_overrides[get_db] = test_db
    app.dependency_overrides[full_identity] = lambda: Identity(User(id=s.user_id), AuthSession())
    with TestClient(app) as client:
        app.state.vault = s.vault
        yield client, f"/api/v1/workspaces/{s.workspace_id}/stores/{s.store_id}"


def test_initial_preview_is_partial_and_refresh_preserves_published_data(setup, owner_client):
    s = setup
    client, path = owner_client
    run_id, task_id = make_run(s, Source.CATALOG)
    process(s, run_id, task_id, Page([{"nmID": 42, "title": "First"}], {"nmID": 42}, False))
    response = client.get(path + "/data/catalog").json()
    assert response["is_partial"] is True
    assert response["total"] == 1
    assert response["items"][0]["nm_id"] == "42"
    assert response["last_successful_run"] is None
    assert response["updated_at"] is not None
    assert records(s) == []
    assert client.get(path + "/data/catalog?offset=1").json()["total"] == 1

    process(s, run_id, requeue(s, run_id), Page([], {}, True))
    assert client.get(path + "/data/catalog").json()["is_partial"] is False
    newer, next_id = make_run(s, Source.CATALOG)
    process(s, newer, next_id, Page([{"nmID": 43}], {}, False))
    response = client.get(path + "/data/catalog").json()
    assert response["is_partial"] is False
    assert response["items"][0]["nm_id"] == "42"
    assert response["latest_run"]["records_processed"] == 1
    process(s, newer, requeue(s, newer), error=WBError("wb_access_denied"))
    assert client.get(path + "/data/catalog").json()["items"][0]["nm_id"] == "42"


def test_basic_token_does_not_block_sales_and_finance_or_call_stocks(setup, owner_client):
    s = setup
    client, path = owner_client
    with Session(s.admin) as db, db.begin():
        credential = db.scalar(
            select(StoreCredential).where(StoreCredential.store_id == s.store_id)
        )
        token = s.vault.open(credential.ciphertext, f"wb:{s.workspace_id}:{s.store_id}")
        header, body, signature = token.split(".")
        payload = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
        payload["acc"] = 1
        body = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
        credential.ciphertext = s.vault.seal(
            f"{header}.{body}.{signature}", f"wb:{s.workspace_id}:{s.store_id}"
        )
    capabilities = client.get(path + "/sync-capabilities").json()
    assert capabilities["token_type"] == "basic"
    assert capabilities["sources"]["stocks"]["available"] is False
    response = client.post(
        path + "/sync",
        json={
            "sources": ["stocks", "sales", "finance"],
            "date_from": FINANCE_START.isoformat(),
            "date_to": now().date().isoformat(),
        },
    )
    assert response.status_code == 202
    runs = {run["source"]: run for run in response.json()}
    assert runs["stocks"]["error_code"] == "wb_token_type_unsupported"
    assert runs["stocks"]["status"] == "failed"
    assert runs["finance"]["date_from"] == FINANCE_START.isoformat()
    assert runs["sales"]["date_from"] == history_limits()[Source.SALES]["date_from"].isoformat()
    assert runs["sales"]["status"] == runs["finance"]["status"] == "queued"
    # Even a previously queued stock job is rejected before an external request.
    run_id, task_id = make_run(s, Source.STOCKS)
    assert not process(s, run_id, task_id, Page([], {}, True)).page.called


def test_atomic_publish_retries_and_duplicate_delivery(setup):
    s = setup
    run_id, task_id = make_run(s, Source.CATALOG)
    first = Page([{"nmID": 42, "title": "Old"}], {}, True)
    process(s, run_id, task_id, first)
    assert len(records(s)) == 1
    assert not process(s, run_id, task_id, first).page.called
    newer, next_id = make_run(s, Source.CATALOG)
    process(s, newer, next_id, Page([{"nmID": 43, "title": "New"}], {"nmID": 43}, False))
    assert records(s)[0].record_key == "42"
    process(s, newer, requeue(s, newer), error=WBError("wb_unavailable", retryable=True))
    assert records(s)[0].record_key == "42"
    with Session(s.engine) as db:
        set_actor(db, s.user_id)
        pending = db.get(SyncRun, newer)
        assert pending.cursor == {"nmID": 43} and pending.attempts == 1
    process(s, newer, requeue(s, newer), Page([], {"nmID": 43}, True))
    assert [r.record_key for r in records(s)] == ["43"]
    with Session(s.engine) as db:
        set_actor(db, s.user_id)
        assert (
            db.scalar(
                select(func.count())
                .select_from(WBStagedRecord)
                .where(WBStagedRecord.run_id == newer)
            )
            == 0
        )


def test_sales_upsert_preserves_other_days_and_does_not_duplicate(setup):
    s = setup
    row = {
        "saleID": "S1",
        "nmId": 42,
        "date": "2026-10-01",
        "lastChangeDate": "2026-10-01",
        "forPay": "12.34",
    }
    for value in ("12.34", "15.67"):
        run_id, task_id = make_run(s, Source.SALES)
        process(s, run_id, task_id, Page([{**row, "forPay": value}], {}, True))
    saved = records(s)
    assert len(saved) == 1
    assert "15.67" not in saved[0].ciphertext
    plain = s.vault.open(
        saved[0].ciphertext, context(s.workspace_id, s.store_id, Source.SALES, "S1")
    )
    assert json.loads(plain)["for_pay"] == "15.67"


def test_batched_publication_rolls_back_all_batches_and_resumes(setup, monkeypatch):
    from app.modules.sync import service

    s = setup
    monkeypatch.setattr(service, "PUBLISH_BATCH_SIZE", 2)
    old_run, old_task = make_run(s, Source.CATALOG)
    process(s, old_run, old_task, Page([{"nmID": 42}], {}, True))
    run_id, task_id = make_run(s, Source.CATALOG)
    process(s, run_id, task_id, Page([{"nmID": value} for value in range(100, 105)], {}, False))
    inserts = []

    def fail_second_insert(connection, cursor, statement, parameters, context, executemany):
        if statement.startswith("INSERT INTO wb_records"):
            inserts.append(1)
            if len(inserts) == 2:
                raise RuntimeError("Synthetic mid-publication failure")

    event.listen(s.engine, "before_cursor_execute", fail_second_insert)
    try:
        with pytest.raises(RuntimeError, match="Synthetic mid-publication failure"):
            process(s, run_id, requeue(s, run_id), Page([], {}, True))
    finally:
        event.remove(s.engine, "before_cursor_execute", fail_second_insert)
    assert [row.record_key for row in records(s)] == ["42"]
    with Session(s.engine) as db:
        set_actor(db, s.user_id)
        assert db.scalar(select(func.count()).select_from(WBStagedRecord)) == 5
    process(s, run_id, requeue(s, run_id), Page([], {}, True))
    assert {row.record_key for row in records(s)} == {str(value) for value in range(100, 105)}


def test_failed_snapshot_keeps_previous_and_empty_success_clears_stocks(setup):
    s = setup
    row = {
        "nmId": 1,
        "chrtId": 2,
        "warehouseId": -999999,
        "warehouseName": "WB",
        "quantity": 5,
        "inWayToClient": 0,
        "inWayFromClient": 1,
    }
    run_id, task_id = make_run(s, Source.STOCKS)
    process(s, run_id, task_id, Page([row], {}, True))
    run_id, task_id = make_run(s, Source.STOCKS)
    process(s, run_id, task_id, error=WBError("wb_access_denied"))
    assert len(records(s)) == 1
    run_id, task_id = make_run(s, Source.STOCKS)
    process(s, run_id, task_id, Page([], {}, True))
    assert records(s) == []


def test_database_rls_hides_data_and_denies_cross_tenant_writes(setup):
    s = setup
    run_id, task_id = make_run(s, Source.CATALOG)
    process(s, run_id, task_id, Page([{"nmID": 42}], {}, True))
    with Session(s.engine) as db:
        set_actor(db, s.other_id)
        assert db.scalars(select(WBRecord).where(WBRecord.store_id == s.store_id)).all() == []
        with pytest.raises(ProgrammingError) as denied:
            db.add(
                WBRecord(
                    workspace_id=s.workspace_id,
                    store_id=s.store_id,
                    source="catalog",
                    record_key="99",
                    ciphertext="bad",
                    updated_at=now(),
                )
            )
            db.flush()
        assert denied.value.orig.sqlstate == "42501"


def test_duplicate_active_source_rejected_in_database(setup):
    s = setup
    make_run(s, Source.CATALOG)
    with pytest.raises(IntegrityError):
        make_run(s, Source.CATALOG)


def test_disconnect_before_execution_prevents_external_request(setup):
    s = setup
    run_id, task_id = make_run(s, Source.CATALOG)
    with Session(s.engine) as db, db.begin():
        set_actor(db, s.user_id)
        db.get(Store, s.store_id).connection_status = "disconnected"
    client = process(s, run_id, task_id, Page([], {}, True))
    assert not client.page.called
    with Session(s.engine) as db:
        set_actor(db, s.user_id)
        assert db.get(SyncRun, run_id).error_code == "store_not_connected"


def test_api_denies_foreign_workspace_and_viewer_start(setup):
    s = setup
    from app.db.session import get_db

    app = create_app(s.settings)
    user = User(id=s.other_id)
    identity = Identity(user, AuthSession())

    def test_db():
        with Session(s.engine, expire_on_commit=False) as db:
            set_actor(db, user.id)
            yield db

    app.dependency_overrides[get_db] = test_db
    app.dependency_overrides[full_identity] = lambda: identity
    with TestClient(app) as c:
        app.state.vault = s.vault
        path = f"/api/v1/workspaces/{s.workspace_id}/stores/{s.store_id}"
        assert c.get(path + "/data/catalog").status_code == 404
        assert c.post(path + "/sync", json={}).status_code == 404
        with Session(s.admin) as db, db.begin():
            db.add(Membership(user_id=s.other_id, workspace_id=s.workspace_id, role="viewer"))
        assert c.get(path + "/data/catalog").status_code == 200
        assert c.post(path + "/sync", json={}).status_code == 404
        user.id = s.user_id
        response = c.post(path + "/sync", json={"sources": ["catalog"]})
        assert response.status_code == 202
        assert c.post(path + "/sync", json={"sources": ["catalog"]}).status_code == 409
        assert c.get(path + "/sync-runs/" + response.json()[0]["id"]).status_code == 200
    app.dependency_overrides.clear()


def test_local_console_real_database_scope_and_import(setup, tmp_path):
    import secrets

    from app.devconsole.access import ConsoleSettings
    from app.devconsole.server import create_console

    s = setup
    grant_file = tmp_path / "dev-grant.json"
    token = "pd_" + secrets.token_urlsafe(32)
    grant = {
        "token": token,
        "user_id": str(s.user_id),
        "workspace_id": str(s.workspace_id),
        "store_id": str(s.store_id),
        "bootstrap_digest": "unused",
        "bootstrap_expires_at": 0,
    }
    grant_file.write_text(json.dumps(grant))
    settings = s.settings.model_dump()
    settings.update(app_env="local", dev_console_enabled=True, dev_grant_file=grant_file)
    app = create_console(ConsoleSettings(_env_file=None, **settings))
    run_id, task_id = make_run(s, Source.CATALOG)
    process(
        s, run_id, task_id, Page([{"nmID": 42, "title": "<script>text only</script>"}], {}, True)
    )
    with TestClient(
        app, base_url="http://127.0.0.1:8010", headers={"Authorization": "Bearer " + token}
    ) as c:
        app.state.vault = s.vault
        response = c.get("/api/v1/dev/summary")
        assert response.status_code == 200
        assert response.json()["sources"]["catalog"]["total"] == 1
        assert response.json()["stocks"] is None
        assert c.get("/api/v1/dev/data/catalog").json()["items"][0]["nm_id"] == "42"
        assert c.post("/api/v1/dev/sync", json={"sources": ["stocks"]}).status_code == 202
        assert c.post("/api/v1/dev/sync", json={"sources": ["stocks"]}).status_code == 409
        grant["store_id"] = str(uuid4())
        grant_file.write_text(json.dumps(grant))
        assert c.get("/api/v1/dev/summary").status_code == 403
        grant["store_id"] = str(s.store_id)
        grant_file.write_text(json.dumps(grant))
        with Session(s.admin) as db, db.begin():
            db.get(Membership, (s.user_id, s.workspace_id)).role = "viewer"
        assert c.get("/api/v1/dev/data/catalog").status_code == 403


def test_analytics_preview_duplicate_page_publication_and_changed_event(setup, owner_client):
    s = setup
    c, path = owner_client
    yesterday = now().date() - timedelta(days=1)
    row = {
        "saleID": "S1",
        "nmId": 42,
        "date": yesterday.isoformat(),
        "lastChangeDate": yesterday.isoformat(),
        "finishedPrice": "12.34",
    }
    run_id, task_id = make_run(s, Source.SALES)
    process(s, run_id, task_id, Page([row], {"last_change": row["date"]}, False))
    endpoint = path + f"/analytics?date_from={yesterday}&date_to={yesterday}"
    result = c.get(endpoint).json()
    assert result["sales"]["sales"] == 1 and result["sales"]["net_amount"] == "12.34"
    assert result["partial_sources"] == ["sales"] and not result["period_complete"]["sales"]
    process(s, run_id, requeue(s, run_id), Page([row], {}, False))
    assert c.get(endpoint).json()["sales"]["sales"] == 1
    process(s, run_id, requeue(s, run_id), Page([], {}, True))
    result = c.get(endpoint).json()
    assert result["sales"]["sales"] == 1 and result["period_complete"]["sales"]
    assert result["partial_sources"] == []
    newer, next_id = make_run(s, Source.SALES)
    changed = {**row, "date": (yesterday - timedelta(days=1)).isoformat(), "finishedPrice": "15.67"}
    process(s, newer, next_id, Page([changed], {}, False))
    assert (
        c.get(endpoint).json()["sales"]["net_amount"] == "12.34"
    )  # Previous full data stays visible.
    process(s, newer, requeue(s, newer), Page([], {}, True))
    assert c.get(endpoint).json()["sales"]["sales"] == 0
    other_day = c.get(
        path + f"/analytics?date_from={changed['date']}&date_to={changed['date']}"
    ).json()
    assert other_day["sales"]["sales"] == 1 and other_day["sales"]["net_amount"] == "15.67"


def test_failed_preview_discarded_and_finance_currencies_separate(setup, owner_client):
    s = setup
    c, path = owner_client
    day = (now().date() - timedelta(days=1)).isoformat()
    run_id, task_id = make_run(s, Source.SALES)
    process(
        s,
        run_id,
        task_id,
        Page(
            [
                {
                    "saleID": "R1",
                    "nmId": 42,
                    "date": day,
                    "lastChangeDate": day,
                    "finishedPrice": "2.34",
                }
            ],
            {},
            False,
        ),
    )
    process(s, run_id, requeue(s, run_id), error=WBError("wb_access_denied"))
    result = c.get(path + f"/analytics?date_from={day}&date_to={day}").json()
    assert not result["available"]["sales"] and result["sales"]["returns"] == 0
    row = {
        "rrdId": 1,
        "reportId": 3,
        "nmId": 42,
        "quantity": 1,
        "rrDate": day,
        "currency": "RUB",
        "docTypeName": "Продажа",
        "forPay": "10.01",
    }
    run_id, task_id = make_run(s, Source.FINANCE)
    process(
        s,
        run_id,
        task_id,
        Page(
            [
                row,
                {**row, "rrdId": 2, "docTypeName": "Возврат", "forPay": "1.23"},
                {**row, "rrdId": 3, "currency": "KZT", "forPay": "2.00"},
            ],
            {},
            True,
        ),
    )
    result = c.get(path + f"/analytics?date_from={day}&date_to={day}").json()
    assert {v["currency"]: v["for_pay"] for v in result["finance"]} == {
        "RUB": "8.78",
        "KZT": "2.00",
    }


def test_plan_resume_disable_keeps_active_run_and_success_advances_history(setup, owner_client):
    from app.modules.sync.models import SyncSchedule

    s = setup
    c, path = owner_client
    response = c.put(path + "/sync-schedule", json={"sources": ["sales", "finance"]})
    assert response.status_code == 200
    with Session(s.engine) as db:
        set_actor(db, s.user_id)
        runs = db.scalars(select(SyncRun).where(SyncRun.store_id == s.store_id)).all()
        assert len(runs) == 2 and all(run.sync_mode == "recent" for run in runs)
        assert all((run.date_to - run.date_from).days == 29 for run in runs)
        saved_ids = {run.id for run in runs}
    assert c.put(path + "/sync-schedule", json={"enabled": False}).status_code == 200
    assert all(not p["enabled"] for p in c.get(path + "/sync-schedule").json())
    with Session(s.engine) as db:
        set_actor(db, s.user_id)
        assert {
            r.id for r in db.scalars(select(SyncRun).where(SyncRun.store_id == s.store_id))
        } == saved_ids
    assert c.put(path + "/sync-schedule", json={"sources": ["sales", "finance"]}).status_code == 200
    with Session(s.engine) as db, db.begin():
        set_actor(db, s.user_id)
        run = db.scalar(
            select(SyncRun).where(SyncRun.store_id == s.store_id, SyncRun.source == "sales")
        )
        run.task_id = str(uuid4())
        run_id, task_id = run.id, run.task_id
    process(s, run_id, task_id, Page([], {}, True))
    with Session(s.engine) as db:
        set_actor(db, s.user_id)
        plan = db.get(SyncSchedule, (s.workspace_id, s.store_id, "sales"))
        assert plan.recent_completed and plan.history_turn and plan.sales_cursor


def test_metrics_and_schedule_rls_hide_foreign_tenant(setup, owner_client):
    from app.modules.sync.models import SyncSchedule, WBDailyMetric, WBMetricVersion

    s = setup
    c, path = owner_client
    c.put(path + "/sync-schedule", json={"sources": ["sales"]})
    with Session(s.engine) as db:
        set_actor(db, s.other_id)
        for model in (SyncSchedule, WBDailyMetric, WBMetricVersion):
            assert db.scalars(select(model).where(model.store_id == s.store_id)).all() == []
        with pytest.raises(ProgrammingError) as denied:
            db.add(
                WBMetricVersion(
                    workspace_id=s.workspace_id,
                    store_id=s.store_id,
                    version=uuid4(),
                    updated_at=now(),
                )
            )
            db.flush()
        assert denied.value.orig.sqlstate == "42501"


def test_delta_refresh_does_not_claim_missing_history_is_complete(setup, owner_client):
    s = setup
    c, path = owner_client
    run_id, task_id = make_run(s, Source.SALES)
    with Session(s.engine) as db, db.begin():
        set_actor(db, s.user_id)
        run = db.get(SyncRun, run_id)
        run.sync_mode = "incremental"
        run.date_from = history_limits()[Source.SALES]["date_from"]
    process(s, run_id, task_id, Page([], {}, True))
    result = c.get(path + "/analytics").json()
    assert result["coverage"]["sales"] == [] and not result["period_complete"]["sales"]


def test_revoked_owner_does_not_fetch_or_enqueue_and_task_terminates(setup, owner_client):
    from app.modules.sync.planner import schedule_due

    s = setup
    c, path = owner_client
    assert c.put(path + "/sync-schedule", json={"sources": ["sales"]}).status_code == 200
    with Session(s.admin) as db, db.begin():
        db.get(Membership, (s.user_id, s.workspace_id)).role = "viewer"
        run = db.scalar(
            select(SyncRun).where(SyncRun.store_id == s.store_id, SyncRun.source == "sales")
        )
        run.task_id = str(uuid4())
        run_id, task_id = run.id, run.task_id
    assert not process(s, run_id, task_id, Page([], {}, True)).page.called
    schedule_due(s.engine, s.vault, s.settings)
    with Session(s.engine) as db:
        set_actor(db, s.user_id)
        assert db.get(SyncRun, run_id).status == "failed"
        assert (
            db.scalar(
                select(func.count()).select_from(SyncRun).where(SyncRun.store_id == s.store_id)
            )
            == 2  # History-enabled sales also schedules reports; revoked owner adds no jobs.
        )
    assert c.put(path + "/sync-schedule", json={"sources": ["finance"]}).status_code == 404


def test_reads_do_not_wait_for_import_store_lock(setup, owner_client):
    from app.db.session import get_db

    s = setup
    client, path = owner_client

    def bounded_db():
        with Session(s.engine, expire_on_commit=False) as db:
            set_actor(db, s.user_id)
            db.execute(text("SET LOCAL statement_timeout = '1000ms'"))
            yield db

    client.app.dependency_overrides[get_db] = bounded_db
    with Session(s.engine) as writer, writer.begin():
        set_actor(writer, s.user_id)
        writer.scalar(select(Store).where(Store.id == s.store_id).with_for_update())
        assert client.get(path + "/analytics").status_code == 200
        assert client.get(path + "/data/finance").status_code == 200


def test_publication_during_analytics_read_retries_revision(setup, owner_client, monkeypatch):
    from app.modules.sync import analytics

    s = setup
    client, path = owner_client
    day = (now().date() - timedelta(days=1)).isoformat()
    row = {"saleID": "S1", "nmId": 42, "date": day, "lastChangeDate": day, "finishedPrice": "10.00"}
    run_id, task_id = make_run(s, Source.SALES)
    process(s, run_id, task_id, Page([row], {}, True))
    refresh_id, refresh_task = make_run(s, Source.SALES)
    original, calls = analytics.calculate, []

    def publish_during_read(*args, **kwargs):
        result = original(*args, **kwargs)
        calls.append(1)
        if len(calls) == 1:
            process(
                s, refresh_id, refresh_task, Page([{**row, "finishedPrice": "20.00"}], {}, True)
            )
        return result

    monkeypatch.setattr(analytics, "calculate", publish_during_read)
    response = client.get(path + f"/analytics?date_from={day}&date_to={day}")
    assert response.status_code == 200
    assert response.json()["sales"]["net_amount"] == "20.00"
    assert response.json()["snapshot_stable"] is True and len(calls) == 2


def test_widening_recent_period_requires_complete_month(setup, owner_client):
    s = setup
    client, path = owner_client
    assert (
        client.put(
            path + "/sync-schedule", json={"sources": ["sales"], "recent_days": 7}
        ).status_code
        == 200
    )
    with Session(s.engine) as db, db.begin():
        set_actor(db, s.user_id)
        run = db.scalar(
            select(SyncRun).where(SyncRun.store_id == s.store_id, SyncRun.source == "sales")
        )
        run.task_id = str(uuid4())
        run_id, task_id = run.id, run.task_id
    process(s, run_id, task_id, Page([], {}, True))
    response = client.put(path + "/sync-schedule", json={"sources": ["sales"], "recent_days": 30})
    assert response.status_code == 200
    assert not response.json()[0]["recent_completed"]
    with Session(s.engine) as db:
        set_actor(db, s.user_id)
        pending = db.scalar(
            select(SyncRun).where(
                SyncRun.store_id == s.store_id,
                SyncRun.source == "sales",
                SyncRun.status == "queued",
            )
        )
        assert pending and (pending.date_to - pending.date_from).days == 29


def test_targeted_cache_warm_requires_current_mfa_owner(setup, monkeypatch):
    from app.workers import tasks

    s = setup
    warm = Mock()
    monkeypatch.setattr(tasks, "get_settings", lambda: s.settings)
    monkeypatch.setattr(tasks, "build_engine", lambda settings: s.engine)
    monkeypatch.setattr(tasks.Redis, "from_url", lambda *args, **kwargs: s.redis)
    monkeypatch.setattr(tasks, "SecretVault", lambda path: s.vault)
    monkeypatch.setattr(tasks, "warm_store", warm)
    monkeypatch.setattr(tasks.finance_jobs, "enqueue", Mock())
    tasks.warm_store_analytics(str(s.workspace_id), str(s.store_id), str(s.other_id))
    warm.assert_not_called()
    tasks.warm_store_analytics(str(s.workspace_id), str(s.store_id), str(s.user_id))
    assert warm.call_count == 1
    assert warm.call_args.args[-2:] == (s.workspace_id, s.store_id)
    with Session(s.admin) as db, db.begin():
        db.get(User, s.user_id).email_verified_at = None
    tasks.warm_store_analytics(str(s.workspace_id), str(s.store_id), str(s.user_id))
    assert warm.call_count == 1


def test_year_sales_use_financial_reports_without_double_counting(setup, owner_client):
    s = setup
    client, path = owner_client
    end = now().date() - timedelta(days=1)
    start = end - timedelta(days=729)
    historical_day = end - timedelta(days=500)
    row = {
        "rrdId": 1,
        "reportId": 1,
        "nmId": 42,
        "quantity": 2,
        "rrDate": str(historical_day),
        "currency": "RUB",
        "docTypeName": "Продажа",
        "sellerOperName": "Продажа",
        "retailAmount": "100.00",
        "forPay": "80.00",
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
                {**row, "rrdId": 2, "rrDate": str(end), "quantity": 1},
                {
                    **row,
                    "rrdId": 3,
                    "quantity": 1,
                    "docTypeName": "Возврат",
                    "sellerOperName": "Возврат",
                    "retailAmount": "40.00",
                },
                {**row, "rrdId": 4, "quantity": 2, "sellerOperName": "Логистика"},
                {**row, "rrdId": 5, "sellerOperName": "Коррекция продаж"},
                {**row, "rrdId": 6, "currency": "KZT", "retailAmount": "200.00"},
                {**row, "rrdId": 7, "docTypeName": "Возврат"},
            ],
            {},
            True,
        ),
    )
    sales_id, sales_task = make_run(s, Source.SALES)
    process(
        s,
        sales_id,
        sales_task,
        Page(
            [
                {
                    "saleID": "S-recent",
                    "nmId": 42,
                    "date": str(end),
                    "lastChangeDate": str(end),
                    "finishedPrice": "100.00",
                }
            ],
            {},
            True,
        ),
    )
    url = path + f"/analytics?date_from={start}&date_to={end}"
    result = client.get(url).json()
    assert result["sales_basis"] == "reports" and result["sales_date_basis"] == "report_date"
    assert result["period_complete"]["sales"] and not result["period_complete"]["operational_sales"]
    assert result["sales"]["sales"] == 5 and result["sales"]["returns"] == 1
    assert result["sales"]["net_amount"] is None
    assert sum(day["sales"] for day in result["daily"]) == 5
    assert result["abc"][0]["net_units"] == 4
    assert {v["currency"]: v["net_amount"] for v in result["sales_money"]} == {
        "RUB": "160.00",
        "KZT": "200.00",
    }
    assert result["sales_quality"]["correction_records"] == 1
    assert result["sales_quality"]["invalid_records"] == 1
    recent = client.get(path + f"/analytics?date_from={end}&date_to={end}").json()
    assert recent["sales_basis"] == "operational" and recent["sales"]["sales"] == 1
    assert client.get(url + "&sales_basis=operational").json()["sales"]["sales"] == 1
    assert client.get(url + "&sales_basis=invalid").status_code == 422
    empty = client.get(
        path + f"/analytics?date_from={start}&date_to={start}&sales_basis=reports"
    ).json()
    assert empty["sales"]["sales"] == 0 and empty["period_complete"]["sales"]


def test_old_report_metrics_upgrade_is_atomic_and_idempotent(setup, owner_client, monkeypatch):
    from app.modules.sync import analytics
    from app.modules.sync.models import WBDailyMetric, WBMetricVersion

    s = setup
    client, path = owner_client
    day = str(now().date() - timedelta(days=1))
    row = {
        "rrdId": 1,
        "reportId": 1,
        "nmId": 42,
        "quantity": 3,
        "rrDate": day,
        "currency": "RUB",
        "docTypeName": "Продажа",
        "sellerOperName": "Продажа",
        "forPay": "10.00",
    }
    run_id, task_id = make_run(s, Source.FINANCE)
    process(s, run_id, task_id, Page([row], {}, True))
    with Session(s.engine) as db, db.begin():
        set_actor(db, s.user_id)
        version = db.get(WBMetricVersion, (s.workspace_id, s.store_id))
        version.format_version = 1
        old_version = version.version
        metric = db.scalar(select(WBDailyMetric).where(WBDailyMetric.source == "finance"))
        aad = analytics.metric_context(
            metric.workspace_id,
            metric.store_id,
            metric.source,
            metric.dataset,
            metric.day,
            metric.nm_id,
            metric.currency,
        )
        values = json.loads(s.vault.open(metric.ciphertext, aad))
        metric.ciphertext = s.vault.seal(
            json.dumps({k: v for k, v in values.items() if not k.startswith("report_")}), aad
        )
    original = analytics.apply_deltas
    monkeypatch.setattr(
        analytics, "apply_deltas", Mock(side_effect=RuntimeError("Synthetic upgrade failure"))
    )
    with pytest.raises(RuntimeError):
        with Session(s.engine) as db, db.begin():
            set_actor(db, s.user_id)
            db.scalar(select(Store).where(Store.id == s.store_id).with_for_update())
            analytics.rebuild_store(db, s.vault, s.workspace_id, s.store_id)
    monkeypatch.setattr(analytics, "apply_deltas", original)
    not_ready = client.get(
        path + f"/analytics?date_from={day}&date_to={day}&sales_basis=reports"
    ).json()
    assert not not_ready["sales_metrics_ready"] and not not_ready["period_complete"]["sales"]
    with Session(s.engine) as db, db.begin():
        set_actor(db, s.user_id)
        assert db.get(WBMetricVersion, (s.workspace_id, s.store_id)).version == old_version
        assert db.scalar(select(func.count()).select_from(WBDailyMetric)) == 1
        analytics.rebuild_store(db, s.vault, s.workspace_id, s.store_id)
        assert db.get(WBMetricVersion, (s.workspace_id, s.store_id)).version != old_version
        upgraded = db.get(WBMetricVersion, (s.workspace_id, s.store_id)).version
        analytics.rebuild_store(db, s.vault, s.workspace_id, s.store_id)
        assert db.get(WBMetricVersion, (s.workspace_id, s.store_id)).version == upgraded
    ready = client.get(
        path + f"/analytics?date_from={day}&date_to={day}&sales_basis=reports"
    ).json()
    assert ready["sales_metrics_ready"] and ready["sales"]["sales"] == 3
    assert ready["finance"][0]["for_pay"] == "10.00"


def test_historical_sales_request_routes_to_reports(setup, owner_client):
    client, path = owner_client
    end = now().date() - timedelta(days=365)
    response = client.post(
        path + "/sync",
        json={"sources": ["sales"], "date_from": str(FINANCE_START), "date_to": str(end)},
    )
    assert response.status_code == 202
    assert [(v["source"], v["date_from"], v["date_to"]) for v in response.json()] == [
        ("finance", str(FINANCE_START), str(end))
    ]


def test_financial_fields_upgrade_without_duplicates_and_failed_refresh_preserves_expenses(
    setup, owner_client
):
    s = setup
    client, path = owner_client
    row = {
        "rrdId": 1,
        "reportId": 2,
        "nmId": 0,
        "docTypeName": "Продажа",
        "sellerOperName": "Коррекция логистики",
        "quantity": 0,
        "rrDate": "2026-10-01",
        "currency": "RUB",
        "retailAmount": "0",
        "forPay": "0",
        "acquiringFee": "0",
    }
    run_id, task_id = make_run(s, Source.FINANCE)
    process(s, run_id, task_id, Page([row], {}, True))
    # Model an already published row from the earlier limited projection.
    legacy_keys = {
        "rrd_id",
        "report_id",
        "nm_id",
        "document_type",
        "operation",
        "quantity",
        "report_date",
        "currency",
        "retail_amount",
        "for_pay",
        "acquiring_fee",
    }
    aad = context(s.workspace_id, s.store_id, Source.FINANCE, "1")
    with Session(s.engine) as db, db.begin():
        set_actor(db, s.user_id)
        saved = db.scalar(select(WBRecord).where(WBRecord.store_id == s.store_id))
        value = json.loads(s.vault.open(saved.ciphertext, aad))
        saved.ciphertext = s.vault.seal(json.dumps({key: value[key] for key in legacy_keys}), aad)
    legacy = client.get(path + "/data/finance").json()["items"][0]
    assert legacy["data_version"] == 1 and legacy["paid_storage"] is None
    assert not legacy["requested_amounts_complete"]

    for amount in ("17.34", "-2.34001"):
        run_id, task_id = make_run(s, Source.FINANCE)
        process(s, run_id, task_id, Page([{**row, "paidStorage": amount}], {}, True))
    response = client.get(path + "/data/finance").json()
    assert response["total"] == 1
    assert response["items"][0]["data_version"] == 3
    assert response["items"][0]["paid_storage"] == "-2.34001"
    assert response["items"][0]["nm_id"] == "0"
    assert "-2.34001" not in records(s)[0].ciphertext

    run_id, task_id = make_run(s, Source.FINANCE)
    process(s, run_id, task_id, Page([{**row, "paidStorage": "NaN"}], {}, True))
    failed = client.get(path + "/data/finance").json()
    assert failed["latest_run"]["status"] == "failed"
    assert failed["latest_run"]["error_code"] == "wb_invalid_record"
    assert failed["total"] == 1
    assert failed["items"][0]["paid_storage"] == "-2.34001"

    with Session(s.engine) as db:
        set_actor(db, s.other_id)
        assert db.scalar(select(WBRecord).where(WBRecord.store_id == s.store_id)) is None


def import_catalog_for_costs(s):
    run_id, task_id = make_run(s, Source.CATALOG)
    process(
        s,
        run_id,
        task_id,
        Page(
            [
                {
                    "nmID": 42,
                    "title": "Synthetic item",
                    "vendorCode": "A42",
                    "sizes": [{"chrtID": 1, "techSize": "M", "skus": ["0001", "0002"]}],
                }
            ],
            {},
            True,
        ),
    )


def preview_cost_file(client, path, rows):
    from cost_workbook import legacy_cost_workbook as cost_workbook

    return client.post(
        path + "/cost-imports",
        files={
            "file": (
                "costs.xlsx",
                cost_workbook(rows),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )


def test_cost_import_history_variants_idempotency_and_missing_cost(setup, owner_client):
    from app.modules.finance.models import ProductCost

    s = setup
    client, path = owner_client
    import_catalog_for_costs(s)
    template = client.get(path + "/costs/template")
    assert template.status_code == 200 and template.content.startswith(b"PK")
    rows = [
        ["42", "", "100.00", "2026-01-01", "RUB"],
        ["42", "", "130.00", "2026-09-01", "RUB"],
        ["42", "0001", "90.25", "2026-01-01", "RUB"],
    ]
    response = preview_cost_file(client, path, rows)
    assert response.status_code == 200
    preview = response.json()
    assert preview["can_apply"] and preview["valid_count"] == 3
    assert client.get(path + "/costs").json() == []
    apply_path = path + f"/cost-imports/{preview['preview_id']}/apply"
    result = client.post(apply_path)
    assert result.status_code == 200 and result.json()["inserted"] == 3
    assert client.post(apply_path).json() == result.json()
    assert len(client.get(path + "/costs").json()) == 3
    reimport = preview_cost_file(client, path, rows).json()
    repeated = client.post(path + f"/cost-imports/{reimport['preview_id']}/apply").json()
    assert repeated["inserted"] == 0 and repeated["unchanged"] == 3
    calculated = client.get(
        path + "/costs/calculate",
        params={
            "nm_id": "42",
            "at": "2026-02-01",
            "quantity": 3,
        },
    ).json()
    assert calculated["unit_cost"] == "100.00" and calculated["total_cost"] == "300.00"
    assert calculated["matched_by"] == "article"
    variant = client.get(
        path + "/costs/calculate",
        params={
            "nm_id": "42",
            "barcode": "0001",
            "at": "2026-10-01",
        },
    ).json()
    assert variant["unit_cost"] == "90.25" and variant["matched_by"] == "barcode"
    fallback = client.get(
        path + "/costs/calculate",
        params={
            "nm_id": "42",
            "barcode": "0002",
            "at": "2026-10-01",
        },
    ).json()
    assert fallback["unit_cost"] == "130.00" and fallback["matched_by"] == "article"
    missing = client.get(
        path + "/costs/calculate",
        params={
            "nm_id": "42",
            "at": "2025-12-01",
        },
    ).json()
    assert not missing["available"] and missing["total_cost"] is None
    with Session(s.engine) as db:
        set_actor(db, s.user_id)
        quotes = db.scalars(select(ProductCost)).all()
        assert len(quotes) == 3
        assert all("100.00" not in item.ciphertext for item in quotes)
        set_actor(db, s.other_id)
        assert db.scalars(select(ProductCost)).all() == []


def test_invalid_cost_rows_never_apply_partially_and_existing_prices_are_immutable(
    setup, owner_client
):
    from app.modules.finance.models import ProductCost

    s = setup
    client, path = owner_client
    import_catalog_for_costs(s)
    invalid = preview_cost_file(
        client,
        path,
        [
            ["42", "", "100", "2026-01-01", "RUB"],
            ["99", "", "100", "2026-01-01", "RUB"],
            ["42", "999", "100", "2026-01-01", "RUB"],
            ["42", "", "110", "2026-01-01", "RUB"],
        ],
    ).json()
    assert not invalid["can_apply"] and invalid["preview_id"] is None
    assert {e["code"] for e in invalid["errors"]} == {
        "unknown_product",
        "unknown_barcode",
        "duplicate_price",
    }
    assert client.get(path + "/costs").json() == []
    rows = [["42", "", "100", "2026-01-01", "RUB"]]
    first = preview_cost_file(client, path, rows).json()["preview_id"]
    second = preview_cost_file(client, path, [["42", "", "110", "2026-01-01", "RUB"]]).json()
    assert client.post(path + f"/cost-imports/{first}/apply").status_code == 200
    assert client.post(path + f"/cost-imports/{second['preview_id']}/apply").status_code == 409
    conflict = preview_cost_file(client, path, [["42", "", "110", "2026-01-01", "RUB"]]).json()
    assert conflict["errors"][0]["code"] == "price_conflict"
    with Session(s.engine) as db, db.begin():
        set_actor(db, s.user_id)
        from sqlalchemy import update

        changed = db.execute(update(ProductCost).values(ciphertext="tampered"))
        assert changed.rowcount == 0  # FORCE RLS gives even the owner no UPDATE policy.
    assert client.get(path + "/costs").json()[0]["amount"] == "100"


def test_cost_preview_expiry_and_catalog_change_are_rechecked(setup, owner_client):
    from app.modules.finance.models import CostImport

    s = setup
    client, path = owner_client
    import_catalog_for_costs(s)
    preview = preview_cost_file(client, path, [["42", "", "1", "2026-01-01", ""]]).json()
    with Session(s.admin) as db, db.begin():
        row = db.get(CostImport, (s.workspace_id, s.store_id, UUID(preview["preview_id"])))
        row.expires_at = now() - timedelta(seconds=1)
    assert client.post(path + f"/cost-imports/{preview['preview_id']}/apply").status_code == 410
    preview = preview_cost_file(client, path, [["42", "", "1", "2026-01-01", ""]]).json()
    run_id, task_id = make_run(s, Source.CATALOG)
    process(s, run_id, task_id, Page([], {}, True))
    assert client.post(path + f"/cost-imports/{preview['preview_id']}/apply").status_code == 409
    assert client.get(path + "/costs").json() == []


def test_cost_apply_failure_rolls_back_prices_and_preview_result(setup, owner_client):
    s = setup
    client, path = owner_client
    import_catalog_for_costs(s)
    preview = preview_cost_file(client, path, [["42", "", "1", "2026-01-01", ""]]).json()
    apply_path = path + f"/cost-imports/{preview['preview_id']}/apply"

    def fail_cost_write(connection, cursor, statement, parameters, context, executemany):
        if statement.startswith("INSERT INTO product_costs"):
            raise RuntimeError("Synthetic failure")

    event.listen(s.engine, "before_cursor_execute", fail_cost_write)
    try:
        assert client.post(apply_path).status_code == 500
    finally:
        event.remove(s.engine, "before_cursor_execute", fail_cost_write)
    assert client.get(path + "/costs").json() == []
    assert client.post(apply_path).json()["inserted"] == 1


def test_external_expenses_idempotency_currency_separation_and_soft_delete(setup, owner_client):
    from app.modules.finance.models import ExternalExpense

    s = setup
    client, path = owner_client
    key = str(uuid4())
    data = {"request_id": key, "expense_date": "2026-10-01", "amount": "1.00", "comment": "Rent"}
    first = client.post(path + "/expenses", json=data)
    assert first.status_code == 201
    assert first.json()["currency"] == "RUB"
    assert client.post(path + "/expenses", json={**data, "amount": "1.0"}).json()["id"] == key
    assert client.post(path + "/expenses", json={**data, "amount": "3"}).status_code == 409
    for amount, currency, day in [
        ("2.20", "RUB", "2026-10-02"),
        ("5", "USD", "2026-10-02"),
        ("7", "RUB", "2026-09-01"),
    ]:
        assert (
            client.post(
                path + "/expenses",
                json={
                    "expense_date": day,
                    "amount": amount,
                    "currency": currency,
                    "comment": "Packaging",
                },
            ).status_code
            == 201
        )
    params = {"date_from": "2026-10-01", "date_to": "2026-10-31"}
    totals = client.get(path + "/expenses/totals", params=params).json()
    assert totals["allocation"] == "store_only"
    assert totals["totals"] == [
        {"currency": "RUB", "amount": "3.20", "count": 2},
        {"currency": "USD", "amount": "5", "count": 1},
    ]
    assert client.delete(path + f"/expenses/{key}").status_code == 204
    assert client.delete(path + f"/expenses/{key}").status_code == 204
    assert (
        client.get(path + "/expenses/totals", params=params).json()["totals"][0]["amount"] == "2.20"
    )
    with Session(s.engine) as db:
        set_actor(db, s.user_id)
        records = db.scalars(select(ExternalExpense)).all()
        assert len(records) == 4 and all("Rent" not in r.ciphertext for r in records)
        set_actor(db, s.other_id)
        assert db.scalars(select(ExternalExpense)).all() == []


def test_cost_upload_limits_do_not_expand_other_api_bodies(setup, owner_client):
    client, path = owner_client
    upload = client.post(
        path + "/cost-imports", files={"file": ("large.xlsx", b"x" * (321 * 1024))}
    )
    assert upload.status_code == 413
    ordinary = client.post(
        path + "/expenses", content=b"x" * 70000, headers={"Content-Type": "application/json"}
    )
    assert ordinary.status_code == 413
    # Files larger than ordinary JSON are allowed through only the upload route,
    # then rejected by the workbook reader without parsing arbitrary content.
    invalid = client.post(path + "/cost-imports", files={"file": ("invalid.xlsx", b"x" * 70000)})
    assert invalid.status_code == 422


def test_cost_and_expense_routes_require_mfa_and_owner_writes(setup, owner_client):
    from cost_workbook import legacy_cost_workbook as cost_workbook

    from app.modules.auth.dependencies import current_identity

    s = setup
    client, path = owner_client
    preview_id, expense_id = uuid4(), uuid4()
    cases = [
        (
            "GET",
            "/finance/summary",
            {"params": {"date_from": "2026-01-01", "date_to": "2026-10-01"}},
        ),
        ("GET", "/finance/abc", {"params": {"date_from": "2026-01-01", "date_to": "2026-10-01"}}),
        ("GET", "/costs/template", {}),
        ("POST", "/cost-imports", {"files": {"file": ("costs.xlsx", cost_workbook())}}),
        ("POST", f"/cost-imports/{preview_id}/apply", {}),
        ("GET", "/costs", {}),
        ("GET", "/costs/calculate", {"params": {"nm_id": "42", "at": "2026-10-01"}}),
        (
            "POST",
            "/expenses",
            {"json": {"expense_date": "2026-10-01", "amount": "1", "comment": "Rent"}},
        ),
        ("GET", "/expenses", {}),
        (
            "GET",
            "/expenses/totals",
            {"params": {"date_from": "2026-01-01", "date_to": "2026-10-01"}},
        ),
        ("DELETE", f"/expenses/{expense_id}", {}),
    ]
    del client.app.dependency_overrides[full_identity]
    for method, suffix, kwargs in cases:
        assert client.request(method, path + suffix, **kwargs).status_code == 401

    identity = Identity(User(id=s.user_id), AuthSession())
    client.app.dependency_overrides[current_identity] = lambda: identity
    for method, suffix, kwargs in cases:
        assert client.request(method, path + suffix, **kwargs).status_code == 403

    identity.user.email_verified_at = now()
    identity.session.mfa_verified_at = now()
    with Session(s.admin) as db, db.begin():
        db.get(Membership, (s.user_id, s.workspace_id)).role = "viewer"
    for method, suffix, kwargs in cases:
        may_read = method == "GET" and suffix != "/costs/template"
        assert client.request(method, path + suffix, **kwargs).status_code == (
            200 if may_read else 403
        )
    other_store = f"/api/v1/workspaces/{s.workspace_id}/stores/{uuid4()}/costs"
    other_workspace = f"/api/v1/workspaces/{uuid4()}/stores/{s.store_id}/costs"
    assert client.get(other_store).status_code == 404
    assert client.get(other_workspace).status_code == 404


def raw_finance(row, key):
    from app.modules.finance.fields import AMOUNT_FIELDS

    return {
        "rrdId": key,
        "reportId": 2,
        "nmId": int(row["nm_id"]),
        "docTypeName": row["document_type"],
        "sellerOperName": row["operation"],
        "quantity": row["quantity"],
        "rrDate": row["report_date"],
        "currency": row["currency"],
        "sku": row.get("barcode"),
        "saleDt": row.get("sale_date"),
        "srid": row.get("sale_reference"),
        "bonusTypeName": row.get("bonus_type_name"),
        **{wb: row.get(field) for field, wb in AMOUNT_FIELDS.items()},
    }


def import_profit_facts(s, rows):
    from datetime import date

    run_id, task_id = make_run(s, Source.FINANCE)
    raw = [raw_finance(row, index) for index, row in enumerate(rows, 1)]
    process(s, run_id, task_id, Page(raw, {}, True))
    with Session(s.admin) as db, db.begin():
        run = db.get(SyncRun, run_id)
        run.date_from, run.date_to = date(2026, 1, 1), date(2026, 10, 7)
    return run_id


def prepare_profit(s):
    from app.modules.finance.projection import prepare

    with Session(s.engine) as db, db.begin():
        set_actor(db, s.user_id)
        db.scalar(select(Store).where(Store.id == s.store_id).with_for_update())
        return prepare(db, s.vault, s.workspace_id, s.store_id)


def test_profit_api_restores_original_cost_and_invalidates_cost_expense_cache(
    setup, owner_client, monkeypatch
):
    from test_profit_rules import finance_row

    from app.modules.finance import jobs
    from app.modules.finance.models import FinanceDay

    s = setup
    client, path = owner_client
    queue = Mock()
    monkeypatch.setattr(jobs, "enqueue", queue)
    import_catalog_for_costs(s)
    rows = [
        finance_row(sale_date="2026-01-01", report_date="2026-01-02", delivery_service="20"),
        finance_row(
            barcode="0002",
            sale_date="2026-10-01",
            report_date="2026-10-01",
            sale_reference="second-sale",
            retail_amount="300",
            for_pay="240",
            delivery_service="20",
        ),
        finance_row(
            document_type="Возврат",
            operation="Возврат",
            sale_date="2026-10-02",
            report_date="2026-10-02",
        ),
        finance_row(
            nm_id="0",
            barcode="",
            document_type="",
            operation="Хранение",
            quantity=0,
            retail_amount="0",
            for_pay="0",
            paid_storage="7",
        ),
    ]
    import_profit_facts(s, rows)
    params = {"date_from": "2026-10-01", "date_to": "2026-10-02"}
    assert client.get(path + "/finance/summary", params=params).json()["status"] == "preparing"
    queue.assert_called_once()
    assert prepare_profit(s) and not prepare_profit(s)
    memory = {}
    redis = Mock()
    redis.eval.return_value = 1
    redis.get.side_effect = memory.get

    def cache_set(key, value, **kwargs):
        memory[key] = value
        return True

    redis.set.side_effect = cache_set
    client.app.state.redis = redis
    missing = client.get(path + "/finance/summary", params=params).json()
    assert missing["summary"]["profit_before_tax"] is None
    assert missing["summary"]["issues"]["missing_cost_units"] == 2
    preview = preview_cost_file(
        client,
        path,
        [
            ["42", "", "100", "2025-01-01", "RUB"],
            ["42", "0001", "90", "2025-01-01", "RUB"],
            ["42", "", "130", "2026-09-01", "RUB"],
        ],
    ).json()
    assert client.post(path + f"/cost-imports/{preview['preview_id']}/apply").status_code == 200
    result = client.get(path + "/finance/summary", params=params).json()
    assert result["summary"]["profit_before_tax"] == "13"
    assert result["unassigned"]["wb_expenses"]["paid_storage"] == "7"
    assert result["unassigned"]["contribution_before_external_expenses"] == "-7"
    assert result["product_count"] == 1 and result["products"][0]["nm_id"] == "42"
    assert result["summary"]["cogs"] == "40" and result["period_covered"]
    assert result["return_cost_policy"] == "original_sale_assuming_resalable"
    expense = client.post(
        path + "/expenses", json={"expense_date": "2026-10-01", "amount": "10", "comment": "Rent"}
    ).json()
    result = client.get(path + "/finance/summary", params=params).json()
    assert result["summary"]["profit_before_tax"] == "3"
    assert result["products"][0]["contribution_before_external_expenses"] == "20"
    assert result["products"][0]["external_expenses"] == "0"
    assert sum(Decimal(row["profit_before_tax"]) for row in result["daily"]) == 3
    assert client.get(path + "/finance/summary", params=params).json() == result
    abc = client.get(path + "/finance/abc", params=params).json()
    assert abc["status"] == "ready" and abc["positive_total"] == "20"
    assert abc["items"][0]["group"] == "A"
    assert client.delete(path + f"/expenses/{expense['id']}").status_code == 204
    assert (
        client.get(path + "/finance/summary", params=params).json()["summary"]["profit_before_tax"]
        == "13"
    )
    # Reading published facts does not wait for a synchronizer holding the store lock.
    with Session(s.engine) as db, db.begin():
        set_actor(db, s.user_id)
        db.scalar(select(Store).where(Store.id == s.store_id).with_for_update())
        assert client.get(path + "/finance/summary", params=params).status_code == 200
    foreign_currency = client.get(
        path + "/finance/summary", params={**params, "currency": "USD"}
    ).json()
    assert foreign_currency["summary"]["profit_before_tax"] is None
    assert foreign_currency["summary"]["issues"]["unavailable_report_currency"] == 1
    from app.modules.finance import report as reports

    original_calculate, concurrent_expense = reports.calculate, []

    def changed_during_calculation(*args, **kwargs):
        value = original_calculate(*args, **kwargs)
        if not concurrent_expense:
            response = client.post(
                path + "/expenses",
                json={"expense_date": "2026-10-01", "amount": "4", "comment": "Concurrent"},
            )
            assert response.status_code == 201
            concurrent_expense.append(response.json()["id"])
        return value

    monkeypatch.setattr(reports, "calculate", changed_during_calculation)
    concurrent = client.get(
        path + "/finance/summary", params={**params, "date_from": "2026-09-30"}
    ).json()
    assert concurrent["summary"]["profit_before_tax"] == "9"
    monkeypatch.setattr(reports, "calculate", original_calculate)
    incomplete = client.get(
        path + "/finance/summary", params={**params, "date_from": "2025-01-01"}
    ).json()
    assert incomplete["summary"]["profit_before_tax"] is None
    assert incomplete["summary"]["issues"]["incomplete_period"] == 1
    assert all("profit_before_tax" not in value for value in memory.values())
    with Session(s.engine) as db:
        set_actor(db, s.user_id)
        assert len(db.scalars(select(FinanceDay)).all()) == 3
        set_actor(db, s.other_id)
        assert db.scalars(select(FinanceDay)).all() == []


def test_profit_projection_refresh_failure_preserves_previous_facts(setup, owner_client):
    from test_profit_rules import finance_row

    from app.modules.finance.models import FinanceDay, FinanceProjection

    s = setup
    first = import_profit_facts(s, [finance_row()])
    assert prepare_profit(s)
    second = import_profit_facts(s, [finance_row(for_pay="170")])

    def fail_projection(connection, cursor, statement, parameters, context, executemany):
        if statement.startswith("INSERT INTO finance_days"):
            raise RuntimeError("synthetic projection write failure")

    event.listen(s.engine, "before_cursor_execute", fail_projection)
    try:
        with pytest.raises(RuntimeError):
            prepare_profit(s)
    finally:
        event.remove(s.engine, "before_cursor_execute", fail_projection)
    with Session(s.engine) as db:
        set_actor(db, s.user_id)
        assert db.get(FinanceProjection, (s.workspace_id, s.store_id)).source_run_id == first
        assert len(db.scalars(select(FinanceDay)).all()) == 1
    assert prepare_profit(s)
    with Session(s.engine) as db:
        set_actor(db, s.user_id)
        assert db.get(FinanceProjection, (s.workspace_id, s.store_id)).source_run_id == second
        assert len(db.scalars(select(FinanceDay)).all()) == 1


def test_finance_preparation_worker_rechecks_current_mfa_owner(setup, monkeypatch):
    from app.workers import tasks

    s = setup
    prepare = Mock()
    monkeypatch.setattr(tasks, "get_settings", lambda: s.settings)
    monkeypatch.setattr(tasks, "build_engine", lambda settings: s.engine)
    monkeypatch.setattr(tasks.Redis, "from_url", lambda *args, **kwargs: s.redis)
    monkeypatch.setattr(tasks, "SecretVault", lambda path: s.vault)
    monkeypatch.setattr(tasks, "prepare_finance_projection", prepare)
    tasks.prepare_finance(str(s.workspace_id), str(s.store_id), str(s.other_id), "test-lease")
    prepare.assert_not_called()
    tasks.prepare_finance(str(s.workspace_id), str(s.store_id), str(s.user_id), "test-lease")
    prepare.assert_called_once()
    prepare.reset_mock()
    with Session(s.admin) as db, db.begin():
        db.get(User, s.user_id).email_verified_at = None
    tasks.prepare_finance(str(s.workspace_id), str(s.store_id), str(s.user_id), "test-lease")
    prepare.assert_not_called()


FINANCE_PARAMS = {"date_from": "2026-10-01", "date_to": "2026-10-03"}


def finance_snapshot(owner_client, **params):
    client, path = owner_client
    response = client.get(path + "/finance/summary", params={**FINANCE_PARAMS, **params})
    assert response.status_code == 200
    return response.json()


def test_finance_partial_batches_corrections_duplicate_days_and_final(setup, owner_client):
    from datetime import date

    from test_profit_rules import finance_row

    s = setup
    schema = owner_client[0].get("/openapi.json").json()["components"]["schemas"]["ProfitReport"]
    assert "is_partial" in schema["required"]
    assert schema["properties"]["is_partial"]["type"] == "boolean"
    assert finance_snapshot(owner_client)["status"] == "no_data"
    run_id, task_id = make_run(s, Source.FINANCE)
    with Session(s.admin) as db, db.begin():
        run = db.get(SyncRun, run_id)
        run.date_from, run.date_to = date(2026, 10, 1), date(2026, 10, 3)
    empty = finance_snapshot(owner_client)
    assert empty["status"] == "preparing" and not empty["is_partial"]
    assert empty["daily"] == [] and empty["updated_at"] is None
    sale = raw_finance(finance_row(), 1)
    usd = raw_finance(finance_row(currency="USD", retail_amount="9"), 2)
    process(s, run_id, task_id, Page([sale, usd], {"rrdId": 2}, False))
    first = finance_snapshot(owner_client)
    assert first["status"] == "ready" and first["is_partial"]
    assert first["summary"]["revenue"] == "200" and first["summary"]["for_pay"] == "160"
    assert first["daily"][0]["day"] == "2026-10-01" and len(first["daily"]) == 1
    assert not first["period_covered"] and first["updated_at"]
    assert finance_snapshot(owner_client, currency="USD")["summary"]["revenue"] == "9"
    assert finance_snapshot(owner_client, currency="EUR")["status"] == "preparing"
    for field in (
        "cogs",
        "settlement_estimate",
        "profit_before_tax",
        "margin_percent",
        "contribution_before_external_expenses",
    ):
        assert first["summary"][field] is None
    corrected = raw_finance(finance_row(retail_amount="260", for_pay="220"), 1)
    returned = raw_finance(
        finance_row(document_type="Возврат", operation="Возврат", retail_amount="40", for_pay="30"),
        3,
    )
    extra = raw_finance(
        finance_row(
            report_date="2026-10-02", retail_amount="90", for_pay="70", sale_reference="extra"
        ),
        4,
    )
    process(s, run_id, requeue(s, run_id), Page([corrected, returned, extra], {}, False))
    second = finance_snapshot(owner_client)
    assert second["summary"]["revenue"] == "310"
    assert second["summary"]["for_pay"] == "260"  # Never substitute payments for revenue.
    assert second["summary"]["records"] == 3
    assert second["daily"][0]["revenue"] == "220"
    assert second["updated_at"] > first["updated_at"]
    assert [row["day"] for row in second["daily"]] == ["2026-10-01", "2026-10-02"]
    process(s, run_id, requeue(s, run_id), Page([extra], {}, False))
    duplicate = finance_snapshot(owner_client)
    assert duplicate["summary"] == second["summary"]
    assert duplicate["daily"] == second["daily"]
    assert duplicate["updated_at"] > second["updated_at"]
    moved = {**extra, "rrDate": "2026-10-03"}
    process(s, run_id, requeue(s, run_id), Page([moved], {}, False))
    latest = finance_snapshot(owner_client)
    assert [row["day"] for row in latest["daily"]] == ["2026-10-01", "2026-10-03"]
    assert latest["summary"]["revenue"] == "310"

    # Financial reads use aggregates. Only catalog identifiers for returned products may be read.
    def no_raw_reads(connection, cursor, statement, parameters, context, executemany):
        assert "wb_staged_records" not in statement
        if "wb_records" in statement:
            assert parameters.get("source_1") == Source.CATALOG, statement

    event.listen(s.engine, "before_cursor_execute", no_raw_reads)
    try:
        assert finance_snapshot(owner_client) == latest
        assert finance_snapshot(owner_client, limit=2)["summary"] == latest["summary"]
        with Session(s.engine) as db, db.begin():
            set_actor(db, s.user_id)
            db.scalar(select(Store).where(Store.id == s.store_id).with_for_update())
            assert finance_snapshot(owner_client)["summary"] == latest["summary"]
    finally:
        event.remove(s.engine, "before_cursor_execute", no_raw_reads)
    process(s, run_id, requeue(s, run_id), Page([], {}, True))
    pending = finance_snapshot(owner_client)
    assert pending["status"] == "preparing" and not pending["is_partial"]
    assert prepare_profit(s)
    final = finance_snapshot(owner_client)
    assert final["status"] == "ready" and not final["is_partial"] and final["period_covered"]
    assert final["summary"]["revenue"] == "310" and final["summary"]["records"] == 3
    assert final["updated_at"] > latest["updated_at"]
    assert "import_in_progress" not in final["summary"]["issues"]
    with Session(s.engine) as db:
        set_actor(db, s.user_id)
        assert db.scalar(select(func.count()).select_from(WBStagedRecord)) == 0


def test_failed_finance_partial_is_discarded_retry_keeps_snapshot(setup, owner_client):
    from test_profit_rules import finance_row

    s = setup
    run_id, task_id = make_run(s, Source.FINANCE)
    process(s, run_id, task_id, Page([raw_finance(finance_row(), 1)], {}, False))
    partial = finance_snapshot(owner_client)
    assert partial["is_partial"]
    process(s, run_id, requeue(s, run_id), error=WBError("wb_unavailable", retryable=True))
    assert finance_snapshot(owner_client) == partial
    process(s, run_id, requeue(s, run_id), error=WBError("wb_forbidden"))
    failed = finance_snapshot(owner_client)
    assert failed["status"] == "no_data" and not failed["is_partial"]
    assert failed["daily"] == [] and failed["summary"]["revenue"] is None
    assert not prepare_profit(s)
    with Session(s.engine) as db:
        set_actor(db, s.user_id)
        assert db.get(SyncRun, run_id).status == "failed"
        assert db.scalar(select(func.count()).select_from(WBStagedRecord)) == 0
        assert not records(s)


def test_finance_reimport_never_double_counts_and_failure_restores_success(setup, owner_client):
    from test_profit_rules import finance_row

    s = setup
    import_profit_facts(s, [finance_row()])
    assert prepare_profit(s)
    final = finance_snapshot(owner_client)
    run_id, task_id = make_run(s, Source.FINANCE)
    assert finance_snapshot(owner_client) == final  # No useful new batch yet.
    changed = raw_finance(finance_row(retail_amount="500", for_pay="300"), 1)
    process(s, run_id, task_id, Page([changed], {}, False))
    partial = finance_snapshot(owner_client)
    assert partial["is_partial"] and partial["summary"]["revenue"] == "500"
    assert partial["summary"]["records"] == 1 and not partial["period_covered"]
    process(s, run_id, requeue(s, run_id), error=WBError("wb_forbidden"))
    assert finance_snapshot(owner_client) == final
    # Successful re-import replaces a same-key record; it does not append a second sale.
    run_id, task_id = make_run(s, Source.FINANCE)
    process(s, run_id, task_id, Page([changed], {}, False))
    process(s, run_id, requeue(s, run_id), Page([], {}, True))
    assert prepare_profit(s)
    refreshed = finance_snapshot(owner_client)
    assert not refreshed["is_partial"] and refreshed["summary"]["revenue"] == "500"
    assert refreshed["summary"]["records"] == 1


def test_busy_store_yields_without_losing_cursor_or_consuming_error_attempts(setup):
    s = setup
    run_id, task_id = make_run(s, Source.CATALOG)
    with Session(s.admin) as lock, lock.begin():
        lock.scalar(select(Store).where(Store.id == s.store_id).with_for_update(key_share=True))
        process(s, run_id, task_id, Page([], {}, True))
        with Session(s.admin) as db:
            run = db.get(SyncRun, run_id)
            assert run.status == "running" and run.attempts == 0
            assert run.pages_processed == 0 and run.records_processed == 0
            assert run.task_id is None and run.cursor == {}
            assert run.error_code == "sync_store_busy"
    process(s, run_id, requeue(s, run_id), Page([], {}, True))
    with Session(s.admin) as db:
        run = db.get(SyncRun, run_id)
        assert run.status == "succeeded" and run.error_code is None


def test_business_endpoint_and_balance_are_scoped(setup, owner_client):
    from test_profit_rules import finance_row

    s = setup
    client, _ = owner_client
    import_profit_facts(s, [finance_row()])
    assert prepare_profit(s)
    run_id, task_id = make_run(s, Source.BALANCE)
    process(
        s,
        run_id,
        task_id,
        Page([{"currency": "RUB", "current": 120, "for_withdraw": 70}], {}, True),
    )
    path = f"/api/v1/workspaces/{s.workspace_id}/business"
    response = client.get(path, params=FINANCE_PARAMS)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["total_stores"] == 1
    assert data["finance"]["summary"]["revenue"] == "200"
    assert data["balances"][0]["current"] == "120"
    assert data["stores"][0]["id"] == str(s.store_id)
    foreign = client.get(f"/api/v1/workspaces/{uuid4()}/business", params=FINANCE_PARAMS)
    assert foreign.status_code == 404
    empty = client.get(path, params={**FINANCE_PARAMS, "store_id": str(uuid4())})
    assert empty.status_code == 200 and empty.json()["total_stores"] == 0


def test_running_history_chunk_keeps_published_days_without_double_counting(setup, owner_client):
    from test_profit_rules import finance_row

    s = setup
    import_profit_facts(s, [finance_row()])
    assert prepare_profit(s)
    final = finance_snapshot(owner_client)
    assert final["summary"]["revenue"] == "200"
    run_id, task_id = make_run(s, Source.FINANCE)
    older = raw_finance(
        finance_row(report_date="2026-10-02", retail_amount="90", sale_reference="older"), 7
    )
    process(s, run_id, task_id, Page([older], {}, False))
    merged = finance_snapshot(owner_client)
    # The running chunk adds its own day; the published day is neither hidden nor added twice.
    assert merged["is_partial"] and not merged["period_covered"]
    assert [row["day"] for row in merged["daily"]] == ["2026-10-01", "2026-10-02"]
    assert merged["daily"][0]["revenue"] == final["daily"][0]["revenue"]
    assert merged["summary"]["revenue"] == "290" and merged["summary"]["records"] == 2
    assert merged["summary"]["cogs"] is None
    # A period the chunk does not touch is served by the published report alone.
    untouched = finance_snapshot(owner_client, date_to="2026-10-01")
    assert not untouched["is_partial"] and untouched["summary"] == final["summary"]


def test_partial_finance_unknown_values_access_and_snapshot_revision(
    setup, owner_client, monkeypatch
):
    from test_profit_rules import finance_row

    from app.modules.finance import report as reports
    from app.modules.sync.models import WBDailyMetric

    s = setup
    client, path = owner_client
    run_id, task_id = make_run(s, Source.FINANCE)
    process(s, run_id, task_id, Page([raw_finance(finance_row(retail_amount=None), 1)], {}, False))
    unknown = finance_snapshot(owner_client)
    assert unknown["summary"]["revenue"] is None and unknown["daily"][0]["revenue"] is None
    assert unknown["summary"]["issues"]["missing_retail_amount"] == 1
    assert (
        client.get(
            f"/api/v1/workspaces/{uuid4()}/stores/{s.store_id}/finance/summary",
            params=FINANCE_PARAMS,
        ).status_code
        == 404
    )
    assert (
        client.get(
            path.replace(str(s.store_id), str(uuid4())) + "/finance/summary", params=FINANCE_PARAMS
        ).status_code
        == 404
    )
    with Session(s.engine) as db:
        set_actor(db, s.other_id)
        assert db.scalars(select(WBDailyMetric)).all() == []
    original, changed = reports.partial_report, []

    def concurrent_batch(*args, **kwargs):
        result = original(*args, **kwargs)
        if not changed:
            process(s, run_id, requeue(s, run_id), Page([raw_finance(finance_row(), 1)], {}, False))
            changed.append(True)
        return result

    monkeypatch.setattr(reports, "partial_report", concurrent_batch)
    # A different limit avoids an existing cached snapshot and exercises the revision retry.
    stable = finance_snapshot(owner_client, limit=3)
    assert stable["is_partial"] and stable["summary"]["revenue"] == "200"
    assert stable["summary"]["records"] == 1 and len(stable["daily"]) == 1
    assert stable["updated_at"] > unknown["updated_at"]


def test_existing_preview_upgrade_and_expense_only_day_do_not_guess_revenue(setup, owner_client):
    from test_profit_rules import finance_row

    from app.modules.sync.analytics import ensure_preview, metric_context
    from app.modules.sync.models import WBDailyMetric

    s = setup
    client, path = owner_client
    run_id, task_id = make_run(s, Source.FINANCE)
    process(s, run_id, task_id, Page([raw_finance(finance_row(), 1)], {}, False))
    first = finance_snapshot(owner_client)
    # Simulate a preview created by the previous backend version.
    with Session(s.engine) as db, db.begin():
        set_actor(db, s.user_id)
        for row in db.scalars(select(WBDailyMetric).where(WBDailyMetric.dataset == str(run_id))):
            aad = metric_context(
                row.workspace_id,
                row.store_id,
                row.source,
                row.dataset,
                row.day,
                row.nm_id,
                row.currency,
            )
            old = json.loads(s.vault.open(row.ciphertext, aad))
            row.ciphertext = s.vault.seal(
                json.dumps(
                    {key: value for key, value in old.items() if not key.startswith("profit_")}
                ),
                aad,
            )
        db.get(SyncRun, run_id).preview_updated_at = None
    assert finance_snapshot(owner_client)["status"] == "preparing"
    with Session(s.engine) as db, db.begin():
        set_actor(db, s.user_id)
        db.scalar(select(Store).where(Store.id == s.store_id).with_for_update())
        run = db.get(SyncRun, run_id)
        ensure_preview(db, s.vault, run)
        stamp = run.preview_updated_at
        ensure_preview(db, s.vault, run)
        assert run.preview_updated_at == stamp  # Worker upgrades once, never every read.
    upgraded = finance_snapshot(owner_client)
    assert upgraded["is_partial"] and upgraded["summary"] == first["summary"]
    expense = client.post(
        path + "/expenses",
        json={"expense_date": "2026-10-03", "amount": "5", "comment": "Synthetic"},
    )
    assert expense.status_code == 201
    with_expense = finance_snapshot(owner_client)
    assert with_expense["updated_at"] > upgraded["updated_at"]
    assert with_expense["summary"]["external_expenses"] == "5"
    day = with_expense["daily"][-1]
    assert day["day"] == "2026-10-03" and day["revenue"] is None
    assert day["for_pay"] is None and day["cogs"] is None
    assert all(value is None for value in day["wb_expenses"].values())
    assert day["external_expenses"] == "5" and not with_expense["period_covered"]


@pytest.mark.parametrize("offset,failed", [(1, False), (0, False), (-1, False), (1, True)])
def test_finance_gap_uses_successful_scoped_coverage(setup, offset, failed):
    from app.modules.sync.planner import finance_gap

    s = setup
    start = history_limits()[Source.FINANCE]["date_from"]
    boundary = start + timedelta(days=10)
    plan = SimpleNamespace(
        workspace_id=s.workspace_id,
        store_id=s.store_id,
        source=Source.FINANCE,
        recent_completed=True,
        history_from=start,
        backfill_to=start - timedelta(days=1),
        backfill_chunk_days=3650,
    )
    with Session(s.engine) as db, db.begin():
        set_actor(db, s.user_id)
        for begin, end in [
            (start, boundary),
            (boundary + timedelta(days=1 + offset), boundary + timedelta(days=10)),
        ]:
            db.add(
                SyncRun(
                    id=uuid4(),
                    workspace_id=s.workspace_id,
                    store_id=s.store_id,
                    requested_by=s.user_id,
                    source=Source.FINANCE,
                    status="succeeded",
                    date_from=begin,
                    date_to=end,
                    finished_at=now(),
                )
            )
        if offset > 0:
            db.add(
                SyncRun(
                    id=uuid4(),
                    workspace_id=s.workspace_id,
                    store_id=s.store_id,
                    requested_by=s.user_id,
                    source=Source.FINANCE,
                    status="failed" if failed else "succeeded",
                    date_from=boundary + timedelta(days=1),
                    date_to=boundary + timedelta(days=1),
                    finished_at=now(),
                )
            )
        expected = (boundary + timedelta(days=1), boundary + timedelta(days=1)) if failed else None
        assert finance_gap(db, plan) == expected
        plan.source = Source.SALES
        assert finance_gap(db, plan) is None
        plan.source, plan.backfill_to = Source.FINANCE, boundary
        assert finance_gap(db, plan) is None


def test_finished_history_schedules_only_the_skipped_finance_days(setup, owner_client):
    from app.modules.sync.models import SyncSchedule
    from app.modules.sync.planner import completed, enqueue_store, finance_gap
    from app.modules.sync.schemas import moscow_today

    s = setup
    c, path = owner_client
    assert c.put(path + "/sync-schedule", json={"sources": ["finance"]}).status_code == 200
    with Session(s.engine) as db, db.begin():
        set_actor(db, s.user_id)
        plan = db.get(SyncSchedule, (s.workspace_id, s.store_id, "finance"))
        recent = db.scalar(select(SyncRun).where(SyncRun.store_id == s.store_id))
        recent.status, recent.finished_at = "succeeded", now()
        recent.date_from, recent.date_to = (
            moscow_today() - timedelta(days=30),
            moscow_today() - timedelta(days=1),
        )
        plan.recent_completed, plan.next_refresh_at = True, now() + timedelta(hours=6)
        history_end = recent.date_from - timedelta(days=5)
        history = SyncRun(
            id=uuid4(),
            workspace_id=s.workspace_id,
            store_id=s.store_id,
            requested_by=s.user_id,
            source=Source.FINANCE,
            status="succeeded",
            sync_mode="backfill",
            date_from=plan.history_from,
            date_to=history_end,
            finished_at=now(),
            next_attempt_at=now(),
        )
        db.add(history)
        completed(db, history, True)
        assert plan.next_attempt_at < plan.next_refresh_at
        expected = history_end + timedelta(days=1), recent.date_from - timedelta(days=1)
        assert finance_gap(db, plan) == expected
        capabilities = {"sources": {Source.FINANCE: {"error_code": None}}}
        enqueue_store(db, db.get(Store, s.store_id), capabilities)
        db.flush()
        queued = db.scalars(
            select(SyncRun).where(SyncRun.store_id == s.store_id, SyncRun.status == "queued")
        ).all()
        assert len(queued) == 1
        repair = queued[0]
        assert repair.sync_mode == "reconcile" and (repair.date_from, repair.date_to) == expected
        # A second scheduler pass never duplicates the active source.
        enqueue_store(db, db.get(Store, s.store_id), capabilities)
        db.flush()
        assert (
            db.scalar(
                select(func.count())
                .select_from(SyncRun)
                .where(SyncRun.store_id == s.store_id, SyncRun.status == "queued")
            )
            == 1
        )
        repair.status, repair.finished_at = "succeeded", now()
        completed(db, repair, True)
        assert finance_gap(db, plan) is None
        assert plan.next_attempt_at == plan.next_refresh_at


def test_finance_overview_full_cost_expense_tax_flow(setup, owner_client, monkeypatch):
    from test_profit_rules import finance_row

    from app.modules.insights import business

    s = setup
    client, path = owner_client
    import_catalog_for_costs(s)
    rows = [
        finance_row(
            report_date="2026-10-01",
            sale_date="2026-10-01",
            retail_price_with_discount="1000",
            retail_amount="800",
            for_pay="700",
            acquiring_fee="30",
            acquiring_percent="3",
            deduction="10",
            bonus_type_name="Оказание услуг WB Продвижение, кампания 123",
        )
    ]
    import_profit_facts(s, rows)
    assert prepare_profit(s)
    before_cost = client.get(
        f"/api/v1/workspaces/{s.workspace_id}/finance/overview",
        params={"date_from": "2026-10-01", "date_to": "2026-10-02", "store_id": str(s.store_id)},
    ).json()
    assert before_cost["expenses_exclude_cogs"]
    assert before_cost["totals"]["expenses_before_tax"] == "310"
    assert before_cost["totals"]["settlement"] == "690"
    assert before_cost["totals"]["profit_before_tax"] is None
    preview = preview_cost_file(client, path, [["42", "", "100", "2026-01-01", "RUB"]]).json()
    assert client.post(path + f"/cost-imports/{preview['preview_id']}/apply").status_code == 200
    expense = {
        "request_id": str(uuid4()),
        "expense_date": "2026-10-01",
        "amount": "5",
        "comment": "Synthetic packaging",
        "category": "packaging",
    }
    created = client.post(path + "/expenses", json=expense)
    assert created.status_code == 201 and created.json()["category"] == "packaging"
    assert client.post(path + "/expenses", json=expense).json()["id"] == created.json()["id"]
    assert client.post(path + "/expenses", json={**expense, "category": "rent"}).status_code == 409
    assert (
        client.put(
            path + "/tax-settings",
            json={
                "effective_from": "2026-01-01",
                "regime": "usn_income",
                "rate": "6",
                "vat_rate": "0",
                "income_base": "revenue",
            },
        ).status_code
        == 200
    )
    # A finance-only read must not start or wait for sales analytics.
    monkeypatch.setattr(
        business, "served", Mock(side_effect=AssertionError("unexpected analytics read"))
    )
    overview = f"/api/v1/workspaces/{s.workspace_id}/finance/overview"
    params = {"date_from": "2026-10-01", "date_to": "2026-10-02", "store_id": str(s.store_id)}
    response = client.get(overview, params=params)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["totals"] == {
        "storage_total": "0",
        "seller_revenue": "1000",
        "marketplace_revenue": "800",
        "expenses_before_tax": "415",
        "profit_before_tax": "585",
        "settlement": "690",
    }
    assert data["currency"] == "RUB" and not data["is_loading"]
    groups = {row["key"]: row for row in data["groups"]}
    assert groups["external"]["amount"] == "5"
    assert (
        next(row for row in groups["external"]["lines"] if row["key"] == "packaging")["amount"]
        == "5"
    )
    assert (
        next(row for row in groups["advertising"]["lines"] if row["key"] == "wb")["amount"] == "10"
    )
    assert data["taxes"]["tax"] == "48.00" and data["taxes"]["net_profit"] == "537.00"
    assert client.delete(path + f"/expenses/{created.json()['id']}").status_code == 204
    refreshed = client.get(overview, params=params).json()
    assert refreshed["groups"][-1]["amount"] == "0"
    assert refreshed["totals"]["profit_before_tax"] == "590"


def test_finance_overview_is_scoped_and_missing_data_stays_unknown(setup, owner_client):
    s = setup
    client, path = owner_client
    overview = f"/api/v1/workspaces/{s.workspace_id}/finance/overview"
    params = {"date_from": "2026-10-01", "date_to": "2026-10-02", "store_id": str(s.store_id)}
    result = client.get(overview, params=params)
    assert result.status_code == 200, result.text
    assert all(value is None for value in result.json()["totals"].values())
    assert result.json()["taxes"]["net_profit"] is None
    assert (
        client.get(f"/api/v1/workspaces/{uuid4()}/finance/overview", params=params).status_code
        == 404
    )
    assert client.get(overview, params={**params, "store_id": str(uuid4())}).status_code == 404
    with Session(s.admin) as db, db.begin():
        db.get(Membership, (s.user_id, s.workspace_id)).role = "viewer"
    assert client.get(overview, params=params).status_code == 200
    assert (
        client.post(
            path + "/expenses", json={"expense_date": "2026-10-01", "amount": "1", "comment": "x"}
        ).status_code
        == 403
    )


def test_product_identifiers_are_scoped_fresh_and_do_not_change_report_money(setup, owner_client):
    from test_profit_rules import finance_row

    s = setup
    client, path = owner_client
    import_profit_facts(s, [finance_row()])
    assert prepare_profit(s)
    params = {"date_from": "2026-10-01", "date_to": "2026-10-02"}
    initial = client.get(path + "/finance/summary", params=params).json()
    product = initial["products"][0]
    assert product["vendor_code"] is None and product["barcodes"] == ["0001"]

    import_catalog_for_costs(s)
    resolved = client.get(path + "/finance/summary", params=params).json()
    assert resolved["summary"] == initial["summary"]
    assert resolved["products"][0]["vendor_code"] == "A42"
    assert resolved["products"][0]["barcodes"] == ["0001", "0002"]
    business = client.get(
        f"/api/v1/workspaces/{s.workspace_id}/business", params={**params, "topic": "overview"}
    ).json()
    assert business["stores"][0]["finance"]["products"][0]["vendor_code"] == "A42"
    abc = client.get(path + "/finance/abc", params={**params, "metric": "revenue"}).json()
    assert abc["items"][0]["vendor_code"] == "A42"
    assert abc["items"][0]["barcodes"] == ["0001", "0002"]

    # Catalog labels are resolved after the financial cache: no money rebuild is needed.
    with Session(s.engine) as db, db.begin():
        set_actor(db, s.user_id)
        row = db.scalar(
            select(WBRecord).where(
                WBRecord.workspace_id == s.workspace_id,
                WBRecord.store_id == s.store_id,
                WBRecord.source == "catalog",
                WBRecord.record_key == "42",
            )
        )
        aad = context(s.workspace_id, s.store_id, Source.CATALOG, "42")
        data = json.loads(s.vault.open(row.ciphertext, aad))
        data["vendor_code"] = "UPDATED-42"
        row.ciphertext = s.vault.seal(json.dumps(data), aad)
    updated = client.get(path + "/finance/summary", params=params).json()
    assert updated["products"][0]["vendor_code"] == "UPDATED-42"
    assert updated["summary"] == initial["summary"]
    assert (
        client.get(
            f"/api/v1/workspaces/{uuid4()}/stores/{s.store_id}/finance/summary", params=params
        ).status_code
        == 404
    )
    assert (
        client.get(
            f"/api/v1/workspaces/{s.workspace_id}/stores/{uuid4()}/finance/summary", params=params
        ).status_code
        == 404
    )


def test_network_request_releases_run_lock_and_late_errors_keep_new_lease(setup):
    s = setup
    run_id, task_id = make_run(s, Source.SALES)
    replacement = str(uuid4())

    def slow_request(*args):
        with Session(s.engine) as db, db.begin():
            set_actor(db, s.user_id)
            row = db.scalar(
                select(SyncRun).where(SyncRun.id == run_id).with_for_update(nowait=True)
            )
            assert row is not None
            row.task_id = replacement
        raise WBError("wb_unavailable", retryable=True)

    client = Mock()
    client.page.side_effect = slow_request
    run_page(s.engine, s.redis, s.vault, s.settings, run_id, task_id, client)
    with Session(s.engine) as db:
        set_actor(db, s.user_id)
        run = db.get(SyncRun, run_id)
        assert run.task_id == replacement and run.attempts == 0


def remember_pending_pages(s):
    """Keep pending pages, but reject quota acquisition on a cached retry."""
    storage = {}
    s.redis.get.side_effect = storage.get
    s.redis.set.side_effect = lambda key, value, **kw: storage.update({key: value}) or True
    s.redis.delete.side_effect = lambda key: storage.pop(key, None) is not None
    return storage


@pytest.mark.parametrize("complete", [False, True])
def test_busy_store_preserves_received_page_and_never_refetches_it(setup, complete):
    s = setup
    storage = remember_pending_pages(s)
    run_id, task_id = make_run(s, Source.CATALOG)
    page = Page([{"nmID": 42, "title": "Received once"}], {"nmID": 42}, complete)
    transport = Mock()
    transport.page.return_value = page
    with Session(s.admin) as lock, lock.begin():
        lock.scalar(select(Store).where(Store.id == s.store_id).with_for_update(key_share=True))
        run_page(s.engine, s.redis, s.vault, s.settings, run_id, task_id, transport)
        # Several retries while finance still holds the lock must not fetch or
        # extend the provider quota; attempts and cursor remain unchanged.
        s.redis.set.side_effect = AssertionError("cached retry must not claim another quota slot")
        for _ in range(2):
            run_page(s.engine, s.redis, s.vault, s.settings, run_id, requeue(s, run_id), transport)
        with Session(s.admin) as db:
            run = db.get(SyncRun, run_id)
            assert run.attempts == run.pages_processed == 0 and run.cursor == {}
    run_page(s.engine, s.redis, s.vault, s.settings, run_id, requeue(s, run_id), transport)
    transport.page.assert_called_once()
    assert not any(key.startswith("perk:wb-pending-page:") for key in storage)
    with Session(s.admin) as db:
        run = db.get(SyncRun, run_id)
        assert run.pages_processed == 1 and run.records_processed == 1
        assert run.status == ("succeeded" if complete else "running")
        assert run.cursor == page.cursor and run.error_code is None


def test_pending_page_is_kept_if_publication_rolls_back(setup, monkeypatch):
    import app.modules.sync.service as sync_service

    s = setup
    storage = remember_pending_pages(s)
    run_id, task_id = make_run(s, Source.CATALOG)
    transport = Mock()
    transport.page.return_value = Page([{"nmID": 42}], {}, True)
    with Session(s.admin) as lock, lock.begin():
        lock.scalar(select(Store).where(Store.id == s.store_id).with_for_update(key_share=True))
        run_page(s.engine, s.redis, s.vault, s.settings, run_id, task_id, transport)
    original = sync_service.publish
    monkeypatch.setattr(sync_service, "publish", Mock(side_effect=RuntimeError("rollback")))
    with pytest.raises(RuntimeError, match="rollback"):
        run_page(s.engine, s.redis, s.vault, s.settings, run_id, requeue(s, run_id), transport)
    assert any(key.startswith("perk:wb-pending-page:") for key in storage)
    assert records(s) == []
    monkeypatch.setattr(sync_service, "publish", original)
    run_page(s.engine, s.redis, s.vault, s.settings, run_id, requeue(s, run_id), transport)
    transport.page.assert_called_once()
    assert len(records(s)) == 1


def test_pending_page_never_bypasses_disconnection(setup):
    s = setup
    remember_pending_pages(s)
    run_id, task_id = make_run(s, Source.CATALOG)
    transport = Mock()
    transport.page.return_value = Page([{"nmID": 42}], {}, True)
    with Session(s.admin) as lock, lock.begin():
        lock.scalar(select(Store).where(Store.id == s.store_id).with_for_update(key_share=True))
        run_page(s.engine, s.redis, s.vault, s.settings, run_id, task_id, transport)
    with Session(s.admin) as db, db.begin():
        db.get(Store, s.store_id).connection_status = "disconnected"
    run_page(s.engine, s.redis, s.vault, s.settings, run_id, requeue(s, run_id), transport)
    transport.page.assert_called_once()
    assert records(s) == []
