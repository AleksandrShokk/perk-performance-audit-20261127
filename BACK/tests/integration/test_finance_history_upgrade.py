"""Real PostgreSQL: any store can upgrade old rows through the normal sync outbox."""

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session
from test_profit_rules import finance_row
from test_wb_sync_database import (
    import_profit_facts,
    prepare_profit,
    process,
    raw_finance,
)
from test_wb_sync_database import pytestmark as pytestmark
from test_wb_sync_database import setup as setup

from app.db.session import set_actor
from app.integrations.wildberries.data import Page, Source
from app.modules.auth.dependencies import now
from app.modules.auth.models import Membership
from app.modules.finance.history import UPGRADE_MODE, enqueue
from app.modules.finance.models import FinanceProjection
from app.modules.sync.models import SyncRun


def old_import(s):
    import json

    from app.modules.sync.analytics import record_context
    from app.modules.sync.models import WBRecord

    import_profit_facts(s, [finance_row(retail_price_with_discount="200")])
    # Reproduce retained records from a previous loader, rather than a newly normalized response.
    with Session(s.engine) as db, db.begin():
        set_actor(db, s.user_id)
        row = db.scalar(select(WBRecord).where(WBRecord.source == "finance"))
        aad = record_context(s.workspace_id, s.store_id, "finance", row.record_key)
        value = json.loads(s.vault.open(row.ciphertext, aad))
        value.update(data_version=2, payment_schedule=None, acquiring_percent=None)
        row.ciphertext = s.vault.seal(json.dumps(value), aad)
    assert prepare_profit(s)


def test_saved_old_fields_queue_once_and_new_publication_clears_upgrade_window(setup):
    s = setup
    old_import(s)
    with Session(s.engine) as db, db.begin():
        set_actor(db, s.user_id)
        state = db.get(FinanceProjection, (s.workspace_id, s.store_id))
        assert state.legacy_date_from == state.legacy_date_to == date(2026, 10, 1)
        assert enqueue(db, s.workspace_id, s.store_id, s.user_id)
        assert not enqueue(db, s.workspace_id, s.store_id, s.user_id)
        run = db.scalar(select(SyncRun).where(SyncRun.sync_mode == UPGRADE_MODE))
        assert run.requested_by == s.user_id and run.cursor == {"page_size": 100000}
        run.task_id = "upgrade-fixture"
        run_id = run.id
    process(s, run_id, "upgrade-fixture", Page([raw_finance(finance_row(), 1)], {}, True))
    assert prepare_profit(s)
    with Session(s.engine) as db:
        set_actor(db, s.user_id)
        state = db.get(FinanceProjection, (s.workspace_id, s.store_id))
        assert state.legacy_date_from is None and state.legacy_date_to is None
        assert not enqueue(db, s.workspace_id, s.store_id, s.user_id)


def test_foreign_member_cannot_start_upgrade_and_failures_do_not_loop(setup):
    s = setup
    old_import(s)
    with Session(s.admin) as db, db.begin():
        db.add(Membership(user_id=s.other_id, workspace_id=s.workspace_id, role="viewer"))
    with Session(s.engine) as db, db.begin():
        set_actor(db, s.other_id)
        assert not enqueue(db, s.workspace_id, s.store_id, s.other_id)
    with Session(s.engine) as db, db.begin():
        set_actor(db, s.user_id)
        assert enqueue(db, s.workspace_id, s.store_id, s.user_id)
        run = db.scalar(select(SyncRun).where(SyncRun.sync_mode == UPGRADE_MODE))
        run.status = "failed"
        db.flush()
        assert not enqueue(db, s.workspace_id, s.store_id, s.user_id)
        run.created_at = now() - timedelta(hours=7)
        db.flush()
        assert enqueue(db, s.workspace_id, s.store_id, s.user_id)


