from datetime import timedelta
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session
from test_insights_flow import env as env
from test_insights_flow import pytestmark as pytestmark
from test_store_token import strong

from app.integrations.ozon.client import OzonAccess
from app.modules.accounts.models import Store, StoreCredential
from app.modules.accounts.ozon_connection import credential_aad
from app.modules.auth.dependencies import now
from app.modules.auth.models import AuthSession, Membership
from app.modules.sync.models import SyncRun


@pytest.fixture
def ozon(env):
    e = env
    e.ozon_key = "synthetic-" + str(uuid4())
    e.ozon_id = str(uuid4().int % 10**10 + 1)
    e.ozon_access = OzonAccess(
        now() + timedelta(days=60), ("ReadOnly",), ("/v1/roles", "/v3/product/list")
    )
    e.ozon_verify = Mock(return_value=e.ozon_access)
    e.client.app.state.ozon_client.verify = e.ozon_verify
    e.ozon_url = f"/api/v1/workspaces/{e.workspace}/stores/ozon"
    e.ozon_body = {"name": "Ozon synthetic", "client_id": e.ozon_id, "api_key": e.ozon_key}
    e.headers = strong(e, e.owner)
    return e


def connect(e):
    response = e.client.post(e.ozon_url, json=e.ozon_body, headers=e.headers)
    assert response.status_code == 201, response.text
    assert not response.json()["reports_available"]
    return UUID(response.json()["id"])


def saved(e, sid):
    with Session(e.admin) as db:
        row = db.scalar(select(StoreCredential).where(StoreCredential.store_id == sid))
        return row.ciphertext


def test_connect_checks_then_encrypts_and_never_schedules_wb_imports(ozon):
    e = ozon
    sid = connect(e)
    encrypted = saved(e, sid)
    assert e.ozon_key not in encrypted
    plaintext = e.vault.open(encrypted, credential_aad(e.workspace, sid))
    assert e.ozon_key in plaintext and e.ozon_id in plaintext
    e.ozon_verify.assert_called_once_with(e.ozon_id, e.ozon_key)
    with Session(e.admin) as db:
        assert (
            db.scalar(select(func.count()).select_from(SyncRun).where(SyncRun.store_id == sid)) == 0
        )
    listing = e.client.get(f"/api/v1/workspaces/{e.workspace}/stores", headers=e.headers)
    assert {row["id"] for row in listing.json()} == {str(e.store), str(sid)}
    assert e.ozon_key not in listing.text and "ciphertext" not in listing.text
    status = e.client.get(
        f"/api/v1/workspaces/{e.workspace}/stores/{sid}/connection", headers=e.headers
    )
    assert status.json()["client_id"] == e.ozon_id and status.json()["status"] == "connected"
    assert e.ozon_key not in status.text


def test_owner_rights_and_strong_factor_are_checked_before_provider(ozon):
    e = ozon
    with Session(e.admin) as db, db.begin():
        db.execute(
            update(AuthSession).where(AuthSession.user_id == e.owner).values(strong_step_up_at=None)
        )
    unconfirmed = e.client.post(e.ozon_url, json=e.ozon_body, headers=e.headers)
    assert unconfirmed.status_code == 403
    viewer = e.client.post(e.ozon_url, json=e.ozon_body, headers=strong(e, e.viewer))
    assert viewer.status_code in {403, 404}
    assert not e.ozon_verify.called


def test_duplicate_and_bad_key_never_create_another_connection(ozon):
    e = ozon
    sid = connect(e)
    duplicate = e.client.post(e.ozon_url, json=e.ozon_body, headers=e.headers)
    assert duplicate.status_code == 409 and e.ozon_verify.call_count == 1
    e.ozon_verify.side_effect = HTTPException(400, "Ozon rejected the synthetic key")
    rejected = e.client.post(
        e.ozon_url, json={**e.ozon_body, "client_id": str(int(e.ozon_id) + 1)}, headers=e.headers
    )
    assert rejected.status_code == 400
    with Session(e.admin) as db:
        assert (
            db.scalar(
                select(func.count()).select_from(Store).where(Store.workspace_id == e.workspace)
            )
            == 2
        )
    assert saved(e, sid)


