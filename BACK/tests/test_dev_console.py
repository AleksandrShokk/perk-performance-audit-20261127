import hashlib
import json
import secrets
import time
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.db.session import get_db
from app.devconsole.access import ConsoleSettings, Grant, scoped_identity
from app.devconsole.server import create_console
from app.main import create_app
from app.modules.auth.dependencies import current_identity

ORIGIN = {"Origin": "http://127.0.0.1:8010"}


@pytest.fixture
def console(isolated_settings, tmp_path):
    raw = {
        "token": "pd_" + secrets.token_urlsafe(32),
        "user_id": str(uuid4()),
        "workspace_id": str(uuid4()),
        "store_id": str(uuid4()),
        "bootstrap_digest": "",
        "bootstrap_expires_at": time.time() + 300,
    }
    code = secrets.token_urlsafe(32)
    raw["bootstrap_digest"] = hashlib.sha256(code.encode()).hexdigest()
    path = tmp_path / "grant.json"
    path.write_text(json.dumps(raw))
    values = isolated_settings.model_dump()
    values.update(app_env="local", dev_console_enabled=True, dev_grant_file=path)
    settings = ConsoleSettings(_env_file=None, **values)
    with patch("app.devconsole.server.build_engine"), patch("app.devconsole.server.Redis.from_url"):
        app = create_console(settings)
        app.dependency_overrides[get_db] = lambda: Mock()
        app.dependency_overrides[scoped_identity] = lambda: SimpleNamespace()
        with TestClient(app, base_url="http://127.0.0.1:8010") as client:
            app.state.redis.eval.return_value = 1
            app.state.redis.set.return_value = True
            yield SimpleNamespace(client=client, raw=raw, code=code, path=path, settings=settings)


@pytest.mark.parametrize(
    "enabled,environment", [(False, "local"), (True, "test"), (True, "production")]
)
def test_console_disabled_by_default_and_outside_local(enabled, environment):
    with pytest.raises(ValidationError):
        ConsoleSettings(_env_file=None, dev_console_enabled=enabled, app_env=environment)


def test_one_time_bootstrap_cookie_csrf_and_revocation(console):
    c = console.client
    assert c.get("/api/v1/dev/session").status_code == 401
    response = c.post("/api/v1/dev/bootstrap", json={"code": console.code}, headers=ORIGIN)
    assert response.status_code == 200
    assert console.raw["token"] not in response.text
    assert "HttpOnly" in response.headers["set-cookie"]
    assert "SameSite=strict" in response.headers["set-cookie"]
    assert c.get("/api/v1/dev/session").status_code == 200
    c.app.state.redis.set.return_value = False
    assert (
        c.post("/api/v1/dev/bootstrap", json={"code": console.code}, headers=ORIGIN).status_code
        == 401
    )
    assert c.post("/api/v1/dev/sync", json={}, headers=ORIGIN).status_code == 403
    console.path.unlink()
    assert c.get("/api/v1/dev/session").status_code == 503


def test_bootstrap_expiry_foreign_origin_and_dns_rebinding(console):
    c = console.client
    assert (
        c.post(
            "/api/v1/dev/bootstrap",
            json={"code": console.code},
            headers={"Origin": "https://evil.test"},
        ).status_code
        == 403
    )
    assert c.get("/", headers={"Host": "evil.test"}).status_code == 400
    assert c.get("/api/v1/dev/session", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
    console.raw["bootstrap_expires_at"] = time.time() - 1
    console.path.write_text(json.dumps(console.raw))
    assert (
        c.post("/api/v1/dev/bootstrap", json={"code": console.code}, headers=ORIGIN).status_code
        == 401
    )


def test_token_has_no_time_expiry_but_is_scoped_and_rotatable(console):
    c = console.client
    headers = {"Authorization": "Bearer " + console.raw["token"]}
    console.raw["bootstrap_expires_at"] = 0
    console.path.write_text(json.dumps(console.raw))
    assert c.get("/api/v1/dev/session", headers=headers).status_code == 200
    # Account, credential administration and arbitrary workspace routes are not exposed.
    assert c.get("/api/v1/auth/me", headers=headers).status_code == 404
    assert c.get("/api/v1/workspaces", headers=headers).status_code == 404
    console.raw["token"] = "pd_" + secrets.token_urlsafe(32)
    console.path.write_text(json.dumps(console.raw))
    assert c.get("/api/v1/dev/session", headers=headers).status_code == 401


def test_regular_auth_rejects_development_token_before_database_lookup(console):
    request = Mock()
    request.cookies = {}
    db = Mock()
    with pytest.raises(HTTPException) as error:
        current_identity(request, db, SimpleNamespace(credentials=console.raw["token"]))
    assert error.value.status_code == 401
    db.execute.assert_not_called()


def test_scope_checks_account_membership_and_store(console):
    grant = Grant.model_validate(console.raw)
    db = Mock()
    db.get.return_value = SimpleNamespace(is_active=True, email_verified_at=1, id=grant.user_id)
    db.scalar.side_effect = [None, object()]
    with pytest.raises(HTTPException) as error:
        scoped_identity(db, grant)
    assert error.value.status_code == 403
    # Only the transaction-local actor is set (forced RLS needs it for the checks themselves).
    assert db.execute.call_count == 1
    assert "set_config" in str(db.execute.call_args.args[0])


def test_static_ui_has_csp_and_no_secret(console, isolated_settings):
    response = console.client.get("/")
    assert response.status_code == 200
    assert "script-src 'self'" in response.headers["content-security-policy"]
    assert console.raw["token"] not in response.text
    assert console.client.get("/assets/app.js").status_code == 200
    assert console.client.get("/assets/grant.json").status_code == 404
    assert all(
        not p.startswith("/api/v1/dev") for p in create_app(isolated_settings).openapi()["paths"]
    )
