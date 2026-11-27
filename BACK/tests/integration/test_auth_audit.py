"""Registration/session/password audit against disposable PostgreSQL and captured delivery."""

from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import update
from sqlalchemy.orm import Session
from test_auth_flow import PASSWORD, bearer, create_user, login
from test_auth_flow import env as env
from test_auth_flow import pytestmark as pytestmark

from app.integrations.notifications import DeliveryError
from app.main import create_app
from app.modules.auth.dependencies import now
from app.modules.auth.models import OtpChallenge

NEW_PASSWORD = "another long password phrase 42"


def verified(env, email):
    client, inbox, _, reset_limits, _ = env
    reset_limits()
    pending = login(client, email)
    code = (
        inbox.phone[-1][2]
        if pending["second_factor"]["challenge"]["channel"] != "email"
        else inbox.email_code(email)
    )
    response = client.post("/api/v1/auth/mfa/verify", json={"code": code}, headers=bearer(pending))
    assert response.status_code == 200, response.text
    return response.json()


def test_wrong_current_password_keeps_session_then_change_revokes_every_device(env):
    client, _, admin, reset_limits, new_email = env
    email = new_email()
    create_user(admin, email, phone="+79004445566")
    first, second = verified(env, email), verified(env, email)
    reset_limits()
    bad = client.post(
        "/api/v1/auth/password",
        json={"password": "wrong", "new_password": NEW_PASSWORD},
        headers=bearer(first),
    )
    assert bad.status_code == 400
    assert bad.json()["detail"]["code"] == "password_invalid"
    assert client.get("/api/v1/auth/me", headers=bearer(first)).status_code == 200
    changed = client.post(
        "/api/v1/auth/password",
        json={"password": PASSWORD, "new_password": NEW_PASSWORD},
        headers=bearer(first),
    )
    assert changed.status_code == 200, changed.text
    for tokens in (first, second):
        assert client.get("/api/v1/auth/me", headers=bearer(tokens)).status_code == 401
        assert (
            client.post(
                "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
            ).status_code
            == 401
        )
    reset_limits()
    assert (
        client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD}).status_code
        == 401
    )
    pending = login(client, email, NEW_PASSWORD)
    assert pending["mfa_required"] is True
    assert pending["second_factor"]["challenge"]["channel"] == "telegram"


def test_change_password_requires_recent_confirmation(env):
    from app.modules.auth.models import AuthSession

    client, _, admin, reset_limits, new_email = env
    email = new_email()
    user_id, _ = create_user(admin, email)
    tokens = verified(env, email)
    with Session(admin) as db, db.begin():
        db.execute(
            update(AuthSession)
            .where(AuthSession.user_id == user_id)
            .values(step_up_at=now() - timedelta(minutes=10))
        )
    reset_limits()
    response = client.post(
        "/api/v1/auth/password",
        json={"password": PASSWORD, "new_password": NEW_PASSWORD},
        headers=bearer(tokens),
    )
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "step_up_required"


def test_native_refresh_rotation_replay_revokes_the_session(env):
    client, _, admin, _, new_email = env
    email = new_email()
    create_user(admin, email)
    full = verified(env, email)
    rotated = client.post("/api/v1/auth/refresh", json={"refresh_token": full["refresh_token"]})
    assert rotated.status_code == 200
    assert rotated.json()["refresh_token"] != full["refresh_token"]
    assert client.get("/api/v1/auth/me", headers=bearer(rotated.json())).status_code == 200
    assert (
        client.post(
            "/api/v1/auth/refresh", json={"refresh_token": full["refresh_token"]}
        ).status_code
        == 401
    )
    assert client.get("/api/v1/auth/me", headers=bearer(rotated.json())).status_code == 401


def test_logout_one_device_and_logout_all(env):
    client, _, admin, reset_limits, new_email = env
    email = new_email()
    create_user(admin, email)
    first, second = verified(env, email), verified(env, email)
    assert client.post("/api/v1/auth/logout", headers=bearer(first)).status_code == 200
    assert client.get("/api/v1/auth/me", headers=bearer(first)).status_code == 401
    assert (
        client.post(
            "/api/v1/auth/refresh", json={"refresh_token": first["refresh_token"]}
        ).status_code
        == 401
    )
    assert client.get("/api/v1/auth/me", headers=bearer(second)).status_code == 200
    third = verified(env, email)
    reset_limits()
    assert client.post("/api/v1/auth/logout-all", headers=bearer(second)).status_code == 200
    assert client.get("/api/v1/auth/me", headers=bearer(third)).status_code == 401


