import os
import re
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import build_engine
from app.main import create_app
from app.modules.accounts.models import Workspace
from app.modules.auth.dependencies import now
from app.modules.auth.models import AuthSession, Membership, OtpChallenge, User
from app.security.crypto import PASSWORD_HASHER

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("PERK_INTEGRATION_TESTS") != "1",
        reason="Requires disposable PostgreSQL test stack",
    ),
]
PASSWORD = "correct horse battery staple"
PHONE = "+79001234567"


class Inbox:
    """Captures deliveries instead of sending real emails or Telegram/SMS messages."""

    def __init__(self):
        self.emails, self.phone = [], []

    def phone_channels(self):
        return ["telegram", "sms"]

    def send_email(self, to, subject, body, *, html=None):
        self.emails.append((to, subject, body))

    def send_phone_code(self, channel, phone, code, ttl):
        self.phone.append((channel, phone, code))

    def email_code(self, to):
        body = next(body for address, _, body in reversed(self.emails) if address == to)
        return re.search(r": (\d{6})", body)[1]


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
    emails = []
    with TestClient(create_app(settings)) as client:
        inbox = Inbox()
        client.app.state.notifier = inbox

        def reset_limits():
            redis = client.app.state.redis
            keys = list(redis.scan_iter("perk:limit:*"))
            if keys:
                redis.delete(*keys)

        def email():
            value = f"{uuid4().hex}@example.com"
            emails.append(value)
            return value

        reset_limits()
        yield client, inbox, admin, reset_limits, email
    with Session(admin) as db, db.begin():
        ids = db.scalars(select(User.id).where(User.email.in_(emails))).all()
        db.execute(delete(Workspace).where(Workspace.owner_user_id.in_(ids)))
        db.execute(delete(User).where(User.id.in_(ids)))
    admin.dispose()


def bearer(tokens):
    return {"Authorization": "Bearer " + tokens["access_token"]}


def create_user(admin, email, *, phone=None):
    with Session(admin) as db, db.begin():
        user = User(
            email=email,
            password_hash=PASSWORD_HASHER.hash(PASSWORD),
            email_verified_at=now(),
            phone=phone,
            phone_verified_at=now() if phone else None,
            phone_channel="telegram" if phone else None,
        )
        db.add(user)
        db.flush()
        workspace = Workspace(name="Auth test", owner_user_id=user.id)
        db.add(workspace)
        db.flush()
        db.add(Membership(user_id=user.id, workspace_id=workspace.id, role="owner"))
        return user.id, workspace.id


def login(client, email, password=PASSWORD):
    response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return response.json()


def test_registration_creates_account_only_after_email_code(env):
    client, inbox, admin, _, new_email = env
    email = new_email()
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": PASSWORD, "workspace_name": "  Магазин  "},
    )
    assert response.status_code == 202
    challenge = response.json()
    assert challenge["destination"].endswith("@example.com") and "***" in challenge["destination"]
    with Session(admin) as db:
        assert db.scalar(select(User.id).where(User.email == email)) is None
        stored = db.get(OtpChallenge, challenge["challenge_id"])
        assert PASSWORD not in (stored.payload_ciphertext or "")

    code = inbox.email_code(email)
    wrong = "000000" if code != "000000" else "111111"
    path = "/api/v1/auth/register/verify"
    invalid = client.post(path, json={"challenge_id": challenge["challenge_id"], "code": wrong})
    assert invalid.status_code == 400
    assert invalid.json()["detail"]["attempts_left"] == 4

    created = client.post(path, json={"challenge_id": challenge["challenge_id"], "code": code})
    assert created.status_code == 201, created.text
    tokens = created.json()
    assert tokens["mfa_required"] is False
    me = client.get("/api/v1/auth/me", headers=bearer(tokens)).json()
    assert me["email_verified"] and me["session_mfa_verified"]
    assert not me["strong_factor_enabled"]
    workspaces = client.get("/api/v1/workspaces", headers=bearer(tokens)).json()
    assert [item["name"] for item in workspaces] == ["Магазин"]
    # The consumed code cannot create a second account.
    again = client.post(path, json={"challenge_id": challenge["challenge_id"], "code": code})
    assert again.status_code == 400


