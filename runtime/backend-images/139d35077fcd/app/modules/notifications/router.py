import hmac
import re
import secrets
from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.integrations.notifications import DeliveryError
from app.modules.accounts.access import effective
from app.modules.audit.service import audit
from app.modules.auth.dependencies import DB, FullIdentity, now
from app.modules.auth.schemas import MessageResponse
from app.modules.notifications import service
from app.modules.notifications.models import Notification, PushDevice
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from redis.exceptions import RedisError
from sqlalchemy import and_, false, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert

router = APIRouter(prefix="/notifications", tags=["Notifications"])
webhook_router = APIRouter(prefix="/integrations/telegram", tags=["Notifications"])
LINK_TTL = 600
PUSH_TOKEN = re.compile(r"^Expo(nent)?PushToken\[[A-Za-z0-9_\-]{10,200}\]$")


class NotificationView(BaseModel):
    id: UUID
    kind: str
    severity: Literal["high", "medium", "info"]
    workspace_id: UUID | None
    store_id: UUID | None
    title: str
    body: str
    data: dict
    created_at: datetime
    read_at: datetime | None
    acknowledged_at: datetime | None = None
    resolved_at: datetime | None = None


class NotificationFeed(BaseModel):
    items: list[NotificationView]
    unread_count: int


class NotificationCategories(BaseModel):
    model_config = ConfigDict(extra="forbid")
    orders: bool = True
    stock: bool = True
    finance: bool = True
    supplies: bool = True
    connection: bool = True


class SettingsView(BaseModel):
    digest_enabled: bool
    digest_hour: int
    digest_mode: Literal["morning", "evening"]
    timezone: str
    quiet_start: int
    quiet_end: int
    show_details: bool
    categories: NotificationCategories
    alerts_enabled: bool
    telegram_enabled: bool
    push_enabled: bool
    telegram_linked: bool
    push_available: bool = False


class SettingsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    digest_enabled: bool | None = None
    digest_hour: int | None = Field(default=None, ge=0, le=23)
    digest_mode: Literal["morning", "evening"] | None = None
    timezone: str | None = Field(default=None, max_length=64)
    quiet_start: int | None = Field(default=None, ge=0, le=23)
    quiet_end: int | None = Field(default=None, ge=0, le=23)
    show_details: bool | None = None
    categories: NotificationCategories | None = None
    alerts_enabled: bool | None = None
    telegram_enabled: bool | None = None
    push_enabled: bool | None = None

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value):
        if value is not None:
            try:
                ZoneInfo(value)
            except ZoneInfoNotFoundError, ValueError:
                raise ValueError("Выберите существующий часовой пояс.") from None
        return value


class TelegramLink(BaseModel):
    url: str = Field(description="Open in Telegram and press Start; valid for 10 minutes.")
    expires_in: int


class DeviceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(min_length=20, max_length=220)
    platform: Literal["ios", "android", "web"]


def settings_view(row, request=None):
    fields = (
        "digest_enabled",
        "digest_hour",
        "alerts_enabled",
        "telegram_enabled",
        "push_enabled",
        "digest_mode",
        "timezone",
        "quiet_start",
        "quiet_end",
        "show_details",
    )
    return SettingsView(
        **{key: getattr(row, key) for key in fields},
        categories=NotificationCategories(**row.categories),
        telegram_linked=bool(row.telegram_chat_ciphertext),
        push_available=bool(request and request.app.state.settings.push_provider == "expo"),
    )


@router.get("", response_model=NotificationFeed, operation_id="notificationsList")
def feed(
    request: Request,
    db: DB,
    identity: FullIdentity,
    unread_only: bool = False,
    before: datetime | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
):
    """Newest first; page with `before` = created_at of the last item."""
    from app.modules.auth.models import Membership

    members = db.scalars(select(Membership).where(Membership.user_id == identity.user.id)).all()
    from app.modules.notifications.rules import PERMISSIONS

    kinds = set(PERMISSIONS)
    visible = []
    for member in members:
        allowed = [
            kind
            for kind in kinds
            if service.can_receive(
                db,
                identity.user.id,
                member.workspace_id,
                None,
                kind,
                memberships=members,
            )
        ]
        stores = (
            True
            if member.role in {"owner", "admin"} or member.store_ids is None
            else or_(
                Notification.store_id.is_(None),
                Notification.store_id.in_([UUID(value) for value in member.store_ids]),
            )
        )
        visible.append(
            and_(
                Notification.workspace_id == member.workspace_id,
                Notification.kind.in_(allowed),
                Notification.required_permissions.contained_by(effective(member)),
                stores,
                True
                if member.role in {"owner", "admin"} or member.store_ids is None
                else Notification.source_store_ids.contained_by(member.store_ids),
            )
        )
    if service.can_receive(db, identity.user.id, None, None, "digest", memberships=members):
        visible.append(Notification.workspace_id.is_(None))
    conditions = [
        Notification.user_id == identity.user.id,
        or_(*visible) if visible else false(),
    ]
    query = select(Notification).where(*conditions)
    if unread_only:
        query = query.where(Notification.read_at.is_(None))
    if before:
        query = query.where(Notification.created_at < before)
    rows = db.scalars(
        query.order_by(Notification.created_at.desc(), Notification.id.desc()).limit(limit)
    ).all()
    unread = db.scalar(
        select(func.count())
        .select_from(Notification)
        .where(*conditions, Notification.read_at.is_(None))
    )
    return NotificationFeed(
        items=[service.view(request.app.state.vault, row) for row in rows],
        unread_count=unread,
    )


