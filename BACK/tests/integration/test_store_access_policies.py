"""Set-based store policies (migration 0044) grant exactly what perk_store_access granted."""

from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session
from test_catalog import card, seed
from test_wb_sync_database import pytestmark as pytestmark
from test_wb_sync_database import setup as setup

from app.db.session import set_actor
from app.integrations.wildberries.data import Source
from app.modules.accounts.models import Store
from app.modules.auth.dependencies import now
from app.modules.auth.models import Membership
from app.modules.sync.models import WBRecord


def visible(s, actor):
    with Session(s.engine) as db, db.begin():
        set_actor(db, actor)
        rows = db.execute(select(WBRecord.store_id, func.count()).group_by(WBRecord.store_id)).all()
        # The previous per-row function must agree with the set-based policy row by row.
        disagreements = db.scalar(
            text(
                "SELECT count(*) FROM wb_records "
                "WHERE NOT perk_store_access(workspace_id, store_id)"
            )
        )
    return {str(store): count for store, count in rows}, disagreements


def member(s, user, role, stores=None):
    with Session(s.admin) as db, db.begin():
        db.add(
            Membership(
                user_id=user,
                workspace_id=s.workspace_id,
                role=role,
                permissions=["inventory.read"] if role == "manager" else None,
                store_ids=stores,
            )
        )


def test_owner_restricted_manager_and_stranger_see_the_same_rows_as_before(setup):
    s = setup
    second = uuid4()
    with Session(s.admin) as db, db.begin():
        db.add(Store(id=second, workspace_id=s.workspace_id, name="B", marketplace="wildberries"))
    seed(s, Source.CATALOG, [("1", card(article="1")), ("2", card(article="2"))])
    seed(s, Source.CATALOG, [("3", card(article="3"))], second)
    first = str(s.store_id)

    owner, disagreements = visible(s, s.user_id)
    assert owner == {first: 2, str(second): 1} and disagreements == 0

    member(s, s.other_id, "manager", [first])
    manager, disagreements = visible(s, s.other_id)
    assert manager == {first: 2} and disagreements == 0

    stranger, disagreements = visible(s, uuid4())
    assert stranger == {} and disagreements == 0

    with Session(s.engine) as db:
        set_actor(db, s.other_id)
        # Write policies keep their owner-only and store checks.
        with pytest.raises(ProgrammingError) as denied:
            db.add(
                WBRecord(
                    workspace_id=s.workspace_id,
                    store_id=second,
                    source="catalog",
                    record_key="x",
                    ciphertext="bad",
                    updated_at=now(),
                )
            )
            db.flush()
        assert denied.value.orig.sqlstate == "42501"


def test_unrestricted_manager_sees_every_store_of_the_workspace_only(setup):
    s = setup
    second = uuid4()
    with Session(s.admin) as db, db.begin():
        db.add(Store(id=second, workspace_id=s.workspace_id, name="B", marketplace="wildberries"))
    seed(s, Source.CATALOG, [("1", card(article="1"))])
    seed(s, Source.CATALOG, [("2", card(article="2"))], second)
    member(s, s.other_id, "manager", None)
    rows, disagreements = visible(s, s.other_id)
    assert rows == {str(s.store_id): 1, str(second): 1} and disagreements == 0


def test_only_the_stores_table_keeps_the_per_row_function(setup):
    with Session(setup.admin) as db:
        per_row = (
            db.execute(
                text(
                    "SELECT DISTINCT tablename FROM pg_policies WHERE schemaname='public' "
                    "AND (coalesce(qual,'') || coalesce(with_check,'')) LIKE '%perk_store_access(%'"
                )
            )
            .scalars()
            .all()
        )
        set_based = db.scalar(
            text(
                "SELECT count(DISTINCT tablename) FROM pg_policies WHERE schemaname='public' "
                "AND (coalesce(qual,'') || coalesce(with_check,'')) LIKE '%perk_accessible_stores%'"
            )
        )
    assert per_row == ["stores"]
    assert set_based == 35
