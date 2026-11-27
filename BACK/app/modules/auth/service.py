import re
import secrets
from datetime import timedelta

import pyotp
from app.db.session import set_actor
from app.modules.audit.service import audit
from app.modules.auth.dependencies import check_csrf, now
from app.modules.auth.models import (
    AccessToken,
    AuthSession,
    RecoveryCode,
    RefreshToken,
    User,
)
from app.modules.auth.schemas import TokenResponse
from app.security.crypto import new_token
from app.security.limits import rate_limit
from fastapi import HTTPException, Request, Response
from sqlalchemy import delete, select, update

STRONG_METHODS = {"telegram", "sms", "totp", "recovery"}


def enforce_client(request: Request, client: str):
    origin = request.headers.get("origin")
    if client == "web" and origin not in request.app.state.settings.cors_origins:
        raise HTTPException(403, "Откройте сайт по разрешённому адресу и повторите вход.")
    if client == "mobile" and origin:
        raise HTTPException(403, "Войдите в аккаунт через сайт.")


def user_limit(request, user_key):
    rate_limit(
        request.app.state.redis,
        request.app.state.vault,
        "auth-account",
        user_key,
        8,
        300,
    )


def verify_totp(user, vault, code: str) -> bool:
    if not user.totp_ciphertext or not re.fullmatch(r"\d{6}", code):
        return False
    secret = vault.open(user.totp_ciphertext, f"totp:{user.id}")
    totp = pyotp.TOTP(secret)
    current_step = int(now().timestamp()) // 30
    for step in [current_step, current_step - 1, current_step + 1]:
        if step <= (user.totp_last_step or 0):
            continue
        if secrets.compare_digest(totp.at(step * 30), code):
            user.totp_last_step = step
            return True
    return False


def verify_recovery(db, vault, user, code: str) -> bool:
    if re.fullmatch(r"rc_[A-Za-z0-9_-]{22}", code):
        recovery = db.scalar(
            select(RecoveryCode)
            .where(
                RecoveryCode.user_id == user.id,
                RecoveryCode.code_digest == vault.digest("recovery", code),
                RecoveryCode.used_at.is_(None),
            )
            .with_for_update()
        )
        if recovery:
            recovery.used_at = now()
            audit(db, "auth.recovery_code_used", user_id=user.id)
            return True
    return False


def has_recovery_codes(db, user_id) -> bool:
    return bool(
        db.scalar(
            select(RecoveryCode.id)
            .where(RecoveryCode.user_id == user_id, RecoveryCode.used_at.is_(None))
            .limit(1)
        )
    )


def recovery_codes(db, vault, user_id):
    db.execute(delete(RecoveryCode).where(RecoveryCode.user_id == user_id))
    values = ["rc_" + secrets.token_urlsafe(16) for _ in range(10)]
    db.add_all(
        [
            RecoveryCode(user_id=user_id, code_digest=vault.digest("recovery", code))
            for code in values
        ]
    )
    return values


def issue_tokens(db, request: Request, response: Response, session: AuthSession):
    settings, vault = request.app.state.settings, request.app.state.vault
    access, refresh, csrf = new_token("pa_"), new_token("pr_"), new_token("pc_")
    expires = min(now() + timedelta(seconds=settings.access_ttl_seconds), session.expires_at)
    db.add(
        AccessToken(
            session_id=session.id,
            token_digest=vault.digest("access", access),
            expires_at=expires,
        )
    )
    db.add(RefreshToken(session_id=session.id, token_digest=vault.digest("refresh", refresh)))
    session.csrf_digest = vault.digest("csrf", csrf)
    db.commit()
    expires_in = max(0, int((expires - now()).total_seconds()))
    if session.client == "web":
        common = {"secure": settings.cookie_secure, "samesite": "strict"}
        remaining = max(0, int((session.expires_at - now()).total_seconds()))
        response.set_cookie(
            "perk_access",
            access,
            httponly=True,
            path="/api/v1",
            max_age=expires_in,
            **common,
        )
        response.set_cookie(
            "perk_refresh",
            refresh,
            httponly=True,
            path="/api/v1/auth",
            max_age=remaining,
            **common,
        )
        response.set_cookie(
            "perk_csrf", csrf, httponly=False, path="/", max_age=remaining, **common
        )
        return TokenResponse(
            expires_in=expires_in,
            csrf_token=csrf,
            mfa_required=not bool(session.mfa_verified_at),
        )
    return TokenResponse(
        access_token=access,
        refresh_token=refresh,
        expires_in=expires_in,
        mfa_required=not bool(session.mfa_verified_at),
    )