def test_browser_cookie_login_csrf_rotation_and_logout(env):
    client, inbox, admin, reset_limits, new_email = env
    email = new_email()
    create_user(admin, email)
    settings = client.app.state.settings
    origin = settings.cors_origins[0]
    with TestClient(create_app(settings), base_url="https://testserver") as web:
        web.app.state.notifier = inbox
        web.headers["Origin"] = origin
        response = web.post(
            "/api/v1/auth/login", json={"email": email, "password": PASSWORD, "client": "web"}
        )
        assert response.status_code == 200, response.text
        pending = response.json()
        assert pending["access_token"] is None and pending["refresh_token"] is None
        assert "HttpOnly" in response.headers["set-cookie"]
        assert "Secure" in response.headers["set-cookie"]
        assert (
            web.post("/api/v1/auth/mfa/verify", json={"code": inbox.email_code(email)}).status_code
            == 403
        )
        checked = web.post(
            "/api/v1/auth/mfa/verify",
            json={"code": inbox.email_code(email)},
            headers={"X-CSRF-Token": pending["csrf_token"]},
        )
        assert checked.status_code == 200, checked.text
        assert web.get("/api/v1/auth/me").json()["session_mfa_verified"]
        assert web.post("/api/v1/auth/refresh", json={}).status_code == 403
        assert (
            web.post(
                "/api/v1/auth/refresh",
                json={},
                headers={
                    "X-CSRF-Token": checked.json()["csrf_token"],
                    "Origin": "https://untrusted.invalid",
                },
            ).status_code
            == 403
        )
        rotated = web.post(
            "/api/v1/auth/refresh", json={}, headers={"X-CSRF-Token": checked.json()["csrf_token"]}
        )
        assert rotated.status_code == 200, rotated.text
        assert (
            web.post(
                "/api/v1/auth/logout", headers={"X-CSRF-Token": rotated.json()["csrf_token"]}
            ).status_code
            == 200
        )
        assert web.get("/api/v1/auth/me").status_code == 401


def test_browser_registration_creates_cookie_session_after_email_only(env):
    client, inbox, _, _, new_email = env
    email = new_email()
    settings = client.app.state.settings
    with TestClient(create_app(settings), base_url="https://testserver") as web:
        web.app.state.notifier = inbox
        web.headers["Origin"] = settings.cors_origins[0]
        start = web.post(
            "/api/v1/auth/register",
            json={
                "email": email,
                "password": PASSWORD,
                "workspace_name": "Browser audit",
                "client": "web",
            },
        )
        assert start.status_code == 202, start.text
        verified = web.post(
            "/api/v1/auth/register/verify",
            json={
                "challenge_id": start.json()["challenge_id"],
                "code": inbox.email_code(email),
                "client": "web",
            },
        )
        assert verified.status_code == 201, verified.text
        assert verified.json()["access_token"] is None
        assert web.get("/api/v1/auth/me").json()["email_verified"]


def test_expired_reset_code_never_changes_password(env):
    client, inbox, admin, _, new_email = env
    email = new_email()
    create_user(admin, email)
    start = client.post("/api/v1/auth/password/forgot", json={"email": email}).json()
    with Session(admin) as db, db.begin():
        db.execute(
            update(OtpChallenge)
            .where(OtpChallenge.id == start["challenge_id"])
            .values(expires_at=now() - timedelta(seconds=1))
        )
    response = client.post(
        "/api/v1/auth/password/reset",
        json={
            "challenge_id": start["challenge_id"],
            "code": inbox.email_code(email),
            "new_password": NEW_PASSWORD,
        },
    )
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "otp_expired"


def test_delivery_failure_returns_recoverable_pending_session(env, monkeypatch):
    client, inbox, admin, reset_limits, new_email = env
    email = new_email()
    create_user(admin, email)

    def fail(*args, **kwargs):
        raise DeliveryError("email_unavailable")

    with monkeypatch.context() as patch:
        patch.setattr(inbox, "send_email", fail)
        pending = login(client, email)
    assert pending["mfa_required"]
    assert pending["second_factor"]["delivery_error"]
    assert client.get("/api/v1/workspaces", headers=bearer(pending)).status_code == 403
    reset_limits()
    # The failed attempt still owns a challenge and a resend cooldown.
    with Session(admin) as db, db.begin():
        db.execute(
            update(OtpChallenge)
            .where(OtpChallenge.consumed_at.is_(None))
            .values(last_sent_at=now() - timedelta(minutes=2))
        )
    sent = client.post("/api/v1/auth/mfa/send", json={}, headers=bearer(pending))
    assert sent.status_code == 202, sent.text
    ok = client.post(
        "/api/v1/auth/mfa/verify", json={"code": inbox.email_code(email)}, headers=bearer(pending)
    )
    assert ok.status_code == 200, ok.text
