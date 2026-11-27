"""Bound sessions, per-device tickets and receipts; no blind delivery retries."""

import logging
from datetime import UTC, timedelta

from app.integrations.notifications import DeliveryError
from app.modules.auth.dependencies import now
from app.modules.auth.models import AuthSession
from app.modules.notifications import rules, service
from app.modules.notifications.models import Notification, PushDevice
from sqlalchemy import case, func, select

logger = logging.getLogger(__name__)
PERMANENT_ERRORS = {
    "DeviceNotRegistered",
    "MessageTooBig",
    "MismatchSenderId",
    "InvalidCredentials",
}


def active_devices(db, user_id):
    return list(
        db.scalars(
            select(PushDevice)
            .join(AuthSession, AuthSession.id == PushDevice.session_id)
            .where(
                PushDevice.user_id == user_id,
                AuthSession.user_id == user_id,
                AuthSession.revoked_at.is_(None),
                AuthSession.expires_at > now(),
                AuthSession.mfa_verified_at.is_not(None),
            )
            .order_by(PushDevice.last_seen_at.desc())
            .limit(20)
        ).all()
    )


def enabled(settings, kind):
    if kind == "digest":
        return settings.digest_enabled
    return settings.alerts_enabled and settings.categories.get(rules.CATEGORY.get(kind), True)


def check_receipts(db, push, state, devices):
    pending = {
        value["ticket"]: key
        for key, value in state.items()
        if value.get("ticket")
        and not value.get("receipt")
        and now().timestamp() - value.get("sent_at", 0) >= 900
    }
    if not pending:
        return
    try:
        receipts = push.get_receipts(list(pending))
    except DeliveryError:
        return
    for ticket, receipt in receipts.items():
        key = pending.get(ticket)
        if not key:
            continue
        state[key]["receipt"] = receipt["status"]
        error = receipt.get("details", {}).get("error")
        if error:
            state[key]["error"] = str(error)[:64]
        if error == "DeviceNotRegistered" and key in devices:
            db.delete(devices[key])
            del devices[key]


def send_push(db, vault, row, push, settings, devices, payload, state):
    pending = []
    for key, device in devices.items():
        last = state.get(key, {})
        if (
            last.get("ticket")
            or last.get("error") in PERMANENT_ERRORS
            or last.get("attempts", 0) >= 3
        ):
            continue
        if now().timestamp() - last.get("last_try", 0) < 300:
            continue
        token = vault.open(device.token_ciphertext, service.device_aad(row.user_id, key))
        pending.append((key, token))
    if not pending:
        return False
    title = payload["title"] if settings.show_details else "PERK · важное событие"
    body = (
        payload["body"] if settings.show_details else "Откройте PERK, чтобы посмотреть подробности."
    )
    store_name = payload.get("data", {}).get("store_name")
    if settings.show_details and store_name and store_name not in title:
        body = f"{store_name} · {body}"
    channel = (
        "perk_digest"
        if row.kind == "digest"
        else "perk_critical"
        if row.severity == "high"
        else "perk_updates"
    )
    try:
        tickets = push.send_notifications(
            [token for _, token in pending],
            title,
            body,
            {"notification_id": str(row.id), "recipient_id": str(row.user_id), "kind": row.kind},
            channel=channel,
            category="perk_open" if row.kind == "digest" else "perk_action",
        )
    except DeliveryError:
        tickets = [{"status": "error", "details": {"error": "unavailable"}}] * len(pending)
        logger.warning("notification_push_unavailable")
    accepted = False
    for (key, _), ticket in zip(pending, tickets, strict=True):
        previous = state.get(key, {})
        value = {"attempts": previous.get("attempts", 0) + 1, "last_try": now().timestamp()}
        if ticket["status"] == "ok":
            value.update(ticket=ticket["id"], sent_at=now().timestamp())
            accepted = True
        else:
            error = ticket.get("details", {}).get("error", "unavailable")
            value["error"] = str(error)[:64]
            if error == "DeviceNotRegistered":
                db.delete(devices.pop(key))
        state[key] = value
    return accepted


def deliver(db, vault, user_id, telegram, push):
    settings = service.settings_for(db, user_id, lock=True)
    devices = {row.token_digest: row for row in active_devices(db, user_id)}
    stamp = now()
    midnight = (
        rules.local_time(stamp, settings)
        .replace(hour=0, minute=0, second=0, microsecond=0)
        .astimezone(UTC)
    )
    sent_today = db.scalar(
        select(func.count())
        .select_from(Notification)
        .where(
            Notification.user_id == user_id,
            Notification.delivered_at >= midnight,
            Notification.kind != "digest",
        )
    )
    rows = db.scalars(
        select(Notification)
        .where(
            Notification.user_id == user_id,
            Notification.kind.in_(rules.PERMISSIONS),
            Notification.created_at > stamp - timedelta(hours=24),
        )
        .order_by(
            case((Notification.kind == "digest", 0), (Notification.severity == "high", 1), else_=2),
            Notification.created_at.desc(),
        )
        .limit(100)
        .with_for_update(skip_locked=True)
    ).all()
    sent = 0
    for row in rows:
        state = dict(row.delivery_state or {})
        push_state = {key: dict(value) for key, value in state.get("push", {}).items()}
        if push:
            check_receipts(db, push, push_state, devices)
        state["push"] = push_state
        allowed = (
            row.kind in rules.PERMISSIONS
            and enabled(settings, row.kind)
            and service.can_receive(
                db,
                user_id,
                row.workspace_id,
                row.store_id,
                row.kind,
                source_store_ids=row.source_store_ids,
                required_permissions=row.required_permissions,
            )
            and not row.acknowledged_at
            and not row.resolved_at
            and not row.read_at
        )
        if (
            not allowed
            or rules.is_quiet(stamp, settings)
            or (sent_today >= 5 and row.kind != "digest" and not row.delivered_at)
        ):
            row.delivery_state = state
            continue
        payload = service.view(vault, row)
        accepted = False
        if settings.push_enabled and push and devices:
            accepted = send_push(db, vault, row, push, settings, devices, payload, push_state)
        if (
            settings.telegram_enabled
            and telegram
            and settings.telegram_chat_ciphertext
            and not state.get("telegram")
        ):
            try:
                chat = vault.open(settings.telegram_chat_ciphertext, service.chat_aad(user_id))
                telegram.send_message(chat, payload["title"] + "\n" + payload["body"])
                state["telegram"] = True
                accepted = True
            except DeliveryError:
                logger.warning("notification_telegram_unavailable")
        if accepted and not row.delivered_at:
            row.delivered_at = stamp
            sent += 1
            if row.kind != "digest":
                sent_today += 1
        row.delivery_state = state
    return sent