def start_session(db, request, response, user, client, method=None):
    """method: None for a password-only session; otherwise the verified second factor."""
    return issue_tokens(db, request, response, create_session(db, request, user, client, method))


def create_session(db, request, user, client, method=None):
    current = now()
    session = AuthSession(
        user_id=user.id,
        client=client,
        expires_at=current + timedelta(seconds=request.app.state.settings.session_ttl_seconds),
        mfa_verified_at=current if method else None,
        step_up_at=current if method else None,
        strong_step_up_at=current if method in STRONG_METHODS else None,
        csrf_digest="pending",
    )
    db.add(session)
    db.flush()
    return session


def rotate(db, request, response, supplied):
    cookie = request.cookies.get("perk_refresh")
    if cookie and supplied:
        raise HTTPException(400, "Используйте один способ обновления сессии.")
    token = cookie or supplied
    if not token or not re.fullmatch(r"pr_[A-Za-z0-9_-]{43}", token):
        raise HTTPException(401, "Сессия завершена. Войдите снова.")
    digest = request.app.state.vault.digest("refresh", token)
    found = db.scalar(select(RefreshToken).where(RefreshToken.token_digest == digest))
    if not found:
        raise HTTPException(401, "Сессия завершена. Войдите снова.")
    # One lock order for refresh/revocation. Reload the token after acquiring the session lock.
    session = db.scalar(
        select(AuthSession).where(AuthSession.id == found.session_id).with_for_update()
    )
    token_row = db.scalar(
        select(RefreshToken)
        .where(RefreshToken.id == found.id)
        .execution_options(populate_existing=True)
    )
    if session.revoked_at or session.expires_at <= now():
        raise HTTPException(401, "Сессия завершена. Войдите снова.")
    if (cookie is not None) != (session.client == "web"):
        raise HTTPException(401, "Сессия завершена. Войдите снова.")
    if cookie and token_row.used_at and token_row.used_at > now() - timedelta(seconds=15):
        successor = db.scalar(
            select(RefreshToken)
            .where(
                RefreshToken.session_id == session.id,
                RefreshToken.used_at.is_(None),
                RefreshToken.created_at >= token_row.created_at,
            )
            .limit(1)
        )
        latest_used = db.scalar(
            select(RefreshToken.id)
            .where(RefreshToken.session_id == session.id, RefreshToken.used_at.is_not(None))
            .order_by(RefreshToken.used_at.desc())
            .limit(1)
        )
        if (
            successor
            and latest_used == token_row.id
            and request.headers.get("origin") in request.app.state.settings.cors_origins
        ):
            # No tokens are issued and replay protection resumes after this collision window.
            raise HTTPException(
                409,
                {"code": "session_rotated", "message": "Сессия обновлена. Повторите действие."},
            )
    if cookie:
        check_csrf(request, session)
    elif request.headers.get("origin"):
        raise HTTPException(403, "Разрешите cookies и войдите в аккаунт через сайт.")
    user = db.get(User, session.user_id)
    if not user.is_active:
        raise HTTPException(401, "Сессия завершена. Войдите снова.")
    set_actor(db, user.id)
    if token_row.used_at:
        session.revoked_at = now()
        audit(db, "auth.refresh_replay", user_id=user.id, success=False)
        db.commit()
        raise HTTPException(401, "Сессия завершена. Войдите снова.")
    token_row.used_at = now()
    return issue_tokens(db, request, response, session)


def revoke_all(db, user_id):
    from app.modules.notifications.service import revoke_devices

    revoke_devices(db, user_id)
    db.execute(
        update(AuthSession)
        .where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=now())
    )


def clear_cookies(response, settings):
    for name, path in [
        ("perk_access", "/api/v1"),
        ("perk_refresh", "/api/v1/auth"),
        ("perk_csrf", "/"),
    ]:
        response.delete_cookie(
            name,
            path=path,
            secure=settings.cookie_secure,
            httponly=name != "perk_csrf",
            samesite="strict",
        )
