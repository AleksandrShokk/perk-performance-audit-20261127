"""Synthetic WB credentials only. These tests never contact or change a real shop."""

import base64
import json
import time
from datetime import timedelta
from unittest.mock import Mock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session
from test_insights_flow import env as env
from test_insights_flow import pytestmark as pytestmark

from app.modules.accounts.models import Store, StoreCredential
from app.modules.audit.models import AuditEvent
from app.modules.auth.dependencies import now
from app.modules.auth.models import AuthSession, Membership, User
from app.modules.sync.models import SyncRun, SyncSchedule, WBRecord


def jwt(seller, *, scopes=(1, 2, 3, 4, 5, 13), token_type=3, readonly=True, expiry=None):
    def encode(value):
        return base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")

    return ".".join(
        [
            encode({"alg": "HS256"}),
            encode(
                {
                    "sid": str(seller),
                    "s": sum(1 << bit for bit in scopes) | ((1 << 30) if readonly else 0),
                    "exp": expiry if expiry is not None else int(time.time()) + 86400,
                    "t": False,
                    "acc": token_type,
                    "nonce": str(uuid4()),
                }
            ),
            "synthetic-signature",
        ]
    )


def strong(e, user):
    headers = e.login(user)
    with Session(e.admin) as db, db.begin():
        db.get(User, user).phone_verified_at = now()
        db.execute(
            update(AuthSession).where(AuthSession.user_id == user).values(strong_step_up_at=now())
        )
    return headers


@pytest.fixture
def token_store(env):
    e = env
    with Session(e.admin) as db, db.begin():
        seller = db.get(Store, e.store).external_seller_id
        old = jwt(seller, scopes=(1, 2, 5, 13))
        cred = db.scalar(select(StoreCredential).where(StoreCredential.store_id == e.store))
        cred.ciphertext = e.vault.seal(old, f"wb:{e.workspace}:{e.store}")
        cred.scopes = "content,analytics,statistics,finance"
    verify = Mock(side_effect=lambda raw, meta: meta)
    e.client.app.state.wb_client.verify = verify
    yield e, seller, old, verify


def saved_token(e):
    with Session(e.admin) as db:
        cred = db.scalar(select(StoreCredential).where(StoreCredential.store_id == e.store))
        return e.vault.open(cred.ciphertext, f"wb:{e.workspace}:{e.store}")


def test_replace_preserves_store_and_reports_and_never_returns_the_token(token_store):
    e, seller, old, verify = token_store
    headers = strong(e, e.owner)
    new = jwt(seller)
    with Session(e.admin) as db:
        before = {
            row.record_key: row.ciphertext
            for row in db.scalars(select(WBRecord).where(WBRecord.store_id == e.store))
        }
        original = db.get(Store, e.store)
        name, created = original.name, original.created_at
    response = e.client.put(e.base + "/credential", json={"token": new}, headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["id"] == str(e.store) and response.json()["name"] == name
    assert (
        new not in response.text and old not in response.text and "ciphertext" not in response.text
    )
    assert saved_token(e) == new
    status = e.client.get(e.base + "/connection", headers=headers)
    assert status.status_code == 200 and status.json()["status"] == "connected"
    assert {"marketplace", "prices", "analytics"} <= set(status.json()["scopes"])
    assert status.json()["expires_at"]
    assert new not in status.text and old not in status.text
    with Session(e.admin) as db:
        assert db.get(Store, e.store).created_at == created
        after = {
            row.record_key: row.ciphertext
            for row in db.scalars(select(WBRecord).where(WBRecord.store_id == e.store))
        }
        assert before == after
        events = db.scalars(
            select(AuditEvent).where(
                AuditEvent.workspace_id == e.workspace,
                AuditEvent.action == "store.credential_replaced",
            )
        ).all()
        assert len(events) == 1 and events[0].target_id == e.store


@pytest.mark.parametrize("kind", ["another_seller", "expired", "write_access", "wb_rejected"])
def test_invalid_replacement_keeps_previous_credential_and_store_state(token_store, kind):
    e, seller, old, verify = token_store
    headers = strong(e, e.owner)
    new = jwt(
        uuid4() if kind == "another_seller" else seller,
        expiry=int(time.time()) - 60 if kind == "expired" else None,
        readonly=kind != "write_access",
    )
    if kind == "wb_rejected":
        verify.side_effect = HTTPException(400, "WB rejected the token")
    response = e.client.put(e.base + "/credential", json={"token": new}, headers=headers)
    assert response.status_code == 400, response.text
    assert saved_token(e) == old
    assert new not in response.text and old not in response.text
    with Session(e.admin) as db:
        assert db.get(Store, e.store).connection_status == "connected"
        assert (
            db.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(
                    AuditEvent.action == "store.credential_replaced",
                    AuditEvent.workspace_id == e.workspace,
                )
            )
            == 0
        )


def test_viewer_cannot_replace_but_admin_with_strong_confirmation_can(token_store):
    e, seller, old, verify = token_store
    headers = strong(e, e.viewer)
    new = jwt(seller)
    denied = e.client.put(e.base + "/credential", json={"token": new}, headers=headers)
    assert denied.status_code in {403, 404} and saved_token(e) == old
    assert not verify.called
    with Session(e.admin) as db, db.begin():
        db.get(Membership, (e.viewer, e.workspace)).role = "admin"
    success = e.client.put(e.base + "/credential", json={"token": new}, headers=headers)
    assert success.status_code == 200, success.text
    assert saved_token(e) == new