def test_registration_of_existing_address_looks_identical_but_sends_no_code(env):
    client, inbox, admin, _, new_email = env
    email = new_email()
    create_user(admin, email)
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": PASSWORD, "workspace_name": "Чужой"},
    )
    assert response.status_code == 202
    assert set(response.json()) == {
        "challenge_id",
        "channel",
        "destination",
        "expires_in",
        "resend_after",
    }
    to, subject, body = inbox.emails[-1]
    assert to == email and "уже существует" in body
    assert not re.search(r"\d{6}", body)
    for guess in ("000000", "123456"):
        attempt = client.post(
            "/api/v1/auth/register/verify",
            json={"challenge_id": response.json()["challenge_id"], "code": guess},
        )
        assert attempt.status_code == 400


def test_resend_is_throttled(env):
    client, _, _, _, new_email = env
    email = new_email()
    first = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": PASSWORD, "workspace_name": "Shop"},
    )
    resend = client.post(
        "/api/v1/auth/register/resend", json={"challenge_id": first.json()["challenge_id"]}
    )
    assert resend.status_code == 429


def test_login_is_not_blocked_by_background_rows_referencing_the_user(env):
    client, _, admin, _, new_email = env
    email = new_email()
    user_id, _ = create_user(admin, email)
    # A long import transaction inserting rows with a foreign key to the user holds KEY SHARE.
    with Session(admin) as db, db.begin():
        held = select(User.id).where(User.id == user_id)
        db.scalar(held.with_for_update(read=True, key_share=True))
        assert login(client, email)["mfa_required"] is True


def test_login_uses_email_until_phone_is_added_then_never_email(env):
    client, inbox, admin, reset_limits, new_email = env
    email = new_email()
    _, workspace_id = create_user(admin, email)

    pending = login(client, email)
    assert pending["mfa_required"] is True
    assert pending["second_factor"]["challenge"]["channel"] == "email"
    assert pending["second_factor"]["available"] == ["email"]
    assert client.get("/api/v1/workspaces", headers=bearer(pending)).status_code == 403

    verified = client.post(
        "/api/v1/auth/mfa/verify",
        json={"code": inbox.email_code(email)},
        headers=bearer(pending),
    )
    assert verified.status_code == 200, verified.text
    full = verified.json()
    # Privilege elevation issues a new session; the limited one is revoked.
    assert client.get("/api/v1/auth/me", headers=bearer(pending)).status_code == 401
    assert client.get("/api/v1/workspaces", headers=bearer(full)).status_code == 200

    store = f"/api/v1/workspaces/{workspace_id}/stores/wildberries"
    body = {"name": "WB", "token": "x" * 40}
    denied = client.post(store, json=body, headers=bearer(full))
    assert denied.status_code == 403
    assert denied.json()["detail"]["code"] == "strong_factor_required"

    started = client.post(
        "/api/v1/auth/phone", json={"phone": "8 900 123-45-67"}, headers=bearer(full)
    )
    assert started.status_code == 202, started.text
    channel, phone, code = inbox.phone[-1]
    assert (channel, phone) == ("telegram", PHONE)
    confirmed = client.post("/api/v1/auth/phone/confirm", json={"code": code}, headers=bearer(full))
    assert confirmed.status_code == 200, confirmed.text
    recovery = confirmed.json()["recovery_codes"]
    assert len(recovery) == 10
    # Fresh strong confirmation: the request now reaches WB token validation.
    assert client.post(store, json=body, headers=bearer(full)).status_code == 400

    reset_limits()
    second = login(client, email)
    assert second["second_factor"]["challenge"]["channel"] == "telegram"
    assert "email" not in second["second_factor"]["available"]
    refused = client.post(
        "/api/v1/auth/mfa/send", json={"channel": "email"}, headers=bearer(second)
    )
    assert refused.json()["detail"]["code"] == "channel_not_allowed"
    by_recovery = client.post(
        "/api/v1/auth/mfa/verify", json={"code": recovery[0]}, headers=bearer(second)
    )
    assert by_recovery.status_code == 200
    me = client.get("/api/v1/auth/me", headers=bearer(by_recovery.json())).json()
    assert me["strong_step_up_valid"] and me["phone"] == "+7 *** ***-45-67"

    reset_limits()
    third = login(client, email)
    reused = client.post(
        "/api/v1/auth/mfa/verify", json={"code": recovery[0]}, headers=bearer(third)
    )
    assert reused.status_code == 400


