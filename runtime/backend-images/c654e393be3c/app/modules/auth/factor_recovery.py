"""One-day cancellation of a first strong factor, using a secret link sent to verified email."""

import json
import secrets

from fastapi import HTTPException
from sqlalchemy import delete

from app.modules.auth.models import RecoveryCode
from app.modules.auth.service import revoke_all

TTL = 86400


def fingerprint(vault, user):
    return vault.digest(
        "factor-state",
        str(user.id)
        + ":"
        + str(user.phone_verified_at)
        + ":"
        + str(user.phone)
        + ":"
        + str(user.totp_ciphertext),
    )


def offer(request, user):
    token = "pf_" + secrets.token_urlsafe(32)
    vault = request.app.state.vault
    key = "perk:factor-recovery:" + vault.digest("factor-recovery", token)
    payload = json.dumps({"user_id": str(user.id), "state": fingerprint(vault, user)})
    request.app.state.redis.set(key, vault.seal(payload, key), ex=TTL)
    base = request.app.state.settings.account_recovery_url
    url = base + "#code=" + token
    request.app.state.notifier.send_email(
        user.email,
        "PERK: подключён способ подтверждения",
        "Если это были не вы, отмените подключение в течение 24 часов: "
        + url
        + "\nПосле отмены все сессии будут завершены. Затем смените пароль почты и PERK.",
    )


def cancel(request, db, token):
    from uuid import UUID

    from app.modules.auth.models import User

    vault = request.app.state.vault
    key = "perk:factor-recovery:" + vault.digest("factor-recovery", token)
    raw = request.app.state.redis.get(key)
    if not raw:
        raise HTTPException(400, "Ссылка недействительна или истекла")
    data = json.loads(vault.open(raw.decode() if isinstance(raw, bytes) else raw, key))
    user = db.get(User, UUID(data["user_id"]), with_for_update=True)
    if not user or not secrets.compare_digest(data["state"], fingerprint(vault, user)):
        raise HTTPException(400, "Способы подтверждения уже изменились")
    user.phone = user.phone_verified_at = user.phone_channel = None
    user.totp_ciphertext = user.totp_pending_ciphertext = user.totp_pending_until = (
        user.totp_last_step
    ) = None
    db.execute(delete(RecoveryCode).where(RecoveryCode.user_id == user.id))
    revoke_all(db, user.id)
    from app.modules.audit.service import audit

    audit(db, "auth.first_factor_cancelled", user_id=user.id)
    db.commit()
    request.app.state.redis.delete(key)
