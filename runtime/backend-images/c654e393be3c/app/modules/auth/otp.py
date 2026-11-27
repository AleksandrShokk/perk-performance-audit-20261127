"""One-time codes: issue, throttle, deliver and verify. Codes exist only as HMAC digests."""

import json
import re
import secrets
from datetime import timedelta
from uuid import uuid4

from app.integrations.notifications import DeliveryError, mask_email, mask_phone
from app.modules.auth.dependencies import now
from app.modules.auth.models import OtpChallenge
from app.security.limits import rate_limit
from fastapi import HTTPException
from sqlalchemy import select

MAX_ATTEMPTS = 5
MAX_SENDS = 5
RESEND_AFTER = 60
TTL = {"email": 600, "telegram": 300, "sms": 300}
PHONE_CHANNELS = ("telegram", "sms")
MESSAGES = {
    "register": ("Подтверждение регистрации в PERK", "Код подтверждения регистрации"),
    "login": ("Код для входа в PERK", "Код для входа"),
    "step_up": ("Подтверждение действия в PERK", "Код подтверждения действия"),
    "password_reset": ("Сброс пароля PERK", "Код для сброса пароля"),
    "phone_change": (
        "Смена номера телефона PERK",
        "Код подтверждения смены номера телефона",
    ),
}


def error(status, code, message, **extra):
    return HTTPException(status, {"code": code, "message": message, **extra})


def normalize_phone(value: str, country_codes: list[str]) -> str:
    digits = re.sub(r"[\s()\-]", "", value.strip())
    if re.fullmatch(r"\+?8\d{10}", digits) and "7" in country_codes:
        digits = "+7" + digits.lstrip("+")[1:]
    elif digits.isascii() and digits.isdigit():
        digits = "+" + digits
    if not re.fullmatch(r"\+[1-9]\d{7,14}", digits) or not any(
        digits[1:].startswith(code) for code in country_codes
    ):
        raise error(422, "phone_invalid", "Введите номер телефона в международном формате.")
    if digits.startswith("+7") and len(digits) != 12:
        raise error(422, "phone_invalid", "Введите номер телефона в международном формате.")
    return digits


def destination_digest(vault, channel, destination):
    kind = "email" if channel == "email" else "phone"
    return vault.digest("otp-destination", f"{kind}:{destination}")


def code_digest(vault, challenge_id, code):
    return vault.digest("otp", f"{challenge_id}:{code}")


def payload_aad(challenge_id):
    return f"otp-payload:v1:{challenge_id}"


def masked(channel, destination):
    return mask_email(destination) if channel == "email" else mask_phone(destination)


def throttle(request, channel, destination):
    state, settings = request.app.state, request.app.state.settings
    key = destination_digest(state.vault, channel, destination)
    rate_limit(state.redis, state.vault, "otp-resend", key, 1, RESEND_AFTER)
    rate_limit(state.redis, state.vault, "otp-hour", key, 6, 3600)
    if channel in PHONE_CHANNELS:
        # Paid channels: a global daily ceiling stops SMS-pumping from draining the budget.
        rate_limit(
            state.redis,
            state.vault,
            f"otp-{channel}-day",
            "all",
            settings.phone_otp_daily_limit,
            86400,
        )


def prepare(
    db,
    vault,
    *,
    purpose,
    channel,
    destination,
    user_id=None,
    session_id=None,
    payload=None,
    challenge=None,
    decoy=False,
):
    """Create or rotate a challenge and return it with the plain code to deliver."""
    current = now()
    if challenge is None:
        challenge = OtpChallenge(
            id=uuid4(),
            purpose=purpose,
            user_id=user_id,
            session_id=session_id,
            sent_count=1,
            attempts=0,
        )
        db.add(challenge)
    else:
        if challenge.sent_count >= MAX_SENDS:
            raise error(429, "otp_send_limit", "Слишком много отправок. Начните заново позже.")
        challenge.sent_count += 1
    code = f"{secrets.randbelow(10**6):06d}"
    challenge.channel = channel
    challenge.destination_digest = destination_digest(vault, channel, destination)
    # A decoy behaves like a real challenge but no code can ever match it.
    challenge.code_digest = code_digest(
        vault, challenge.id, secrets.token_urlsafe(16) if decoy else code
    )
    challenge.attempts = 0
    challenge.last_sent_at = current
    challenge.expires_at = current + timedelta(seconds=TTL[channel])
    if payload is not None:
        challenge.payload_ciphertext = vault.seal(json.dumps(payload), payload_aad(challenge.id))
    return challenge, code


def deliver(request, purpose, channel, destination, code, *, notice=None):
    notifier = request.app.state.notifier
    minutes = TTL[channel] // 60
    try:
        if channel == "email":
            if notice:
                notifier.send_email(destination, *notice)
            else:
                subject, title = MESSAGES[purpose]
                notifier.send_email(
                    destination,
                    subject,
                    f"{title}: {code}\n\nКод действует {minutes} мин. "
                    "Никому не сообщайте его, сотрудники PERK его не спрашивают.\n"
                    "Если вы не запрашивали код, просто проигнорируйте это письмо.",
                )
        else:
            notifier.send_phone_code(channel, destination, code, TTL[channel])
    except DeliveryError as exc:
        raise error(
            503,
            exc.code,
            "Не удалось отправить код. Попробуйте позже или выберите другой способ.",
        ) from None


def response(challenge, destination):
    return {
        "challenge_id": challenge.id,
        "channel": challenge.channel,
        "destination": masked(challenge.channel, destination),
        "expires_in": max(0, int((challenge.expires_at - now()).total_seconds())),
        "resend_after": RESEND_AFTER,
    }


def active(db, *, purpose, session_id=None, user_id=None, lock=False):
    query = (
        select(OtpChallenge)
        .where(
            OtpChallenge.purpose == purpose,
            OtpChallenge.consumed_at.is_(None),
            OtpChallenge.expires_at > now(),
        )
        .order_by(OtpChallenge.last_sent_at.desc())
        .limit(1)
    )
    if session_id is not None:
        query = query.where(OtpChallenge.session_id == session_id)
    if user_id is not None:
        query = query.where(OtpChallenge.user_id == user_id)
    return db.scalar(query.with_for_update() if lock else query)


def check(db, vault, challenge, code):
    """Consume on success. Failed attempts are committed before the error is raised."""
    if challenge is None or challenge.consumed_at:
        raise error(400, "otp_not_found", "Запросите новый код.")
    if challenge.expires_at <= now():
        raise error(400, "otp_expired", "Срок действия кода истёк. Запросите новый.")
    if challenge.attempts >= MAX_ATTEMPTS:
        raise error(400, "otp_attempts_exceeded", "Слишком много попыток. Запросите новый код.")
    if not re.fullmatch(r"\d{6}", code) or not secrets.compare_digest(
        code_digest(vault, challenge.id, code), challenge.code_digest
    ):
        challenge.attempts += 1
        left = MAX_ATTEMPTS - challenge.attempts
        db.commit()
        raise error(400, "otp_invalid", "Неверный код.", attempts_left=left)
    challenge.consumed_at = now()


def payload(vault, challenge):
    if not challenge.payload_ciphertext:
        return None
    return json.loads(vault.open(challenge.payload_ciphertext, payload_aad(challenge.id)))
