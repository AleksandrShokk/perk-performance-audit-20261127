"""A short-lived, single-purpose grant for replacing a verified phone number."""

from datetime import timedelta

from app.modules.audit.service import audit
from app.modules.auth import otp
from app.modules.auth.dependencies import now
from app.modules.auth.models import OtpChallenge
from sqlalchemy import select, update

AUTHORIZATION_TTL = 300


def require_phone(user):
    if not user.phone or not user.phone_verified_at:
        raise otp.error(400, "phone_not_verified", "Сначала привяжите номер телефона.")


def invalidate(db, user_id, *, session_id=None, purposes=("phone_change", "phone_verify")):
    query = update(OtpChallenge).where(
        OtpChallenge.user_id == user_id,
        OtpChallenge.purpose.in_(purposes),
        OtpChallenge.expires_at > now(),
    )
    if session_id is not None:
        query = query.where(OtpChallenge.session_id == session_id)
    db.execute(query.values(expires_at=now()))


def send(db, request, user, session, data):
    require_phone(user)
    phone = otp.normalize_phone(data.phone, request.app.state.settings.phone_country_codes)
    if phone == user.phone:
        raise otp.error(400, "phone_unchanged", "Введите новый номер телефона.")
    channel = data.channel
    if channel == "telegram" and channel not in request.app.state.notifier.phone_channels():
        raise otp.error(400, "telegram_unavailable", "Отправка кодов в Telegram недоступна.")
    destination = user.email if channel == "email" else user.phone
    otp.throttle(request, channel, destination)
    # A new request invalidates any earlier grant and new-phone code in this session.
    invalidate(db, user.id, session_id=session.id)
    challenge, code = otp.prepare(
        db,
        request.app.state.vault,
        purpose="phone_change",
        channel=channel,
        destination=destination,
        user_id=user.id,
        session_id=session.id,
        payload={"previous_phone": user.phone, "phone": phone},
    )
    audit(db, "auth.phone_change_requested", user_id=user.id)
    db.commit()
    otp.deliver(request, "phone_change", channel, destination, code)
    return otp.response(challenge, destination)


def owned_challenge(db, user, session, challenge_id):
    return db.scalar(
        select(OtpChallenge)
        .where(
            OtpChallenge.id == challenge_id,
            OtpChallenge.purpose == "phone_change",
            OtpChallenge.user_id == user.id,
            OtpChallenge.session_id == session.id,
        )
        .with_for_update()
    )


def verify(db, request, user, session, data):
    require_phone(user)
    challenge = owned_challenge(db, user, session, data.challenge_id)
    otp.check(db, request.app.state.vault, challenge, data.code.get_secret_value())
    if otp.payload(request.app.state.vault, challenge)["previous_phone"] != user.phone:
        raise otp.error(400, "phone_change_expired", "Номер уже изменён. Начните заново.")
    challenge.expires_at = now() + timedelta(seconds=AUTHORIZATION_TTL)
    # This proves only phone replacement, never a generic strong step-up.
    audit(db, "auth.phone_change_authorized", user_id=user.id)
    db.commit()
    return {"authorization_id": challenge.id, "expires_in": AUTHORIZATION_TTL}


def authorize(db, vault, user, session, authorization_id, phone):
    grant = owned_challenge(db, user, session, authorization_id) if authorization_id else None
    if not grant or not grant.consumed_at or grant.expires_at <= now():
        raise otp.error(403, "phone_change_required", "Подтвердите старый номер или почту.")
    payload = otp.payload(vault, grant)
    if payload["previous_phone"] != user.phone or payload["phone"] != phone:
        raise otp.error(
            403,
            "phone_change_required",
            "Номер изменился. Начните подтверждение заново.",
        )
    return grant
