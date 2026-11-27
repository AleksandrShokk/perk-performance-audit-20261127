import json
from uuid import uuid4

from sqlalchemy import event, text, update
from sqlalchemy.orm import Session
from test_insights_flow import env as env
from test_insights_flow import pytestmark as pytestmark

from app.db.session import set_actor
from app.modules.accounts.access import PERMISSIONS, ROLE_DEFAULTS
from app.modules.auth.models import Membership
from app.modules.notifications.models import Notification
from app.modules.notifications.service import notification_aad
from app.modules.sync.models import SyncRun


def test_outbox_cannot_be_read_without_actor_or_from_another_workspace(env):
    e = env
    rid = uuid4()
    with Session(e.admin) as db, db.begin():
        db.add(
            SyncRun(
                id=rid,
                workspace_id=e.workspace,
                store_id=e.store,
                source="sales",
                requested_by=e.owner,
            )
        )
    with Session(e.engine) as db:
        assert db.get(SyncRun, rid) is None
        set_actor(db, uuid4())
        assert db.get(SyncRun, rid) is None
        set_actor(db, e.owner)
        assert db.get(SyncRun, rid) is not None
        rows = db.execute(
            text(
                "SELECT relname,relrowsecurity,relforcerowsecurity FROM pg_class "
                "WHERE relname IN ('sync_runs','notifications','ozon_analytics_sync',"
                "'ozon_catalog_sync','supply_destination_sync')"
            )
        ).all()
        assert len(rows) == 5 and all(
            row.relrowsecurity and row.relforcerowsecurity for row in rows
        )


def test_notification_feed_is_bounded_and_has_no_n_plus_one(env):
    e = env
    with Session(e.admin) as db, db.begin():
        for _ in range(1000):
            nid = uuid4()
            db.add(
                Notification(
                    id=nid,
                    user_id=e.owner,
                    workspace_id=e.workspace,
                    store_id=e.store,
                    kind="stock",
                    severity="info",
                    dedupe_key=str(nid),
                    ciphertext=e.vault.seal(
                        json.dumps({"title": "Stock", "body": "Test", "data": {}}),
                        notification_aad(e.owner, nid),
                    ),
                )
            )
    headers = e.login(e.owner)
    calls = []

    def count(*args):
        calls.append(1)

    event.listen(e.client.app.state.db_engine, "before_cursor_execute", count)
    try:
        result = e.client.get("/api/v1/notifications?limit=30", headers=headers)
    finally:
        event.remove(e.client.app.state.db_engine, "before_cursor_execute", count)
    assert result.status_code == 200, result.text
    assert len(result.json()["items"]) == 30 and result.json()["unread_count"] == 1000
    assert 4 <= len(calls) <= 6


def test_python_role_defaults_match_actual_database_permissions(env):
    e = env
    for role, expected in {
        **ROLE_DEFAULTS,
        "owner": list(PERMISSIONS),
        "admin": list(PERMISSIONS),
    }.items():
        with Session(e.admin) as db, db.begin():
            db.execute(
                update(Membership)
                .where(Membership.user_id == e.owner, Membership.workspace_id == e.workspace)
                .values(role=role, permissions=None)
            )
        with Session(e.engine) as db:
            set_actor(db, e.owner)
            actual = [
                key
                for key in PERMISSIONS
                if db.scalar(
                    text("SELECT perk_permission(:ws,:key)"), {"ws": e.workspace, "key": key}
                )
            ]
            assert set(actual) == set(expected)


def test_dispatch_does_not_write_a_view_only_workspaces_queue(env, monkeypatch):
    from sqlalchemy import delete

    from app.modules.accounts.models import Store, Workspace
    from app.modules.auth.dependencies import now
    from app.modules.insights import ozon_jobs
    from app.modules.insights.marketplace_models import OzonAnalyticsSync

    e = env
    other_workspace, other_store = uuid4(), uuid4()
    with Session(e.admin) as db, db.begin():
        db.add(Workspace(id=other_workspace, name="Other", owner_user_id=e.viewer))
        db.flush()
        db.add_all(
            [
                Membership(user_id=e.viewer, workspace_id=other_workspace, role="owner"),
                Membership(user_id=e.owner, workspace_id=other_workspace, role="viewer"),
                Store(
                    id=other_store,
                    workspace_id=other_workspace,
                    name="Other",
                    marketplace="ozon",
                    connection_status="connected",
                ),
            ]
        )
        db.flush()
        for wid, sid, uid in [
            (e.workspace, e.store, e.owner),
            (other_workspace, other_store, e.viewer),
        ]:
            db.add(
                OzonAnalyticsSync(
                    workspace_id=wid,
                    store_id=sid,
                    requested_by=uid,
                    source="sales",
                    next_attempt_at=now(),
                )
            )

    def owner_only(db, queue):
        set_actor(db, e.owner)
        yield e.owner
        db.flush()

    sent = []
    monkeypatch.setattr(ozon_jobs, "actors", owner_only)
    monkeypatch.setattr(ozon_jobs, "build_engine", lambda _: e.engine)
    monkeypatch.setattr(ozon_jobs, "release_engine", lambda _: None)
    monkeypatch.setattr(
        ozon_jobs.import_analytics, "apply_async", lambda **kwargs: sent.append(kwargs)
    )
    try:
        ozon_jobs.dispatch.run()
        with Session(e.admin) as db:
            assert db.get(OzonAnalyticsSync, (e.workspace, e.store, "sales")).status == "queued"
            assert (
                db.get(OzonAnalyticsSync, (other_workspace, other_store, "sales")).status
                == "pending"
            )
        assert len(sent) == 1 and sent[0]["args"][0] == str(e.workspace)
    finally:
        with Session(e.admin) as db, db.begin():
            db.execute(delete(Workspace).where(Workspace.id == other_workspace))


def test_deletion_dry_run_preserves_data_and_execution_removes_workspace(env):
    from sqlalchemy import MetaData, func, select

    from app.modules.accounts.models import Store, Workspace
    from app.modules.audit.models import AuditEvent
    from scripts.delete_data import remove

    e = env
    with Session(e.admin) as db, db.begin():
        counts = remove(db, e.workspace)
        assert counts["wb_records"] > 0
        assert db.get(Store, e.store) is not None
        assert db.get(Workspace, e.workspace) is not None
    with Session(e.admin) as db, db.begin():
        remove(db, e.workspace, execute=True)
    with Session(e.admin) as db:
        metadata = MetaData()
        metadata.reflect(bind=e.admin)
        for table in metadata.tables.values():
            if "workspace_id" in table.c:
                assert (
                    db.scalar(
                        select(func.count())
                        .select_from(table)
                        .where(table.c.workspace_id == e.workspace)
                    )
                    == 0
                ), table.name
        assert db.get(Workspace, e.workspace) is None
        assert db.get(Store, e.store) is None
        event = db.scalar(select(AuditEvent).where(AuditEvent.target_id == e.workspace))
        assert event.action == "data.workspace_deleted" and event.workspace_id is None
