"""Synthetic credentials only: internal beta must not widen access for other companies."""

import base64
import json
import time
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import httpx
import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.core.config import Settings
from app.integrations.wildberries.client import (
    READ_ONLY,
    WildberriesClient,
    inspect_token,
)
from app.integrations.wildberries.data import Source
from app.modules.accounts import router as accounts
from app.modules.sync.capabilities import sync_capabilities


def token(seller=None, **overrides):
    payload = {
        "sid": str(seller or uuid4()),
        "s": READ_ONLY | (1 << 1) | (1 << 2) | (1 << 5),
        "exp": int(time.time()) + 3600,
        "t": False,
        "acc": 3,
        "for": "self",
        **overrides,
    }

    def encode(value):
        return base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")

    return ".".join((encode({"alg": "HS256"}), encode(payload), "synthetic-signature"))


def beta_settings(settings, workspace, **overrides):
    return settings.model_copy(
        update={
            "app_env": "production",
            "wb_personal_token_test_workspaces": [workspace],
            "wb_personal_token_test_until": datetime.now(UTC) + timedelta(days=30),
            **overrides,
        }
    )


def test_personal_token_requires_explicit_beta_but_own_service_still_works():
    personal = token()
    with pytest.raises(HTTPException) as denied:
        inspect_token(personal, production=True)
    assert "сервисный токен" in denied.value.detail
    assert inspect_token(personal, production=True, allow_personal=True).token_type == 3
    service = token(acc=4, **{"for": "asid:perk"})
    assert inspect_token(service, production=True, service_id="perk").token_type == 4


@pytest.mark.parametrize(
    "fields",
    [
        {"acc": 1, "for": None},
        {"acc": 2, "t": True},
        {"acc": 3, "for": "asid:other"},
        {"acc": 3, "for": None},
        {"acc": 4, "for": "asid:other"},
        {"acc": 4, "for": "asid:perk"},  # No configured service ID.
        {"exp": int(time.time()) - 1},
        {"s": 1 << 2},  # Write access is still forbidden.
        {"s": READ_ONLY | (1 << 2) | (1 << 15)},  # Disallowed category.
        {"s": READ_ONLY},  # No useful scopes.
    ],
)
def test_beta_keeps_token_type_expiry_and_scope_checks(fields):
    with pytest.raises(HTTPException) as denied:
        inspect_token(token(**fields), production=True, allow_personal=True)
    assert denied.value.status_code == 400


@pytest.mark.parametrize(
    "state", ["other_workspace", "past", "exact_deadline", "no_deadline", "empty"]
)
def test_beta_is_scoped_and_expires(isolated_settings, state):
    workspace = uuid4()
    settings = beta_settings(isolated_settings, workspace)
    assert settings.allows_personal_wb_token(workspace)
    if state == "other_workspace":
        workspace = uuid4()
    elif state in {"past", "exact_deadline"}:
        settings.wb_personal_token_test_until = datetime.now(UTC) - timedelta(
            seconds=1 if state == "past" else 0
        )
    elif state == "no_deadline":
        settings.wb_personal_token_test_until = None
    else:
        settings.wb_personal_token_test_workspaces = []
    assert not settings.allows_personal_wb_token(workspace)
    with pytest.raises(HTTPException):
        inspect_token(
            token(),
            production=True,
            allow_personal=settings.allows_personal_wb_token(workspace),
        )


def test_beta_settings_are_disabled_by_default_and_require_timezone():
    settings = Settings(_env_file=None, wb_personal_token_test_until="")
    assert not settings.allows_personal_wb_token(uuid4())
    with pytest.raises(ValidationError):
        Settings(_env_file=None, wb_personal_token_test_until="2026-12-11T12:00:00")


@pytest.mark.parametrize("same_seller", [True, False])
def test_beta_connection_still_verifies_token_with_wb(isolated_settings, monkeypatch, same_seller):
    workspace, seller = uuid4(), uuid4()
    raw = token(seller)
    settings = beta_settings(isolated_settings, workspace)
    checked = []

    def wb_response(request):
        checked.append(request)
        assert request.headers["Authorization"] == raw
        return httpx.Response(200, json={"sid": str(seller if same_seller else uuid4())})

    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                settings=settings,
                redis=None,
                vault=None,
                wb_client=WildberriesClient(httpx.MockTransport(wb_response)),
            )
        )
    )
    limit = Mock()
    monkeypatch.setattr(accounts, "rate_limit", limit)
    if same_seller:
        assert accounts.verify_wb(request, raw, workspace).seller_id == str(seller)
    else:
        with pytest.raises(HTTPException) as mismatch:
            accounts.verify_wb(request, raw, workspace)
        assert mismatch.value.status_code == 400
    assert len(checked) == 1 and limit.call_count == 1
    checked.clear()
    with pytest.raises(HTTPException):
        accounts.verify_wb(request, raw, uuid4())
    assert checked == []


def test_beta_capabilities_work_only_in_allowed_workspace(isolated_settings, vault):
    workspace, store = uuid4(), uuid4()
    settings = beta_settings(isolated_settings, workspace)
    raw = token()
    credential = SimpleNamespace(ciphertext=vault.seal(raw, f"wb:{workspace}:{store}"))
    result = sync_capabilities(credential, vault, settings, workspace, store)
    assert result["token_type"] == "personal"
    assert result["sources"][Source.STOCKS]["available"]
    assert raw not in str(result)
    settings.wb_personal_token_test_workspaces = []
    denied = sync_capabilities(credential, vault, settings, workspace, store)
    assert denied["token_type"] == "unavailable"
    assert not any(item["available"] for item in denied["sources"].values())


def test_global_personal_beta_is_available_for_new_workspaces_and_auto_expires(
    isolated_settings,
):
    settings = beta_settings(isolated_settings, uuid4(), wb_personal_token_test_all_workspaces=True)
    assert settings.allows_personal_wb_token(uuid4())
    assert (
        inspect_token(
            token(),
            production=True,
            allow_personal=settings.allows_personal_wb_token(uuid4()),
        ).token_type
        == 3
    )
    settings.wb_personal_token_test_until = None
    assert not settings.allows_personal_wb_token(uuid4())
    settings.wb_personal_token_test_until = datetime.now(UTC)
    assert not settings.allows_personal_wb_token(uuid4())
