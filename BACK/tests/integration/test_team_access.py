"""Team invitation flows and direct runtime-role RLS (not only HTTP permission checks)."""

import re
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import delete, select, text, update
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session
from test_insights_flow import PASSWORD
from test_insights_flow import env as env
from test_insights_flow import pytestmark as pytestmark

from app.db.session import set_actor
from app.modules.accounts.models import Store, StoreCredential, Workspace, WorkspaceInvite
from app.modules.audit.models import AuditEvent
from app.modules.auth.dependencies import now
from app.modules.auth.models import AuthSession, Membership, User
from app.security.crypto import PASSWORD_HASHER


@pytest.fixture
def outsider(env):
    user_id = uuid4()
    email = f"{user_id.hex}@example.com"
    env.emails[user_id] = email  # Existing env teardown removes the account after the workspace.
    with Session(env.admin) as db, db.begin():
        db.add(
            User(
                id=user_id,
                email=email,
                email_verified_at=now(),
                password_hash=PASSWORD_HASHER.hash(PASSWORD),
                phone="+7" + str(9000000000 + user_id.int % 999999999),
                phone_verified_at=now(),
            )
        )
    env.inbox.send_phone_code = lambda channel, phone, code, ttl: env.inbox.emails.append(
        (email, f"Код: {code}")
    )
    return user_id


def invite_code(env, address):
    body = next(
        body for email, body in reversed(env.inbox.emails) if email == address and "pw_" in body
    )
    return re.search(r"pw_[A-Za-z0-9_-]{43}", body)[0]


def test_invited_address_joins_once_and_can_be_removed(env, outsider):
    owner = env.login(env.owner)
    outside = env.login(outsider)
    path = f"/api/v1/workspaces/{env.workspace}"
    assert env.client.get(env.base + "/dashboard", headers=outside).status_code == 404
    response = env.client.post(
        path + "/invites", json={"email": env.emails[outsider]}, headers=owner
    )
    assert response.status_code == 201, response.text
    assert "token_digest" not in response.json()
    code = invite_code(env, env.emails[outsider])
    assert code not in response.text

    # Possessing the code is insufficient: it belongs to the recipient's verified address.
    wrong = env.client.post("/api/v1/invites/accept", json={"code": code}, headers=owner)
    assert wrong.status_code == 404
    accepted = env.client.post("/api/v1/invites/accept", json={"code": code}, headers=outside)
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["workspace_id"] == str(env.workspace)
    assert (
        env.client.post("/api/v1/invites/accept", json={"code": code}, headers=outside).status_code
        == 404
    )
    assert env.client.get(env.base + "/dashboard", headers=outside).status_code == 200
    assert env.client.get(path + "/team", headers=outside).status_code == 404
    assert (
        env.client.post(
            env.base + "/events",
            json={"day": str(now().date()), "kind": "other", "title": "x"},
            headers=outside,
        ).status_code
        == 404
    )
    team = env.client.get(path + "/team", headers=owner).json()
    member = next(item for item in team["members"] if item["user_id"] == str(outsider))
    assert member["role"] == "viewer" and not member["is_creator"]
    assert team["invites"] == []
    removed = env.client.delete(path + f"/members/{outsider}", headers=owner)
    assert removed.status_code == 200, removed.text
    assert env.client.get(env.base + "/dashboard", headers=outside).status_code == 404


def test_invites_can_be_cancelled_and_expire(env, outsider):
    owner = env.login(env.owner)
    outside = env.login(outsider)
    path = f"/api/v1/workspaces/{env.workspace}/invites"
    created = env.client.post(path, json={"email": env.emails[outsider]}, headers=owner)
    code = invite_code(env, env.emails[outsider])
    assert env.client.delete(path + "/" + created.json()["id"], headers=owner).status_code == 204
    assert (
        env.client.post("/api/v1/invites/accept", json={"code": code}, headers=outside).status_code
        == 404
    )
    created = env.client.post(path, json={"email": env.emails[outsider]}, headers=owner)
    code = invite_code(env, env.emails[outsider])
    with Session(env.admin) as db, db.begin():
        db.get(WorkspaceInvite, created.json()["id"]).expires_at = now() - timedelta(seconds=1)
    assert (
        env.client.post("/api/v1/invites/accept", json={"code": code}, headers=outside).status_code
        == 404
    )


def test_owner_grant_needs_strong_confirmation_and_creator_is_protected(env, outsider):
    owner = env.login(env.owner)
    path = f"/api/v1/workspaces/{env.workspace}"
    before = env.client.post(
        path + "/invites", json={"email": env.emails[outsider], "role": "owner"}, headers=owner
    )
    assert before.status_code == 403 and before.json()["code"] == "strong_factor_required"
    assert env.client.delete(path + f"/members/{env.owner}", headers=owner).status_code == 409
    # Simulate a phone-confirmed session; the phone-code flow has its own integration suite.
    with Session(env.admin) as db, db.begin():
        db.get(User, env.owner).phone_verified_at = now()
        db.execute(
            update(AuthSession)
            .where(AuthSession.user_id == env.owner)
            .values(strong_step_up_at=now())
        )
    granted = env.client.put(path + f"/members/{env.viewer}", json={"role": "owner"}, headers=owner)
    assert granted.status_code == 200, granted.text
    assert granted.json()["role"] == "owner"
    protected = env.client.put(
        path + f"/members/{env.owner}", json={"role": "viewer"}, headers=owner
    )
    assert protected.status_code == 409


