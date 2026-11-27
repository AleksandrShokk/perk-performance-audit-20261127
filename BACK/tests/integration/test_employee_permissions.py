"""Real API + PostgreSQL checks for employee grants, links and registration."""

from datetime import timedelta
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.orm import Session
from test_insights_flow import PASSWORD
from test_insights_flow import env as env
from test_insights_flow import pytestmark as pytestmark
from test_team_access import invite_code
from test_team_access import outsider as outsider

from app.db.session import set_actor
from app.modules.accounts.models import Store, Workspace
from app.modules.auth.dependencies import now
from app.modules.auth.models import AuthSession, Membership, User
from app.modules.sync.schemas import moscow_today


def grant(env, user_id, role, permissions=None, stores=None):
    with Session(env.admin) as db, db.begin():
        member = db.get(Membership, (user_id, env.workspace))
        if member is None:
            member = Membership(user_id=user_id, workspace_id=env.workspace, role=role)
            db.add(member)
        member.role, member.permissions, member.store_ids = role, permissions, stores


def strong(env, user_id):
    with Session(env.admin) as db, db.begin():
        db.get(User, user_id).phone_verified_at = now()
        db.execute(
            update(AuthSession)
            .where(AuthSession.user_id == user_id)
            .values(strong_step_up_at=now())
        )


def period():
    end = moscow_today() - timedelta(days=1)
    return {"date_from": str(end - timedelta(days=6)), "date_to": str(end)}


def test_invitation_requires_phone_and_cannot_be_forwarded_or_replayed(env, outsider):
    owner, employee = env.login(env.owner), env.login(outsider)
    created = env.client.post(
        f"/api/v1/workspaces/{env.workspace}/invites",
        headers=owner,
        json={"email": env.emails[outsider], "role": "manager", "store_ids": [str(env.store)]},
    )
    assert created.status_code == 201
    code = invite_code(env, env.emails[outsider])
    assert "#code=" + code in env.inbox.emails[-1][1]
    assert "token_digest" not in created.text and code not in created.text
    preview = env.client.post("/api/v1/invites/preview", json={"code": code})
    assert preview.status_code == 200 and preview.json()["email"] == env.emails[outsider]
    assert (
        env.client.post("/api/v1/invites/accept", json={"code": code}, headers=owner).status_code
        == 404
    )
    with Session(env.admin) as db, db.begin():
        db.get(User, outsider).phone_verified_at = None
    denied = env.client.post("/api/v1/invites/accept", json={"code": code}, headers=employee)
    assert denied.status_code == 403 and denied.json()["code"] == "phone_required"
    with Session(env.admin) as db, db.begin():
        db.get(User, outsider).phone_verified_at = now()
    assert (
        env.client.post("/api/v1/invites/accept", json={"code": code}, headers=employee).status_code
        == 200
    )
    assert (
        env.client.post("/api/v1/invites/accept", json={"code": code}, headers=employee).status_code
        == 404
    )
    assert env.client.post("/api/v1/invites/preview", json={"code": code}).status_code == 404


def test_manager_is_scoped_in_lists_totals_and_direct_database_reads(env):
    second = uuid4()
    with Session(env.admin) as db, db.begin():
        db.add(
            Store(id=second, workspace_id=env.workspace, name="Closed", marketplace="wildberries")
        )
    grant(env, env.viewer, "manager", stores=[str(env.store)])
    headers = env.login(env.viewer)
    root = f"/api/v1/workspaces/{env.workspace}"
    listed = env.client.get(root + "/stores", headers=headers)
    assert [item["id"] for item in listed.json()] == [str(env.store)]
    assert (
        env.client.get(env.base + "/insights/funnel", params=period(), headers=headers).status_code
        == 200
    )
    assert (
        env.client.get(env.base + "/finance/summary", params=period(), headers=headers).status_code
        == 403
    )
    assert env.client.get(env.base + "/data/finance", headers=headers).status_code == 403
    assert (
        env.client.get(root + f"/stores/{second}/inventory/forecast", headers=headers).status_code
        == 404
    )
    business = env.client.get(
        root + "/business", params={**period(), "topic": "overview"}, headers=headers
    )
    assert business.status_code == 200, business.text
    assert business.json()["total_stores"] == 1
    assert business.json()["finance"]["summary"]["revenue"] is None
    assert business.json()["balances"] == []
    assert business.json()["stores"][0]["finance"]["summary"]["profit_before_tax"] is None
    with Session(env.engine) as db, db.begin():
        set_actor(db, env.viewer)
        assert db.get(Store, second) is None
        assert {row.id for row in db.scalars(select(Store))} == {env.store}


def test_admin_has_all_sections_can_manage_team_and_cannot_remove_creator(env, outsider):
    owner = env.login(env.owner)
    strong(env, env.owner)
    root = f"/api/v1/workspaces/{env.workspace}"
    created = env.client.post(
        root + "/invites", json={"email": env.emails[outsider], "role": "admin"}, headers=owner
    )
    assert created.status_code == 201, created.text
    employee = env.login(outsider)
    code = invite_code(env, env.emails[outsider])
    assert (
        env.client.post("/api/v1/invites/accept", json={"code": code}, headers=employee).status_code
        == 200
    )
    assert env.client.get(root + "/team", headers=employee).status_code == 200
    assert env.client.get(env.base + "/dashboard", headers=employee).status_code == 200
    assert env.client.get(env.base + "/connection", headers=employee).status_code == 200
    workspaces = env.client.get("/api/v1/workspaces", headers=employee).json()
    member = next(row for row in workspaces if row["id"] == str(env.workspace))
    assert member["role"] == "admin" and len(member["permissions"]) == 8
    assert (
        env.client.post(
            root + "/invites",
            json={"email": "colleague@example.com", "role": "manager"},
            headers=employee,
        ).status_code
        == 201
    )
    assert env.client.delete(root + f"/members/{env.owner}", headers=employee).status_code == 409


