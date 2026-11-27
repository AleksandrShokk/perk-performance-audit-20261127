import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import build_engine
from app.main import create_app
from app.modules.accounts.models import Store, Workspace
from app.modules.sync.models import SyncRun

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("PERK_INTEGRATION_TESTS") != "1",
        reason="Set PERK_INTEGRATION_TESTS=1 with PERK PostgreSQL and Redis running",
    ),
]


@pytest.fixture
def session():
    # These are schema/constraint tests, not access tests: create synthetic ownerless rows
    # through the isolated admin connection. Runtime-role RLS is tested separately.
    settings = get_settings().model_copy(
        update={
            "postgres_user": os.environ["TEST_ADMIN_USER"],
            "postgres_password_file": Path(os.environ["TEST_ADMIN_PASSWORD_FILE"]),
        }
    )
    engine = build_engine(settings)
    try:
        with engine.connect() as connection, connection.begin() as transaction:
            with Session(bind=connection, join_transaction_mode="create_savepoint") as db:
                yield db
            transaction.rollback()
    finally:
        engine.dispose()


def test_readiness_with_real_postgresql_and_redis():
    with TestClient(create_app()) as client:
        response = client.get("/api/v1/health/ready")
        assert response.status_code == 200
        assert response.json()["dependencies"] == {"database": "ok", "redis": "ok"}


def test_sync_run_roundtrip(session):
    workspace = Workspace(name="PERK integration test")
    session.add(workspace)
    session.flush()
    store = Store(workspace_id=workspace.id, name="Test WB", marketplace="wildberries")
    session.add(store)
    session.flush()
    run = SyncRun(workspace_id=workspace.id, store_id=store.id, source="orders")
    session.add(run)
    session.flush()
    session.refresh(run)
    assert run.status == "queued"
    assert run.records_processed == 0
    assert run.created_at.tzinfo is not None


def test_sync_cannot_reference_store_in_another_workspace(session):
    first = Workspace(name="First")
    second = Workspace(name="Second")
    session.add_all([first, second])
    session.flush()
    store = Store(workspace_id=first.id, name="First store", marketplace="ozon")
    session.add(store)
    session.flush()
    with pytest.raises(IntegrityError), session.begin_nested():
        session.add(SyncRun(workspace_id=second.id, store_id=store.id, source="orders"))
        session.flush()


def test_unknown_marketplace_is_rejected(session):
    workspace = Workspace(name="Test")
    session.add(workspace)
    session.flush()
    with pytest.raises(IntegrityError), session.begin_nested():
        session.add(Store(workspace_id=workspace.id, name="Bad store", marketplace="unknown"))
        session.flush()


def test_negative_record_count_is_rejected(session):
    workspace = Workspace(name="Test")
    session.add(workspace)
    session.flush()
    store = Store(workspace_id=workspace.id, name="Test store", marketplace="wildberries")
    session.add(store)
    session.flush()
    with pytest.raises(IntegrityError), session.begin_nested():
        session.add(
            SyncRun(
                workspace_id=workspace.id, store_id=store.id, source="orders", records_processed=-1
            )
        )
        session.flush()


def test_latest_source_state_is_bounded_and_scoped(session):
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import event

    from app.modules.sync.read import source_states

    workspace, other = Workspace(name="Audit first"), Workspace(name="Audit second")
    session.add_all([workspace, other])
    session.flush()
    first = Store(workspace_id=workspace.id, name="A", marketplace="wildberries")
    second = Store(workspace_id=workspace.id, name="B", marketplace="wildberries")
    foreign = Store(workspace_id=other.id, name="C", marketplace="wildberries")
    session.add_all([first, second, foreign])
    session.flush()
    at = datetime(2026, 11, 1, tzinfo=UTC)
    session.add_all(
        [
            SyncRun(
                workspace_id=workspace.id,
                store_id=first.id,
                source="stocks",
                status="succeeded",
                created_at=at + timedelta(minutes=i),
                finished_at=at,
            )
            for i in range(100)
        ]
    )
    for store in (second, foreign):
        session.add(
            SyncRun(
                workspace_id=store.workspace_id,
                store_id=store.id,
                source="stocks",
                status="running",
                created_at=at + timedelta(days=2),
            )
        )
    session.add_all(
        [
            SyncRun(
                workspace_id=workspace.id,
                store_id=first.id,
                source="stocks",
                status="failed",
                created_at=at + timedelta(days=1),
            ),
            SyncRun(
                workspace_id=workspace.id,
                store_id=first.id,
                source="catalog",
                status="queued",
                created_at=at,
            ),
        ]
    )
    session.flush()
    workspace_id, store_id = workspace.id, first.id
    session.expunge_all()
    loaded = []

    def record(_session, instance):
        if isinstance(instance, SyncRun):
            loaded.append(instance)

    event.listen(session, "loaded_as_persistent", record)
    try:
        state = source_states(session, workspace_id, store_id, ["stocks", "catalog", "prices"])
    finally:
        event.remove(session, "loaded_as_persistent", record)
    assert len(loaded) == 2  # not 100 historical successes or another store's active runs
    assert state["stocks"].success.created_at == at + timedelta(minutes=99)
    assert not state["stocks"].loading
    assert state["catalog"].success is None and state["catalog"].loading
    assert state["prices"].success is None and not state["prices"].loading


