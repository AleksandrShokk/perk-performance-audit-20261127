import json
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock, patch

import httpx
import pytest
from fastapi import HTTPException
from pydantic import SecretStr, ValidationError

from app.core.config import Settings
from app.integrations.notifications import (
    DeliveryError,
    TelegramGateway,
    build_notifier,
    mask_email,
    mask_phone,
)
from app.modules.auth import otp
from app.modules.auth.dependencies import now, recent_identity, strong_identity
from app.modules.auth.models import User
from app.modules.auth.schemas import PasswordResetInput, RegisterInput


def detail_code(error):
    return error.value.detail["code"]


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("+7 (900) 123-45-67", "+79001234567"),
        ("89001234567", "+79001234567"),
        ("+79001234567", "+79001234567"),
    ],
)
def test_phone_is_normalized_to_e164(raw, expected):
    assert otp.normalize_phone(raw, ["7"]) == expected


@pytest.mark.parametrize("raw", ["+1 202 555 0100", "+7900123", "+7900123456789", "abc"])
def test_phone_outside_allowed_countries_or_malformed_is_rejected(raw):
    with pytest.raises(HTTPException) as error:
        otp.normalize_phone(raw, ["7"])
    assert detail_code(error) == "phone_invalid"


def test_masks_hide_most_of_the_address():
    assert mask_email("seller@example.com") == "s***@example.com"
    assert mask_phone("+79001234567") == "+7 *** ***-45-67"


def test_code_is_stored_only_as_digest_and_payload_is_encrypted(vault):
    db = Mock()
    challenge, code = otp.prepare(
        db,
        vault,
        purpose="register",
        channel="email",
        destination="a@example.com",
        payload={"email": "a@example.com", "password_hash": "argon"},
    )
    assert len(code) == 6 and code.isdigit()
    assert code not in challenge.code_digest
    assert "argon" not in challenge.payload_ciphertext
    assert otp.payload(vault, challenge)["password_hash"] == "argon"
    db.add.assert_called_once_with(challenge)


def test_check_counts_attempts_and_consumes_once(vault):
    db = Mock()
    challenge, code = otp.prepare(
        db, vault, purpose="login", channel="telegram", destination="+79001234567"
    )
    wrong = "000000" if code != "000000" else "111111"
    with pytest.raises(HTTPException) as error:
        otp.check(db, vault, challenge, wrong)
    assert detail_code(error) == "otp_invalid"
    assert error.value.detail["attempts_left"] == otp.MAX_ATTEMPTS - 1
    db.commit.assert_called_once()
    otp.check(db, vault, challenge, code)
    assert challenge.consumed_at is not None
    with pytest.raises(HTTPException) as error:
        otp.check(db, vault, challenge, code)
    assert detail_code(error) == "otp_not_found"


def test_attempt_limit_blocks_even_the_correct_code(vault):
    db = Mock()
    challenge, code = otp.prepare(db, vault, purpose="login", channel="email", destination="x@y.z")
    challenge.attempts = otp.MAX_ATTEMPTS
    with pytest.raises(HTTPException) as error:
        otp.check(db, vault, challenge, code)
    assert detail_code(error) == "otp_attempts_exceeded"


def test_expired_code_is_rejected(vault):
    db = Mock()
    challenge, code = otp.prepare(db, vault, purpose="login", channel="sms", destination="+7")
    challenge.expires_at = now() - timedelta(seconds=1)
    with pytest.raises(HTTPException) as error:
        otp.check(db, vault, challenge, code)
    assert detail_code(error) == "otp_expired"


def test_decoy_challenge_never_accepts_the_generated_code(vault):
    db = Mock()
    challenge, code = otp.prepare(
        db, vault, purpose="register", channel="email", destination="a@b.c", decoy=True
    )
    with pytest.raises(HTTPException):
        otp.check(db, vault, challenge, code)


