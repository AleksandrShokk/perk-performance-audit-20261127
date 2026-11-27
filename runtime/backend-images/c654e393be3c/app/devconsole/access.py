import hashlib
import hmac
import json
import re
from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, SecretStr, model_validator
from sqlalchemy import select

from app.core.config import Settings
from app.db.session import set_actor
from app.modules.accounts.models import Store
from app.modules.auth.dependencies import DB, Identity
from app.modules.auth.models import Membership, User

COOKIE = "perk_local_dev"


class ConsoleSettings(Settings):
    dev_console_enabled: bool = False
    dev_grant_file: Path = Path(".secrets/dev-console/grant.json")

    @model_validator(mode="after")
    def local_only(self):
        if not self.dev_console_enabled or self.app_env != "local":
            raise ValueError("Development console requires explicit enablement and APP_ENV=local")
        return self


class Grant(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: SecretStr
    user_id: UUID
    workspace_id: UUID
    store_id: UUID
    bootstrap_digest: str
    bootstrap_expires_at: float

    @model_validator(mode="after")
    def valid_token(self):
        if not re.fullmatch(r"pd_[A-Za-z0-9_-]{43}", self.token.get_secret_value()):
            raise ValueError("Invalid local grant")
        return self


def read_grant(request: Request) -> Grant:
    # Read each time: revocation/rotation takes effect without a server restart.
    try:
        return Grant.model_validate_json(request.app.state.settings.dev_grant_file.read_text())
    except OSError, ValueError, json.JSONDecodeError:
        raise HTTPException(503, "Локальный доступ отозван или не настроен.") from None


def csrf_token(grant: Grant):
    return hmac.new(
        grant.token.get_secret_value().encode(), b"dev-console-csrf", hashlib.sha256
    ).hexdigest()


def authenticate(request: Request) -> Grant:
    grant = read_grant(request)
    authorization = request.headers.get("authorization", "")
    cookie = request.cookies.get(COOKIE)
    if authorization and cookie:
        raise HTTPException(400, "Используйте один способ входа.")
    supplied = authorization.removeprefix("Bearer ") if authorization else cookie
    if not supplied or not hmac.compare_digest(supplied, grant.token.get_secret_value()):
        raise HTTPException(401, "Откройте консоль по новой локальной ссылке запуска.")
    if cookie and request.method not in {"GET", "HEAD", "OPTIONS"}:
        if not hmac.compare_digest(request.headers.get("x-csrf-token", ""), csrf_token(grant)):
            raise HTTPException(
                403, "Не удалось подтвердить запрос. Обновите страницу и повторите действие."
            )
    return grant


GrantDependency = Annotated[Grant, Depends(authenticate)]


def scoped_identity(db: DB, grant: GrantDependency):
    # Forced RLS on memberships/stores: checks run as the grant owner, not as nobody.
    set_actor(db, grant.user_id)
    user = db.get(User, grant.user_id)
    membership = db.scalar(
        select(Membership).where(
            Membership.user_id == grant.user_id,
            Membership.workspace_id == grant.workspace_id,
            Membership.role == "owner",
        )
    )
    store = db.scalar(
        select(Store).where(
            Store.id == grant.store_id,
            Store.workspace_id == grant.workspace_id,
            Store.marketplace == "wildberries",
            Store.is_active.is_(True),
        )
    )
    if not user or not user.is_active or not user.email_verified_at or not membership or not store:
        raise HTTPException(403, "Владелец локального доступа или магазин больше не активен.")
    set_actor(db, user.id)
    # Explicit local operator grant, NOT an MFA-verified web/mobile session.
    # Only the console's read/import routes use it; auth/account changes are not mounted.
    return Identity(user=user, session=None)


ConsoleIdentity = Annotated[Identity, Depends(scoped_identity)]