def test_key_replacement_preserves_identity_and_rejects_another_cabinet(ozon):
    e = ozon
    sid = connect(e)
    path = f"/api/v1/workspaces/{e.workspace}/stores/{sid}"
    original = saved(e, sid)
    new_key = "synthetic-new-" + str(uuid4())
    wrong = e.client.put(
        path + "/ozon-credential",
        json={"client_id": str(int(e.ozon_id) + 1), "api_key": new_key},
        headers=e.headers,
    )
    assert wrong.status_code == 400 and saved(e, sid) == original
    e.ozon_verify.side_effect = HTTPException(400, "Rejected")
    bad = e.client.put(
        path + "/ozon-credential",
        json={"client_id": e.ozon_id, "api_key": new_key},
        headers=e.headers,
    )
    assert bad.status_code == 400 and saved(e, sid) == original
    e.ozon_verify.side_effect = None
    good = e.client.put(
        path + "/ozon-credential",
        json={"client_id": e.ozon_id, "api_key": new_key},
        headers=e.headers,
    )
    assert good.status_code == 200 and new_key not in good.text
    assert new_key in e.vault.open(saved(e, sid), credential_aad(e.workspace, sid))
    assert good.json()["id"] == str(sid) and good.json()["name"] == "Ozon synthetic"
    checked = e.client.post(path + "/check", headers=e.headers)
    assert checked.status_code == 200 and checked.json()["status"] == "connected"


def test_ozon_cannot_be_read_through_wb_reports_or_capabilities(ozon):
    e = ozon
    sid = connect(e)
    base = f"/api/v1/workspaces/{e.workspace}"
    for path in (
        f"/stores/{sid}/sync-capabilities",
        f"/stores/{sid}/finance/balance",
    ):
        response = e.client.get(base + path, headers=e.headers)
        assert response.status_code == 409, (path, response.text)
        assert response.json()["code"] == "marketplace_not_ready"
    before = e.client.get(base + f"/inventory/overview?store_id={e.store}", headers=e.headers)
    all_stores = e.client.get(base + "/inventory/overview", headers=e.headers)
    assert before.status_code == all_stores.status_code == 200
    assert all_stores.json()["aggregation_status"] == "warehouse_mapping_required"
    assert all_stores.json()["fbs"]["units"] is None
    # The Ozon stock snapshot is not yet ready; the mixed FBO balance is unknown.
    assert all_stores.json()["fbo"]["units"] is None


def test_ozon_input_errors_do_not_echo_keys(ozon):
    e = ozon
    secret = "private-input-that-must-not-appear\nInjected"
    response = e.client.post(e.ozon_url, json={**e.ozon_body, "api_key": secret}, headers=e.headers)
    assert response.status_code == 422 and "private-input" not in response.text
    assert not e.ozon_verify.called


def test_admin_can_connect_but_foreign_workspace_is_hidden(ozon):
    e = ozon
    with Session(e.admin) as db, db.begin():
        member = db.scalar(select(Membership).where(Membership.user_id == e.viewer))
        member.role = "admin"
    headers = strong(e, e.viewer)
    foreign = e.client.post(
        f"/api/v1/workspaces/{uuid4()}/stores/ozon", json=e.ozon_body, headers=headers
    )
    assert foreign.status_code == 404 and not e.ozon_verify.called
    response = e.client.post(e.ozon_url, json=e.ozon_body, headers=headers)
    assert response.status_code == 201, response.text


def test_a_stale_check_cannot_overwrite_a_replaced_key(ozon):
    from app.modules.accounts.ozon_connection import seal

    e = ozon
    sid = connect(e)
    next_key = "synthetic-concurrent-" + str(uuid4())

    def replace_during_check(_client_id, _key):
        with Session(e.admin) as db, db.begin():
            store = db.get(Store, sid)
            credential = db.scalar(select(StoreCredential).where(StoreCredential.store_id == sid))
            credential.ciphertext = seal(e.vault, store, e.ozon_id, next_key, e.ozon_access)
        return e.ozon_access

    e.ozon_verify.side_effect = replace_during_check
    response = e.client.post(
        f"/api/v1/workspaces/{e.workspace}/stores/{sid}/check", headers=e.headers
    )
    assert response.status_code == 409 and response.json()["code"] == "credential_changed"
    assert next_key in e.vault.open(saved(e, sid), credential_aad(e.workspace, sid))


def test_wb_background_reports_and_notifications_ignore_connection_only_ozon(ozon, monkeypatch):
    from app.db.session import set_actor
    from app.modules.notifications import service as notifications
    from app.workers.tasks import member_store

    e = ozon
    sid = connect(e)
    visited = []

    def alert(_db, _vault, _user, store, _day):
        visited.append(store.id)
        return 0

    monkeypatch.setattr(notifications, "store_alerts", alert)
    with Session(e.engine) as db, db.begin():
        set_actor(db, e.owner)
        assert member_store(db, e.workspace, e.store, e.owner) is not None
        assert member_store(db, e.workspace, sid, e.owner) is None
        settings = notifications.settings_for(db, e.owner)
        settings.alerts_enabled = True
        settings.digest_enabled = False
        notifications.generate(db, e.vault, e.owner)
    assert visited == [e.store]
