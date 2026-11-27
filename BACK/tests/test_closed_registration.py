from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException, Response

from app.modules.auth import router
from app.modules.auth.schemas import ChallengeInput, RegisterInput, RegisterVerifyInput


def closed_request():
    return SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                settings=SimpleNamespace(public_registration_enabled=False),
                vault=Mock(),
            )
        )
    )


def test_closed_signup_does_not_hash_password_or_create_challenge():
    db = Mock()
    data = RegisterInput(
        email="new@example.com", password="a long test password", workspace_name="Test"
    )
    with patch.object(router, "hash_password") as hashing:
        with pytest.raises(HTTPException) as error:
            router.register(data, closed_request(), db)
    assert error.value.status_code == 403
    assert error.value.detail["code"] == "registration_closed"
    hashing.assert_not_called()
    assert not db.mock_calls


@pytest.mark.parametrize("action", ["resend", "verify"])
def test_old_public_challenge_cannot_bypass_closed_signup(action):
    db = Mock()
    challenge = SimpleNamespace(consumed_at=None)
    data = {"challenge_id": uuid4(), "code": "123456"}
    with (
        patch.object(router, "locked_challenge", return_value=challenge),
        patch.object(router, "enforce_client"),
        patch.object(router, "user_limit"),
        patch.object(router.otp, "check"),
        patch.object(router.otp, "payload", return_value={"email": "old@example.com"}),
        patch.object(router.otp, "deliver") as delivery,
    ):
        with pytest.raises(HTTPException) as error:
            if action == "resend":
                router.register_resend(
                    ChallengeInput(challenge_id=data["challenge_id"]),
                    closed_request(),
                    db,
                )
            else:
                router.register_verify(
                    RegisterVerifyInput(**data), closed_request(), Response(), db
                )
    assert error.value.detail["code"] == "registration_closed"
    delivery.assert_not_called()
    db.add.assert_not_called()
    db.commit.assert_not_called()


def test_closed_signup_keeps_invited_registration_available():
    router.require_registration(closed_request(), invited=True)


def test_allowlisted_email_can_register_without_opening_public_signup():
    request = closed_request()
    request.app.state.settings.registration_allowed_emails = ["owner@example.com"]
    router.require_registration(request, invited=False, email="OWNER@example.com")
    with pytest.raises(HTTPException) as error:
        router.require_registration(request, invited=False, email="other@example.com")
    assert error.value.detail["code"] == "registration_closed"
    with pytest.raises(HTTPException):
        router.require_registration(request, invited=False)


def test_public_beta_registration_closes_at_its_deadline():
    from datetime import timedelta

    request = closed_request()
    settings = request.app.state.settings
    settings.public_registration_enabled = True
    settings.registration_open_until = router.now() + timedelta(days=1)
    router.require_registration(request, invited=False)
    settings.registration_open_until = router.now()
    with pytest.raises(HTTPException):
        router.require_registration(request, invited=False)
    router.require_registration(request, invited=True)
