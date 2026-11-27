import hmac
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db, set_actor
from app.modules.auth.models import AccessToken, AuthSession, User

DB = Annotated[Session, Depends(get_db)]
bearer = HTTPBearer(auto_error=False)


def now():
    return datetime.now(UTC)


def check_csrf(request: Request, session: AuthSession) -> None:
    origin = request.headers.get("origin")
    value = request.headers.get("x-csrf-token", "")
    if origin not in request.app.state.settings.cors_origins or not value or len(value) > 100:
        raise HTTPException(
            403, "Не удалось подтвердить запрос. Обновите страницу и повторите действие."
        )
    if not hmac.compare_digest(request.app.state.vault.digest("csrf", value), session.csrf_digest):
        raise HTTPException(
            403, "Не удалось подтвердить запрос. Обновите страницу и повторите действие."
        )


@dataclass
class Identity:
    user: User
    session: AuthSession


def current_identity(
    request: Request,
    db: DB,
    authorization: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> Identity:
    cookie = request.cookies.get("perk_access")
    if authorization and cookie:
        raise HTTPException(400, "Используйте один способ входа.")
    token = authorization.credentials if authorization else cookie
    if not token or not re.fullmatch(r"pa_[A-Za-z0-9_-]{43}", token):
        raise HTTPException(401, "Войдите в аккаунт.", headers={"WWW-Authenticate": "Bearer"})
    digest = request.app.state.vault.digest("access", token)
    record = db.execute(
        select(AccessToken, AuthSession, User)
        .join(AuthSession, AccessToken.session_id == AuthSession.id)
        .join(User, AuthSession.user_id == User.id)
        .where(AccessToken.token_digest == digest)
    ).first()
    if not record:
        raise HTTPException(401, "Войдите в аккаунт.")
    access, session, user = record
    if (
        not user.is_active
        or session.revoked_at
        or session.expires_at <= now()
        or access.expires_at <= now()
    ):
        raise HTTPException(401, "Войдите в аккаунт.")
    if (cookie is not None) != (session.client == "web"):
        raise HTTPException(401, "Способ входа изменился. Войдите в аккаунт заново.")
    if cookie and request.method not in {"GET", "HEAD", "OPTIONS"}:
        check_csrf(request, session)
    from app.security.limits import rate_limit

    rate_limit(
        request.app.state.redis,
        request.app.state.vault,
        "api-user",
        str(user.id),
        request.app.state.settings.api_limit_per_minute,
    )
    set_actor(db, user.id)
    return Identity(user, session)


CurrentIdentity = Annotated[Identity, Depends(current_identity)]


STEP_UP_WINDOW = timedelta(minutes=5)


def fresh(moment) -> bool:
    return bool(moment and moment > now() - STEP_UP_WINDOW)


def full_identity(identity: CurrentIdentity) -> Identity:
    if not identity.user.email_verified_at or not identity.session.mfa_verified_at:
        raise HTTPException(
            403,
            {"code": "mfa_required", "message": "Подтвердите вход кодом."},
        )
    return identity


FullIdentity = Annotated[Identity, Depends(full_identity)]


def recent_identity(identity: FullIdentity) -> Identity:
    if not fresh(identity.session.step_up_at):
        raise HTTPException(
            403,
            {
                "code": "step_up_required",
                "strong": False,
                "message": "Подтвердите действие кодом.",
            },
        )
    return identity


RecentIdentity = Annotated[Identity, Depends(recent_identity)]


def strong_identity(identity: FullIdentity) -> Identity:
    # Store tokens and account factors need a phone/app code, never email alone.
    if not identity.user.has_strong_factor:
        raise HTTPException(
            403,
            {
                "code": "strong_factor_required",
                "message": "Сначала привяжите телефон или приложение для кодов.",
            },
        )
    if not fresh(identity.session.strong_step_up_at):
        raise HTTPException(
            403,
            {
                "code": "step_up_required",
                "strong": True,
                "message": "Подтвердите действие кодом.",
            },
        )
    return identity


StrongIdentity = Annotated[Identity, Depends(strong_identity)]
