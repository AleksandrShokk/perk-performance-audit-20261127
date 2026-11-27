import re

from sqlalchemy.orm import Session
from test_auth_audit import verified
from test_auth_flow import bearer, create_user
from test_auth_flow import env as env
from test_auth_flow import pytestmark as pytestmark

from app.modules.auth.models import User


def test_first_phone_factor_can_be_cancelled_by_email_link_and_all_sessions_end(env):
    client, inbox, admin, reset, new_email = env
    email = new_email()
    uid, _ = create_user(admin, email)
    tokens = verified(env, email)
    reset()
    started = client.post(
        "/api/v1/auth/phone",
        json={"phone": "+79009992233", "channel": "telegram"},
        headers=bearer(tokens),
    )
    assert started.status_code == 202, started.text
    confirmed = client.post(
        "/api/v1/auth/phone/confirm", json={"code": inbox.phone[-1][2]}, headers=bearer(tokens)
    )
    assert confirmed.status_code == 200, confirmed.text
    body = next(body for address, _, body in reversed(inbox.emails) if "#code=pf_" in body)
    token = re.search(r"#code=(pf_[A-Za-z0-9_-]{43})", body)[1]
    reset()
    cancelled = client.post("/api/v1/auth/factor/cancel", json={"token": token})
    assert cancelled.status_code == 200, cancelled.text
    assert client.get("/api/v1/auth/me", headers=bearer(tokens)).status_code == 401
    with Session(admin) as db:
        user = db.get(User, uid)
        assert user.phone is None and not user.has_strong_factor
    assert client.post("/api/v1/auth/factor/cancel", json={"token": token}).status_code == 400