def test_each_store_has_its_own_upgrade_window_and_outbox(setup):
    from uuid import uuid4

    from app.modules.accounts.models import Store, StoreCredential
    from app.modules.finance.projection import FORMAT

    s = setup
    old_import(s)
    other_store, other_run = uuid4(), uuid4()
    with Session(s.admin) as db, db.begin():
        db.add(
            Store(
                id=other_store,
                workspace_id=s.workspace_id,
                name="Second store",
                marketplace="wildberries",
                connection_status="connected",
            )
        )
        db.flush()
        db.add(
            StoreCredential(
                workspace_id=s.workspace_id,
                store_id=other_store,
                ciphertext="fixture-only",
                scopes="finance",
                expires_at=now() + timedelta(hours=1),
            )
        )
        db.add(
            SyncRun(
                id=other_run,
                workspace_id=s.workspace_id,
                store_id=other_store,
                source="finance",
                requested_by=s.user_id,
                status="succeeded",
                finished_at=now(),
            )
        )
        db.flush()
        db.add(
            FinanceProjection(
                workspace_id=s.workspace_id,
                store_id=other_store,
                source_run_id=other_run,
                format_version=FORMAT,
                updated_at=now(),
                legacy_date_from=date(2025, 1, 1),
                legacy_date_to=date(2025, 2, 1),
            )
        )
    with Session(s.engine) as db, db.begin():
        set_actor(db, s.user_id)
        assert enqueue(db, s.workspace_id, s.store_id, s.user_id)
        assert enqueue(db, s.workspace_id, other_store, s.user_id)
        runs = db.scalars(select(SyncRun).where(SyncRun.sync_mode == UPGRADE_MODE)).all()
        assert len(runs) == 2
        by_store = {run.store_id: (run.date_from, run.date_to) for run in runs}
        assert by_store[s.store_id] == (date(2026, 10, 1), date(2026, 10, 1))
        assert by_store[other_store] == (date(2025, 1, 1), date(2025, 2, 1))
        assert not enqueue(db, uuid4(), other_store, s.user_id)


def test_old_compatible_projection_remains_readable_while_metadata_is_prepared(setup, monkeypatch):
    from unittest.mock import Mock

    from fastapi.testclient import TestClient

    from app.db.session import get_db
    from app.main import create_app
    from app.modules.auth.dependencies import Identity, full_identity
    from app.modules.auth.models import AuthSession, User
    from app.workers.tasks import prepare_finance

    s = setup
    old_import(s)
    with Session(s.admin) as db, db.begin():
        db.get(FinanceProjection, (s.workspace_id, s.store_id)).format_version = 4
    app = create_app(s.settings)

    def db_for_request():
        with Session(s.engine) as db:
            set_actor(db, s.user_id)
            yield db

    app.dependency_overrides[get_db] = db_for_request
    app.dependency_overrides[full_identity] = lambda: Identity(User(id=s.user_id), AuthSession())
    queued = Mock()
    monkeypatch.setattr(prepare_finance, "apply_async", queued)
    with TestClient(app) as client:
        app.state.vault = s.vault
        result = client.get(
            f"/api/v1/workspaces/{s.workspace_id}/stores/{s.store_id}/finance/summary",
            params={"date_from": "2026-10-01", "date_to": "2026-10-03"},
        )
        assert result.status_code == 200
        assert result.json()["status"] == "ready" and result.json()["summary"]["revenue"] == "200"
        queued.assert_called_once()


def test_dispatch_gives_finance_its_own_queue_and_publication_budget(setup, monkeypatch):
    from unittest.mock import Mock

    from test_wb_sync_database import make_run

    from app.workers import tasks
    from app.workers.celery_app import HEAVY_QUEUE

    s = setup
    finance, _ = make_run(s, Source.FINANCE)
    stocks, _ = make_run(s, Source.STOCKS)
    sent = Mock()
    monkeypatch.setattr(tasks, "get_settings", lambda: s.settings)
    monkeypatch.setattr(tasks, "build_engine", lambda _: s.engine)
    monkeypatch.setattr(tasks.sync_page, "apply_async", sent)
    tasks.dispatch_sync()
    calls = {call.kwargs["args"][0]: call.kwargs for call in sent.call_args_list}
    assert calls[str(finance)]["queue"] == HEAVY_QUEUE
    assert calls[str(finance)]["soft_time_limit"] == 600
    assert calls[str(finance)]["time_limit"] == 660
    assert "queue" not in calls[str(stocks)] and "soft_time_limit" not in calls[str(stocks)]