def test_resend_rotates_code_and_has_a_limit(vault):
    db = Mock()
    challenge, first = otp.prepare(db, vault, purpose="login", channel="email", destination="a@b.c")
    digests = {challenge.code_digest}
    for _ in range(otp.MAX_SENDS - 1):
        challenge, _ = otp.prepare(
            db, vault, purpose="login", channel="email", destination="a@b.c", challenge=challenge
        )
        digests.add(challenge.code_digest)
    assert len(digests) > 1
    with pytest.raises(HTTPException) as error:
        otp.prepare(
            db, vault, purpose="login", channel="email", destination="a@b.c", challenge=challenge
        )
    assert detail_code(error) == "otp_send_limit"


def test_strong_factor_never_includes_email_only():
    assert not User(email_verified_at=now()).has_strong_factor
    assert User(phone_verified_at=now()).has_strong_factor
    assert User(totp_ciphertext="sealed").has_strong_factor


def identity(user, **session):
    values = {"step_up_at": None, "strong_step_up_at": None, **session}
    return SimpleNamespace(user=user, session=SimpleNamespace(**values))


def test_strong_actions_require_a_phone_or_app_and_a_fresh_strong_code():
    with pytest.raises(HTTPException) as error:
        strong_identity(identity(User(), strong_step_up_at=now()))
    assert detail_code(error) == "strong_factor_required"

    stale = now() - timedelta(minutes=6)
    with pytest.raises(HTTPException) as error:
        strong_identity(identity(User(phone_verified_at=now()), strong_step_up_at=stale))
    assert error.value.detail == {
        "code": "step_up_required",
        "strong": True,
        "message": "Confirm with a code",
    }
    with pytest.raises(HTTPException):
        # An email step-up never satisfies a strong action.
        strong_identity(identity(User(phone_verified_at=now()), step_up_at=now()))
    strong_identity(identity(User(phone_verified_at=now()), strong_step_up_at=now()))


def test_recent_actions_accept_any_fresh_code():
    with pytest.raises(HTTPException) as error:
        recent_identity(identity(User()))
    assert error.value.detail["strong"] is False
    recent_identity(identity(User(), step_up_at=now()))


def test_registration_input_trims_workspace_name_and_rejects_blank():
    data = RegisterInput(
        email="a@example.com", password="correct horse battery", workspace_name="  Shop  "
    )
    assert data.workspace_name == "Shop"
    with pytest.raises(ValidationError):
        RegisterInput(email="a@example.com", password="correct horse battery", workspace_name="  ")


def test_new_password_policy_applies_to_reset():
    with pytest.raises(ValidationError):
        PasswordResetInput(
            challenge_id="00000000-0000-0000-0000-000000000000",
            code="123456",
            new_password="1234567890123456",
        )
    assert isinstance(
        PasswordResetInput(
            challenge_id="00000000-0000-0000-0000-000000000000",
            code="123456",
            new_password="correct horse battery",
        ).new_password,
        SecretStr,
    )


def test_production_forbids_fake_providers_and_plain_smtp():
    base = dict(
        _env_file=None,
        app_env="production",
        team_invite_url="https://app.example.test/invite",
        account_recovery_url="https://app.example.test/recover-factor",
        cors_origins=["https://app.perk.test"],
        allowed_hosts=["api.perk.test"],
        postgres_password="x",
    )
    with pytest.raises(ValidationError):
        Settings(**base)
    with pytest.raises(ValidationError):
        Settings(**base, email_provider="smtp", smtp_security="none")
    with pytest.raises(ValidationError):
        Settings(**base, email_provider="smtp", smtp_security="starttls", sms_provider="fake")
    secure = dict(email_provider="smtp", smtp_security="starttls", sms_provider="disabled")
    with pytest.raises(ValidationError):
        # Notification test providers are forbidden in production too.
        Settings(**base, **secure, telegram_provider="disabled")
    Settings(
        **base,
        **secure,
        telegram_provider="disabled",
        telegram_bot_provider="disabled",
        push_provider="disabled",
    )