@router.post("/{notification_id}/read", status_code=204, operation_id="notificationsRead")
def mark_read(notification_id: UUID, db: DB, identity: FullIdentity):
    db.execute(
        update(Notification)
        .where(
            Notification.id == notification_id,
            Notification.user_id == identity.user.id,
            Notification.read_at.is_(None),
        )
        .values(read_at=now())
    )
    db.commit()


@router.post("/read-all", status_code=204, operation_id="notificationsReadAll")
def mark_all_read(db: DB, identity: FullIdentity):
    db.execute(
        update(Notification)
        .where(Notification.user_id == identity.user.id, Notification.read_at.is_(None))
        .values(read_at=now())
    )
    db.commit()


@router.get("/settings", response_model=SettingsView, operation_id="notificationsSettings")
def get_settings(request: Request, db: DB, identity: FullIdentity):
    row = service.settings_for(db, identity.user.id)
    db.commit()
    return settings_view(row, request)


@router.put("/settings", response_model=SettingsView, operation_id="notificationsSaveSettings")
def save_settings(data: SettingsInput, request: Request, db: DB, identity: FullIdentity):
    row = service.settings_for(db, identity.user.id, lock=True)
    for field, value in data.model_dump(exclude_none=True).items():
        if field == "categories":
            value = {**row.categories, **data.categories.model_dump(exclude_unset=True)}
        setattr(row, field, value)
    db.commit()
    return settings_view(row, request)


@router.post(
    "/telegram/link",
    response_model=TelegramLink,
    operation_id="notificationsTelegramLink",
)
def telegram_link(request: Request, identity: FullIdentity):
    state = request.app.state
    if state.telegram_bot is None:
        raise HTTPException(503, "Уведомления в Telegram сейчас недоступны.")
    code = secrets.token_urlsafe(24)
    try:
        state.redis.set(
            "perk:tg-link:" + state.vault.digest("tg-link", code),
            str(identity.user.id),
            ex=LINK_TTL,
        )
    except RedisError:
        raise HTTPException(503, "Попробуйте позже.") from None
    username = state.settings.telegram_bot_username
    return TelegramLink(url=f"https://t.me/{username}?start={code}", expires_in=LINK_TTL)


@router.delete(
    "/telegram",
    response_model=MessageResponse,
    operation_id="notificationsTelegramUnlink",
)
def telegram_unlink(db: DB, identity: FullIdentity):
    row = service.settings_for(db, identity.user.id, lock=True)
    row.telegram_chat_ciphertext, row.telegram_linked_at = None, None
    audit(db, "notifications.telegram_unlinked", user_id=identity.user.id)
    db.commit()
    return MessageResponse(message="Telegram отключён")


@router.post("/devices", status_code=204, operation_id="notificationsRegisterDevice")
def register_device(data: DeviceInput, request: Request, db: DB, identity: FullIdentity):
    if not PUSH_TOKEN.fullmatch(data.token):
        raise HTTPException(422, "Неподдерживаемый push-токен.")
    vault = request.app.state.vault
    digest = vault.digest("push-device", data.token)
    row = db.scalar(select(PushDevice).where(PushDevice.token_digest == digest))
    if row is None or row.user_id != identity.user.id:
        count = db.scalar(
            select(func.count())
            .select_from(PushDevice)
            .where(PushDevice.user_id == identity.user.id)
        )
        if count >= 20:
            raise HTTPException(
                409, "Достигнут лимит устройств. Выйдите из старых сессий в профиле."
            )
    values = dict(
        user_id=identity.user.id,
        token_digest=digest,
        token_ciphertext=vault.seal(data.token, service.device_aad(identity.user.id, digest)),
        platform=data.platform,
        session_id=identity.session.id,
        session_started_at=identity.session.created_at,
        last_seen_at=now(),
    )
    # A delayed request from the previous login cannot take the device back.
    db.execute(
        insert(PushDevice)
        .values(**values)
        .on_conflict_do_update(
            index_elements=["token_digest"],
            set_=values,
            where=or_(
                PushDevice.session_started_at.is_(None),
                PushDevice.session_started_at <= identity.session.created_at,
            ),
        )
    )
    db.commit()


@router.delete("/devices", status_code=204, operation_id="notificationsRemoveDevice")
def remove_device(data: DeviceInput, request: Request, db: DB, identity: FullIdentity):
    digest = request.app.state.vault.digest("push-device", data.token)
    row = db.scalar(
        select(PushDevice).where(
            PushDevice.token_digest == digest, PushDevice.user_id == identity.user.id
        )
    )
    if row:
        db.delete(row)
        db.commit()


