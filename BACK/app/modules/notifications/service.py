"""Alerts and digests built from precomputed snapshots; delivery to Telegram and push.

Generation only reads snapshots: a slow report never delays a notification run.
"""

import json
import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from app.modules.accounts.access import allows, store_allowed
from app.modules.accounts.models import Store, Workspace
from app.modules.auth.dependencies import now
from app.modules.auth.models import Membership
from app.modules.insights import snapshots
from app.modules.notifications.models import (
    Notification,
    NotificationSettings,
    PushDevice,
)
from app.modules.sync.schemas import moscow_today
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

logger = logging.getLogger(__name__)
SEND_KINDS = {"digest"}
TOKEN_WARNING = timedelta(days=7)
ANOMALY_MIN_AVERAGE = 5


def notification_aad(user_id, notification_id):
    return f"perk-notification:v1:{user_id}:{notification_id}"


def chat_aad(user_id):
    return f"perk-telegram-chat:v1:{user_id}"


def device_aad(user_id, digest):
    return f"perk-push-device:v1:{user_id}:{digest}"


def moscow_hour():
    return (datetime.now(UTC) + timedelta(hours=3)).hour


def settings_for(db, user_id, lock=False):
    query = select(NotificationSettings).where(NotificationSettings.user_id == user_id)
    row = db.scalar(query.with_for_update() if lock else query)
    if row is None:
        db.execute(
            insert(NotificationSettings)
            .values(user_id=user_id)
            .on_conflict_do_nothing(index_elements=["user_id"])
        )
        row = db.scalar(query.with_for_update() if lock else query)
    return row


def can_receive(
    db,
    user_id,
    workspace_id,
    store_id,
    kind,
    *,
    memberships=None,
    source_store_ids=None,
    required_permissions=None,
):
    if memberships is None:
        memberships = db.scalars(select(Membership).where(Membership.user_id == user_id)).all()
    if workspace_id is None:
        # Old digests have no per-store scope. Only unrestricted read access can see them.
        return bool(memberships) and all(
            row.store_ids is None
            and all(
                allows(row, p)
                for p in (
                    "analytics.read",
                    "inventory.read",
                    "finance.read",
                    "profit.read",
                )
            )
            for row in memberships
        )
    member = next((row for row in memberships if row.workspace_id == workspace_id), None)
    if member is None or (store_id and not store_allowed(member, store_id)):
        return False
    if any(not store_allowed(member, value) for value in (source_store_ids or [])):
        return False
    if any(not allows(member, permission) for permission in (required_permissions or [])):
        return False
    from app.modules.notifications.rules import PERMISSIONS

    permission = PERMISSIONS.get(kind)
    if permission == "connection":
        return member.role in {"owner", "admin"}
    return permission is not None and allows(member, permission)


def create(
    db,
    vault,
    user_id,
    *,
    kind,
    severity,
    dedupe,
    title,
    body,
    data=None,
    workspace_id=None,
    store_id=None,
    incident_key=None,
    source_store_ids=None,
    required_permissions=None,
):
    """Insert once per (user, dedupe key). Returns True when a new item was created."""
    if not can_receive(
        db,
        user_id,
        workspace_id,
        store_id,
        kind,
        source_store_ids=source_store_ids,
        required_permissions=required_permissions,
    ):
        return False
    notification_id = uuid4()
    statement = (
        insert(Notification)
        .values(
            id=notification_id,
            user_id=user_id,
            workspace_id=workspace_id,
            store_id=store_id,
            kind=kind,
            incident_key=incident_key,
            source_store_ids=source_store_ids or [],
            required_permissions=required_permissions or [],
            severity=severity,
            dedupe_key=vault.digest("notification", dedupe),
            ciphertext=vault.seal(
                json.dumps(
                    {"title": title, "body": body, "data": data or {}},
                    ensure_ascii=False,
                    default=str,
                ),
                notification_aad(user_id, notification_id),
            ),
        )
        .on_conflict_do_nothing(index_elements=["user_id", "dedupe_key"])
        .returning(Notification.id)
    )
    return db.execute(statement).scalar() is not None