def test_gateway_requires_token_file():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, telegram_provider="gateway")


def test_disabled_channels_are_not_offered(isolated_settings):
    settings = isolated_settings.model_copy(
        update={"telegram_provider": "disabled", "sms_provider": "fake"}
    )
    notifier = build_notifier(settings)
    assert notifier.phone_channels() == ["sms"]
    with pytest.raises(DeliveryError):
        notifier.send_phone_code("telegram", "+79001234567", "123456", 300)


def gateway(tmp_path, handler):
    token = tmp_path / "telegram-token"
    token.write_text("secret-token\n")
    return TelegramGateway(token, transport=httpx.MockTransport(handler))


def test_telegram_gateway_sends_own_code_with_bearer_token(tmp_path):
    seen = {}

    def handler(request):
        seen["auth"] = request.headers["authorization"]
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"ok": True, "result": {"request_id": "r1"}})

    gateway(tmp_path, handler).send("+79001234567", "123456", 300)
    assert seen["auth"] == "Bearer secret-token"
    assert seen["url"] == "https://gatewayapi.telegram.org/sendVerificationMessage"
    assert seen["body"] == {"phone_number": "+79001234567", "code": "123456", "ttl": 300}


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, json={"ok": False, "error": "PHONE_NUMBER_INVALID"}),
        httpx.Response(500, text="oops"),
        httpx.Response(302, headers={"location": "https://evil.test"}),
    ],
)
def test_telegram_gateway_failures_become_delivery_errors(tmp_path, response):
    with pytest.raises(DeliveryError) as error:
        gateway(tmp_path, lambda request: response).send("+79001234567", "123456", 300)
    assert error.value.code == "telegram_unavailable"


def test_smtp_failure_does_not_leak_code(isolated_settings, caplog):
    from app.integrations.notifications import SmtpEmail

    sender = SmtpEmail(isolated_settings.model_copy(update={"email_provider": "smtp"}))
    with patch("smtplib.SMTP", side_effect=OSError("connection refused")):
        with pytest.raises(DeliveryError):
            sender.send("a@example.com", "Код", "Код: 123456")
    assert "123456" not in caplog.text


def test_gateway_private_proxy_keeps_https_and_sensitive_data_out_of_url(
    isolated_settings, tmp_path
):
    token = tmp_path / "telegram-token"
    token.write_text("secret-token")
    settings = isolated_settings.model_copy(
        update={
            "telegram_provider": "gateway",
            "telegram_gateway_token_file": token,
            "telegram_gateway_proxy_url": "http://172.19.0.1:18888",
        }
    )
    with patch("app.integrations.notifications.httpx.Client") as client:
        session = client.return_value.__enter__.return_value
        session.post.return_value = httpx.Response(200, json={"ok": True})
        build_notifier(settings).send_phone_code("telegram", "+79001234567", "123456", 300)
    assert client.call_args.kwargs["proxy"] == "http://172.19.0.1:18888"
    assert client.call_args.kwargs["follow_redirects"] is False
    assert client.call_args.kwargs["trust_env"] is False
    assert session.post.call_args.args == (
        "https://gatewayapi.telegram.org/sendVerificationMessage",
    )
    assert session.post.call_args.kwargs["headers"] == {"Authorization": "Bearer secret-token"}


def test_gateway_private_proxy_failure_is_sanitized(tmp_path, caplog):
    token = tmp_path / "telegram-token"
    token.write_text("secret-token")
    sender = TelegramGateway(token, proxy="http://172.19.0.1:18888")
    with patch("app.integrations.notifications.httpx.Client") as client:
        client.return_value.__enter__.return_value.post.side_effect = httpx.ProxyError(
            "secret-token +79001234567 123456"
        )
        with pytest.raises(DeliveryError) as error:
            sender.send("+79001234567", "123456", 300)
    assert error.value.code == "telegram_unavailable"
    assert "secret-token" not in caplog.text
    assert "+79001234567" not in caplog.text
    assert "123456" not in caplog.text