def webhook_secret(settings):
    if settings.telegram_bot_provider == "bot":
        return Path(settings.telegram_webhook_secret_file).read_text(encoding="utf-8").strip()
    if settings.telegram_bot_provider == "fake" and settings.app_env in {
        "local",
        "test",
    }:
        return "dev"
    return None


@webhook_router.post("/webhook", include_in_schema=False)
async def telegram_webhook(request: Request):
    """Telegram calls this with the secret header. Only `/start <code>` links a chat."""
    state = request.app.state
    expected = webhook_secret(state.settings)
    supplied = request.headers.get("x-telegram-bot-api-secret-token", "")
    if not expected or not hmac.compare_digest(supplied, expected):
        raise HTTPException(404)
    try:
        update_body = await request.json()
        message = update_body.get("message") or {}
        text = str(message.get("text", ""))
        chat_id = str(message["chat"]["id"])
    except ValueError, KeyError, TypeError, AttributeError:
        return {"ok": True}
    match = re.fullmatch(r"/start ([A-Za-z0-9_-]{20,64})", text.strip())
    if not match:
        return {"ok": True}
    from starlette.concurrency import run_in_threadpool

    return await run_in_threadpool(link_chat, request, match[1], chat_id)


def link_chat(request, code, chat_id):
    from sqlalchemy.orm import Session

    state = request.app.state
    key = "perk:tg-link:" + state.vault.digest("tg-link", code)
    try:
        user_id = state.redis.getdel(key)
    except RedisError:
        return {"ok": True}
    if not user_id:
        return {"ok": True}
    with Session(state.db_engine) as db:
        row = service.settings_for(db, UUID(user_id), lock=True)
        row.telegram_chat_ciphertext = state.vault.seal(chat_id, service.chat_aad(row.user_id))
        row.telegram_linked_at = now()
        audit(db, "notifications.telegram_linked", user_id=row.user_id)
        db.commit()
    try:
        state.telegram_bot.send_message(
            chat_id, "Готово! Сводки и важные уведомления PERK будут приходить сюда."
        )
    except DeliveryError:
        pass
    return {"ok": True}


def owned_notification(db, identity, notification_id):
    row = db.scalar(
        select(Notification)
        .where(Notification.id == notification_id, Notification.user_id == identity.user.id)
        .with_for_update()
    )
    if not row or not service.can_receive(
        db,
        identity.user.id,
        row.workspace_id,
        row.store_id,
        row.kind,
        source_store_ids=row.source_store_ids,
        required_permissions=row.required_permissions,
    ):
        raise HTTPException(404, "Уведомление не найдено или доступ отозван.")
    return row


@router.post("/test", response_model=MessageResponse, operation_id="notificationsTest")
def test_push(request: Request, db: DB, identity: FullIdentity):
    from app.modules.notifications.delivery import active_devices

    devices = active_devices(db, identity.user.id)
    if not devices:
        raise HTTPException(409, "Сначала включите уведомления на этом устройстве.")
    if request.app.state.settings.push_provider != "expo":
        raise HTTPException(409, "Отправка пушей ещё не подключена.")
    try:
        if not request.app.state.redis.set(
            f"perk:push-test:{identity.user.id}", "1", nx=True, ex=60
        ):
            raise HTTPException(429, "Повторную проверку можно отправить через минуту.")
    except RedisError:
        raise HTTPException(503, "Проверка временно недоступна.") from None
    push = request.app.state.push
    vault = request.app.state.vault
    tokens = [
        vault.open(row.token_ciphertext, service.device_aad(identity.user.id, row.token_digest))
        for row in devices
    ]
    try:
        tickets = push.send_notifications(
            tokens,
            "PERK · проверка уведомлений",
            "Всё готово. Здесь будут важные события ваших магазинов.",
            {"test": True, "recipient_id": str(identity.user.id)},
            channel="perk_updates",
            category="perk_open",
        )
        if not any(ticket.get("status") == "ok" for ticket in tickets):
            raise DeliveryError("push_unavailable")
    except DeliveryError:
        raise HTTPException(503, "Не удалось отправить проверку. Повторите позже.") from None
    return MessageResponse(message="Проверка отправлена на ваши устройства.")


@router.get("/{notification_id}", response_model=NotificationView, operation_id="notificationsGet")
def get_notification(notification_id: UUID, request: Request, db: DB, identity: FullIdentity):
    return service.view(request.app.state.vault, owned_notification(db, identity, notification_id))


@router.post(
    "/{notification_id}/acknowledge",
    response_model=NotificationView,
    operation_id="notificationsAcknowledge",
)
def acknowledge_notification(
    notification_id: UUID, request: Request, db: DB, identity: FullIdentity
):
    row = owned_notification(db, identity, notification_id)
    if row.kind != "digest" and not row.resolved_at:
        row.acknowledged_at = row.acknowledged_at or now()
    row.read_at = row.read_at or now()
    db.commit()
    return service.view(request.app.state.vault, row)