def test_custom_permissions_are_enforced_for_writes_and_revocation(env):
    headers = env.login(env.viewer)
    grant(env, env.viewer, "accountant", ["finance.read", "expenses.write"], [str(env.store)])
    root = f"/api/v1/workspaces/{env.workspace}"
    assert (
        env.client.get(root + "/finance/overview", params=period(), headers=headers).status_code
        == 200
    )
    assert env.client.get(env.base + "/costs", headers=headers).status_code == 403
    assert (
        env.client.get(env.base + "/insights/funnel", params=period(), headers=headers).status_code
        == 403
    )
    data = {
        "date": str(moscow_today() - timedelta(days=1)),
        "amount": "10",
        "currency": "RUB",
        "category": "other",
        "comment": "Test",
    }
    # The operation uses the real finance permission and database write policies.
    schema = env.client.app.openapi()["components"]["schemas"]["ExpenseInput"]["properties"]
    if "expense_date" in schema:
        data["expense_date"] = data.pop("date")
    created = env.client.post(env.base + "/expenses", json=data, headers=headers)
    assert created.status_code == 201, created.text
    grant(env, env.viewer, "viewer", [], [str(env.store)])
    assert (
        env.client.get(root + "/finance/overview", params=period(), headers=headers).status_code
        == 403
    )
    assert env.client.post(env.base + "/expenses", json=data, headers=headers).status_code == 403
    assert env.client.post(env.base + "/cost-imports", headers=headers).status_code == 403


def test_resend_invalidates_old_link_and_foreign_stores_are_rejected(env, outsider):
    headers = env.login(env.owner)
    root = f"/api/v1/workspaces/{env.workspace}"
    created = env.client.post(
        root + "/invites", json={"email": env.emails[outsider]}, headers=headers
    )
    old = invite_code(env, env.emails[outsider])
    sent = env.client.post(root + f"/invites/{created.json()['id']}/resend", headers=headers)
    assert sent.status_code == 200
    new = invite_code(env, env.emails[outsider])
    assert new != old
    assert env.client.post("/api/v1/invites/preview", json={"code": old}).status_code == 404
    assert env.client.post("/api/v1/invites/preview", json={"code": new}).status_code == 200
    invalid = env.client.post(
        root + "/invites",
        json={"email": "other@example.com", "store_ids": [str(uuid4())]},
        headers=headers,
    )
    assert invalid.status_code == 422
    unknown = env.client.post(
        root + "/invites",
        json={"email": "other@example.com", "permissions": ["root.access"]},
        headers=headers,
    )
    assert unknown.status_code == 422


def test_registration_from_link_creates_no_empty_owned_workspace(env):
    email = f"{uuid4().hex}@example.com"
    headers = env.login(env.owner)
    root = f"/api/v1/workspaces/{env.workspace}"
    env.client.post(
        root + "/invites",
        json={"email": email, "role": "manager", "store_ids": [str(env.store)]},
        headers=headers,
    )
    code = invite_code(env, email)
    response = env.client.post(
        "/api/v1/auth/register", json={"email": email, "password": PASSWORD, "invite_code": code}
    )
    assert response.status_code == 202, response.text
    verified = env.client.post(
        "/api/v1/auth/register/verify",
        json={"challenge_id": response.json()["challenge_id"], "code": env.inbox.code(email)},
    )
    assert verified.status_code == 201, verified.text
    token = {"Authorization": "Bearer " + verified.json()["access_token"]}
    user_id = env.client.get("/api/v1/auth/me", headers=token).json()["id"]
    env.emails[user_id] = email
    with Session(env.admin) as db:
        assert db.scalars(select(Workspace).where(Workspace.owner_user_id == user_id)).all() == []
    assert env.client.get("/api/v1/workspaces", headers=token).json() == []
    assert (
        env.client.post("/api/v1/invites/accept", json={"code": code}, headers=token).json()["code"]
        == "phone_required"
    )
    # Use the actual phone-code endpoints, with the fixture's fake delivery transport.
    delivered = []
    env.inbox.send_phone_code = lambda channel, phone, otp, ttl: delivered.append(otp)
    started = env.client.post(
        "/api/v1/auth/phone", json={"phone": "+79001234567", "channel": "telegram"}, headers=token
    )
    assert started.status_code == 202, started.text
    confirmed = env.client.post(
        "/api/v1/auth/phone/confirm", json={"code": delivered[-1]}, headers=token
    )
    assert confirmed.status_code == 200, confirmed.text
    accepted = env.client.post("/api/v1/invites/accept", json={"code": code}, headers=token)
    assert accepted.status_code == 200, accepted.text
    assert env.client.get(root + "/stores", headers=token).status_code == 200