def test_expired_confirmation_requests_step_up_before_validating_the_key(token_store):
    e, seller, old, verify = token_store
    headers = strong(e, e.owner)
    with Session(e.admin) as db, db.begin():
        db.execute(
            update(AuthSession)
            .where(AuthSession.user_id == e.owner)
            .values(strong_step_up_at=now() - timedelta(minutes=6))
        )
    response = e.client.put(e.base + "/credential", json={"token": jwt(seller)}, headers=headers)
    assert response.status_code == 403 and response.json()["code"] == "step_up_required"
    assert response.json()["detail"]["strong"] and not verify.called and saved_token(e) == old


def test_replacement_resumes_authorized_plans_without_resetting_history_or_quotas(token_store):
    e, seller, old, verify = token_store
    headers = strong(e, e.owner)
    tomorrow = now() + timedelta(days=1)
    with Session(e.admin) as db, db.begin():
        for source, enabled, error in [
            ("stocks", True, None),
            ("fbs", False, "wb_scope_missing"),
            ("finance", False, None),
        ]:
            db.add(
                SyncSchedule(
                    workspace_id=e.workspace,
                    store_id=e.store,
                    source=source,
                    requested_by=e.owner,
                    enabled=enabled,
                    error_code=error,
                    recent_days=28,
                    recent_completed=True,
                    next_refresh_at=tomorrow,
                    next_attempt_at=tomorrow,
                    reconcile_at=tomorrow,
                    history_from=now().date() - timedelta(days=90),
                    backfill_to=now().date() - timedelta(days=30),
                )
            )
        pending = SyncRun(
            workspace_id=e.workspace,
            store_id=e.store,
            source="stocks",
            status="queued",
            requested_by=e.owner,
            cursor={"offset": 10000},
        )
        db.add(pending)
        db.flush()
        pending_id = pending.id
    response = e.client.put(e.base + "/credential", json={"token": jwt(seller)}, headers=headers)
    assert response.status_code == 200, response.text
    with Session(e.admin) as db:
        for source in ("stocks", "fbs"):
            plan = db.get(SyncSchedule, (e.workspace, e.store, source))
            assert plan.enabled and plan.error_code is None
            assert plan.next_refresh_at < tomorrow and plan.next_attempt_at < tomorrow
            assert plan.recent_completed and plan.history_from and plan.backfill_to
        assert not db.get(SyncSchedule, (e.workspace, e.store, "finance")).enabled
        assert db.get(SyncRun, pending_id).cursor == {"offset": 10000}


def test_removed_scopes_disable_only_the_affected_plans(token_store):
    e, seller, old, verify = token_store
    headers = strong(e, e.owner)
    with Session(e.admin) as db, db.begin():
        for source in ("stock_history", "fbs"):
            db.add(
                SyncSchedule(
                    workspace_id=e.workspace,
                    store_id=e.store,
                    source=source,
                    requested_by=e.owner,
                    enabled=True,
                    next_refresh_at=now(),
                    next_attempt_at=now(),
                    reconcile_at=now(),
                )
            )
    response = e.client.put(
        e.base + "/credential", json={"token": jwt(seller, scopes=(2,))}, headers=headers
    )
    assert response.status_code == 200, response.text
    with Session(e.admin) as db:
        assert db.get(SyncSchedule, (e.workspace, e.store, "stock_history")).enabled
        fbs = db.get(SyncSchedule, (e.workspace, e.store, "fbs"))
        assert not fbs.enabled and fbs.error_code == "wb_scope_missing"


def test_token_type_change_resumes_funnel_summary_without_erasing_same_type_quota(token_store):
    from app.integrations.wildberries.client import inspect_token
    from app.modules.sync.quota import addresses

    e, seller, old, verify = token_store
    headers = strong(e, e.owner)
    basic = jwt(seller, token_type=1)
    new = jwt(seller)
    personal = inspect_token(new)
    with Session(e.admin) as db, db.begin():
        cred = db.scalar(select(StoreCredential).where(StoreCredential.store_id == e.store))
        cred.ciphertext = e.vault.seal(basic, f"wb:{e.workspace}:{e.store}")
        run = SyncRun(
            workspace_id=e.workspace,
            store_id=e.store,
            source="funnel_summary",
            status="queued",
            requested_by=e.owner,
            error_code="wb_rate_limited",
            cursor={"offset": 1000},
            date_from=now().date() - timedelta(days=28),
            date_to=now().date() - timedelta(days=1),
        )
        db.add(run)
        db.flush()
        run_id = run.id
    key, _, _ = addresses(e.vault, "funnel", personal)
    e.client.app.state.redis.set(key, "1", ex=120)
    response = e.client.put(e.base + "/credential", json={"token": new}, headers=headers)
    assert response.status_code == 200, response.text
    with Session(e.admin) as db:
        run = db.get(SyncRun, run_id)
        assert run.error_code is None and run.cursor == {"offset": 1000}
        assert run.next_attempt_at > now() + timedelta(seconds=100)
    assert e.client.app.state.redis.ttl(key) > 100
