from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_auth_flow import PASSWORD, create_user
from test_auth_flow import env as env
from test_auth_flow import pytestmark as pytestmark

from app.main import create_app
from app.modules.auth.models import AuthSession


def test_web_refresh_collision_does_not_revoke_the_rotated_session(env):
    original, inbox, admin, reset, new_email = env
    email = new_email()
    uid, _ = create_user(admin, email)
    settings = original.app.state.settings
    with TestClient(create_app(settings), base_url="https://testserver") as web:
        web.app.state.notifier = inbox
        web.headers["Origin"] = settings.cors_origins[0]
        reset()
        pending = web.post(
            "/api/v1/auth/login", json={"email": email, "password": PASSWORD, "client": "web"}
        )
        assert pending.status_code == 200, pending.text
        csrf = pending.json()["csrf_token"]
        full = web.post(
            "/api/v1/auth/mfa/verify",
            json={"code": inbox.email_code(email)},
            headers={"X-CSRF-Token": csrf},
        )
        assert full.status_code == 200, full.text
        old = web.cookies.get("perk_refresh")
        csrf = full.json()["csrf_token"]
        rotated = web.post("/api/v1/auth/refresh", json={}, headers={"X-CSRF-Token": csrf})
        assert rotated.status_code == 200, rotated.text
        collision = web.post(
            "/api/v1/auth/refresh",
            json={},
            headers={"Cookie": "perk_refresh=" + old, "X-CSRF-Token": csrf},
        )
        assert collision.status_code == 409, collision.text
        with Session(admin) as db:
            rows = db.scalars(
                select(AuthSession).where(
                    AuthSession.user_id == uid, AuthSession.mfa_verified_at.is_not(None)
                )
            ).all()
            assert rows and all(row.revoked_at is None for row in rows)
        assert web.get("/api/v1/auth/me").status_code == 200