def test_member_can_leave_and_revoked_owner_invites_cannot_be_accepted(env, outsider):
    owner = env.login(env.owner)
    viewer = env.login(env.viewer)
    outside = env.login(outsider)
    path = f"/api/v1/workspaces/{env.workspace}"
    with Session(env.admin) as db, db.begin():
        db.get(Membership, (env.viewer, env.workspace)).role = "owner"
    created = env.client.post(
        path + "/invites", json={"email": env.emails[outsider]}, headers=viewer
    )
    assert created.status_code == 201
    code = invite_code(env, env.emails[outsider])
    removed = env.client.delete(path + f"/members/{env.viewer}", headers=viewer)
    assert removed.status_code == 200, removed.text
    assert (
        env.client.post("/api/v1/invites/accept", json={"code": code}, headers=outside).status_code
        == 404
    )
    assert env.client.get(env.base + "/dashboard", headers=viewer).status_code == 404
    assert env.client.get(path + "/team", headers=owner).status_code == 200


@pytest.mark.parametrize("actor", [None, "outsider"])
def test_tenant_metadata_is_hidden_without_a_membership(env, outsider, actor):
    with Session(env.engine) as db, db.begin():
        if actor:
            set_actor(db, outsider)
        for model in (Workspace, Store, StoreCredential, Membership, WorkspaceInvite):
            assert db.scalars(select(model)).all() == [], model.__tablename__
        assert db.execute(delete(Store).where(Store.id == env.store)).rowcount == 0
    with Session(env.engine) as db, db.begin():
        if actor:
            set_actor(db, outsider)
        with pytest.raises(ProgrammingError), db.begin_nested():
            db.add(Store(workspace_id=env.workspace, name="forbidden", marketplace="wildberries"))
            db.flush()


def test_viewer_can_read_but_cannot_escalate_or_write_credentials(env):
    with Session(env.engine) as db, db.begin():
        set_actor(db, env.viewer)
        assert db.get(Store, env.store) is not None
        assert db.scalars(select(Membership)).all()
        assert (
            db.execute(
                update(Membership).where(Membership.user_id == env.viewer).values(role="owner")
            ).rowcount
            == 0
        )
        assert db.execute(delete(StoreCredential)).rowcount == 0
        assert db.execute(update(Store).values(name="hacked")).rowcount == 0


def test_creator_is_protected_at_database_level_too(env):
    with Session(env.engine) as db, db.begin():
        set_actor(db, env.owner)
        assert db.execute(delete(Membership).where(Membership.user_id == env.owner)).rowcount == 0
        assert (
            db.execute(
                update(Membership).where(Membership.user_id == env.owner).values(role="viewer")
            ).rowcount
            == 0
        )
        with pytest.raises(ProgrammingError), db.begin_nested():
            db.execute(update(Workspace).values(owner_user_id=env.viewer))


def test_audit_logs_are_append_only_and_private_and_actor_does_not_leak(env):
    from app.modules.audit.service import audit

    with Session(env.engine) as db, db.begin():
        set_actor(db, env.owner)
        audit(db, "test.private", user_id=env.owner)
        audit(db, "test.workspace", user_id=env.owner, workspace_id=env.workspace)
    with Session(env.engine) as db, db.begin():
        set_actor(db, env.viewer)
        assert db.scalars(select(AuditEvent).where(AuditEvent.action.like("test.%"))).all() == []
        with pytest.raises(ProgrammingError), db.begin_nested():
            db.execute(delete(AuditEvent))  # No table-level permission, even with actor.
    with Session(env.engine) as db:
        set_actor(db, env.owner)
        assert db.get(Store, env.store) is not None
        db.commit()
        assert db.scalar(text("SELECT perk_actor()")) is None
        assert db.scalars(select(Store)).all() == []


def test_background_discovery_and_notifications_work_with_forced_rls(env):
    from unittest.mock import patch

    from app.modules.notifications.models import Notification
    from app.workers.tasks import dispatch_notifications, warm_all_insights

    headers = env.login(env.owner)
    assert env.client.get(env.base + "/inventory/forecast", headers=headers).status_code == 200
    with patch("app.workers.tasks.warm_insights") as warm:
        warm_all_insights()
    assert any(
        call.args[2:] == (env.workspace, env.store, env.owner) for call in warm.call_args_list
    )
    with patch(
        "app.integrations.notifications.build_messenger", return_value=(env.inbox, env.inbox)
    ):
        dispatch_notifications()
    with Session(env.admin) as db:
        for user in (env.owner, env.viewer):
            kinds = set(db.scalars(select(Notification.kind).where(Notification.user_id == user)))
            assert "stock" in kinds
        if user == env.owner:
            assert "token_expiring" in kinds