def test_strong_step_up_expires_and_can_be_renewed(env):
    client, inbox, admin, reset_limits, new_email = env
    email = new_email()
    user_id, workspace_id = create_user(admin, email, phone="+79001112233")
    pending = login(client, email)
    full = client.post(
        "/api/v1/auth/mfa/verify", json={"code": inbox.phone[-1][2]}, headers=bearer(pending)
    ).json()
    with Session(admin) as db, db.begin():
        db.execute(
            update(AuthSession)
            .where(AuthSession.user_id == user_id)
            .values(strong_step_up_at=now() - timedelta(minutes=10))
        )
    store = f"/api/v1/workspaces/{workspace_id}/stores/wildberries"
    body = {"name": "WB", "token": "x" * 40}
    stale = client.post(store, json=body, headers=bearer(full))
    assert stale.status_code == 403
    assert stale.json()["detail"] == {
        "code": "step_up_required",
        "strong": True,
        "message": "Confirm with a code",
    }

    reset_limits()
    sent = client.post("/api/v1/auth/step-up/send", json={}, headers=bearer(full))
    assert sent.status_code == 202 and sent.json()["channel"] == "telegram"
    ok = client.post(
        "/api/v1/auth/step-up/verify", json={"code": inbox.phone[-1][2]}, headers=bearer(full)
    )
    assert ok.status_code == 200
    assert client.post(store, json=body, headers=bearer(full)).status_code == 400


def test_password_reset_revokes_sessions_and_keeps_phone_factor(env):
    client, inbox, admin, reset_limits, new_email = env
    email = new_email()
    create_user(admin, email, phone="+79002223344")
    pending = login(client, email)
    full = client.post(
        "/api/v1/auth/mfa/verify", json={"code": inbox.phone[-1][2]}, headers=bearer(pending)
    ).json()

    reset_limits()
    forgot = client.post("/api/v1/auth/password/forgot", json={"email": email})
    assert forgot.status_code == 202
    new_password = "another long passphrase 42"
    reset = client.post(
        "/api/v1/auth/password/reset",
        json={
            "challenge_id": forgot.json()["challenge_id"],
            "code": inbox.email_code(email),
            "new_password": new_password,
        },
    )
    assert reset.status_code == 200, reset.text
    assert client.get("/api/v1/workspaces", headers=bearer(full)).status_code == 401
    assert (
        client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD}).status_code
        == 401
    )
    reset_limits()
    relogin = login(client, email, new_password)
    # The emailed reset code alone never grants access: the phone is still required.
    assert relogin["mfa_required"] is True
    assert relogin["second_factor"]["challenge"]["channel"] == "telegram"


def test_unknown_address_reset_looks_identical(env):
    client, inbox, _, _, new_email = env
    email = new_email()
    response = client.post("/api/v1/auth/password/forgot", json={"email": email})
    assert response.status_code == 202
    assert "нет" in inbox.emails[-1][2] and not re.search(r"\d{6}", inbox.emails[-1][2])


def test_wrong_codes_lock_the_challenge(env):
    client, inbox, admin, _, new_email = env
    email = new_email()
    create_user(admin, email)
    pending = login(client, email)
    code = inbox.email_code(email)
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(5):
        client.post("/api/v1/auth/mfa/verify", json={"code": wrong}, headers=bearer(pending))
    blocked = client.post("/api/v1/auth/mfa/verify", json={"code": code}, headers=bearer(pending))
    assert blocked.status_code == 400
    assert blocked.json()["detail"]["code"] == "otp_attempts_exceeded"