def view(vault, row):
    value = json.loads(vault.open(row.ciphertext, notification_aad(row.user_id, row.id)))
    return {
        "id": row.id,
        "kind": row.kind,
        "severity": row.severity,
        "workspace_id": row.workspace_id,
        "store_id": row.store_id,
        "created_at": row.created_at,
        "read_at": row.read_at,
        "acknowledged_at": row.acknowledged_at,
        "resolved_at": row.resolved_at,
        **value,
    }


def snapshot(db, vault, workspace_id, store_id, kind, params):
    key = snapshots.params_key(vault, kind, params)
    _, data = snapshots.load(db, vault, workspace_id, store_id, kind, key)
    return data


def rub(amount, currency):
    if amount is None:
        return "—"
    value = f"{Decimal(amount).quantize(Decimal(1)):,}".replace(",", " ")
    return f"{value} {'₽' if currency == 'RUB' else currency}"


def store_alerts(db, vault, user_id, store, today, settings=None, redis=None, data=None):
    from app.modules.notifications.engine import evaluate_store

    return evaluate_store(
        db, vault, user_id, store, today, settings or settings_for(db, user_id), redis, data=data
    )


def digest_section(store, dashboard):
    """Compatibility helper: a digest never substitutes buyouts for orders."""
    day = dashboard.get("orders", {}).get("yesterday", {})
    units, amount = day.get("orders"), day.get("orders_amount")
    if units is None or amount is None:
        return f"{store.name}: заказы ещё загружаются"
    return f"{store.name}: заказано {units} шт. на {rub(amount, dashboard['currency'])}"


def generate(db, vault, user_id, redis=None):
    settings = settings_for(db, user_id, lock=True)
    members = db.scalars(select(Membership).where(Membership.user_id == user_id)).all()
    stores = db.scalars(
        select(Store)
        .join(Membership, Membership.workspace_id == Store.workspace_id)
        .where(
            Membership.user_id == user_id,
            Store.is_active.is_(True),
            Store.marketplace.in_(("wildberries", "ozon")),
        )
        .order_by(Store.created_at)
    ).all()
    today = moscow_today()
    from collections import defaultdict

    from app.modules.notifications import digest, engine, facts

    entries = defaultdict(list)
    created = 0
    for store in stores:
        member = next(row for row in members if row.workspace_id == store.workspace_id)
        if not store_allowed(member, store.id):
            continue
        try:
            with db.begin_nested():
                data = facts.read(db, redis, vault, store, today)
                created += store_alerts(
                    db, vault, user_id, store, today, settings=settings, redis=redis, data=data
                )
            if can_receive(
                db, user_id, store.workspace_id, store.id, "digest", memberships=members
            ):
                entries[store.workspace_id].append((store, data))
        except Exception:
            logger.warning("notification_snapshot_unavailable store=%s", store.id)
            if can_receive(
                db, user_id, store.workspace_id, store.id, "digest", memberships=members
            ):
                entries[store.workspace_id].append((store, None))
    for workspace_id, reports in entries.items():
        member = next(row for row in members if row.workspace_id == workspace_id)
        workspace = db.get(Workspace, workspace_id)
        event = digest.build(
            reports,
            now(),
            settings,
            workspace.name,
            inventory_allowed=allows(member, "inventory.read"),
            finance_allowed=allows(member, "finance.read"),
            costs_allowed=allows(member, "profit.read"),
        )
        if event:
            created += engine.publish_scoped(
                db,
                vault,
                user_id,
                workspace_id,
                None,
                event,
                [str(store.id) for store, _ in reports],
            )

    return created


def deliver(db, vault, user_id, telegram, push):
    from app.modules.notifications.delivery import deliver as send

    return send(db, vault, user_id, telegram, push)


def revoke_devices(db, user_id, session_id=None):
    from sqlalchemy import delete

    query = delete(PushDevice).where(PushDevice.user_id == user_id)
    if session_id is not None:
        query = query.where(PushDevice.session_id == session_id)
    db.execute(query)