@pytest.mark.parametrize("can_cost", [False, True])
def test_stock_summary_matches_full_page_including_unknowns(session, vault, can_cost):
    import json

    from app.integrations.wildberries.data import Source
    from app.modules.auth.dependencies import now
    from app.modules.inventory.overview import overview
    from app.modules.sync.models import WBRecord
    from app.modules.sync.service import context

    workspace = Workspace(name="Summary regression")
    session.add(workspace)
    session.flush()
    store = Store(workspace_id=workspace.id, name="Stock", marketplace="wildberries")
    session.add(store)
    session.flush()
    at = now()
    for source in (Source.CATALOG, Source.STOCKS, Source.FBS, Source.PRICES):
        session.add(
            SyncRun(
                workspace_id=workspace.id,
                store_id=store.id,
                source=source,
                status="succeeded",
                finished_at=at,
                created_at=at,
            )
        )
    records = {
        Source.CATALOG: [
            {
                "nm_id": "1",
                "vendor_code": "ABC",
                "title": "Product",
                "sizes": [{"chrt_id": "10", "size": "M", "barcodes": ["111"]}],
            }
        ],
        Source.STOCKS: [
            {
                "nm_id": "1",
                "chrt_id": "10",
                "warehouse_name": "A",
                "quantity": 3,
                "in_way_to_client": 2,
                "in_way_from_client": 1,
            },
            # Orphan size and article must remain in stock even without a catalog card.
            {
                "nm_id": "2",
                "chrt_id": "20",
                "warehouse_name": "B",
                "quantity": 2,
                "in_way_to_client": 0,
                "in_way_from_client": 0,
            },
        ],
        Source.FBS: [{"nm_id": "1", "chrt_id": "11", "warehouse_name": "Seller", "quantity": 4}],
        Source.PRICES: [{"nm_id": "1", "currency": "RUB", "prices": {"10": "100", "11": "150"}}],
    }
    for source, rows in records.items():
        for i, row in enumerate(rows):
            key = str(i)
            session.add(
                WBRecord(
                    workspace_id=workspace.id,
                    store_id=store.id,
                    source=source,
                    record_key=key,
                    ciphertext=vault.seal(
                        json.dumps(row), context(workspace.id, store.id, source, key)
                    ),
                    updated_at=at,
                )
            )
    session.flush()
    summary = overview(session, vault, workspace.id, [store], "RUB", can_cost)
    full = overview(session, vault, workspace.id, [store], "RUB", can_cost, limit=30)
    assert summary.model_dump(exclude={"items", "limit"}) == full.model_dump(
        exclude={"items", "limit"}
    )
    assert summary.items == [] and summary.count == 2
    assert summary.fbo.units == 5 and summary.fbs.units == 4
    assert summary.total.retail_value == "900.00" and not summary.total.retail_complete
    assert summary.total.cost_value is None and not summary.total.cost_complete
    assert full.items[0].turnover_status == "no_data"
    # Search and in-stock filtering must preserve the same summary/page contract.
    filtered = overview(
        session, vault, workspace.id, [store], "RUB", can_cost, query="ABC", only_stock=True
    )
    assert filtered.count == 1 and filtered.total.units == 7
