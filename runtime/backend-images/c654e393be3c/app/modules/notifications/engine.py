"""Evaluate one shared cabinet snapshot; create incidents with recipient-specific access."""

import json
from datetime import datetime, timedelta

from app.modules.auth.dependencies import now
from app.modules.notifications import facts, rules, service
from app.modules.notifications.models import Notification
from sqlalchemy import select


def publish(db, vault, user_id, store, event):
    event = {
        **event,
        "data": {
            **event.get("data", {}),
            "store_name": store.name,
            "marketplace": store.marketplace,
        },
    }
    return publish_scoped(db, vault, user_id, store.workspace_id, store.id, event, [str(store.id)])


def publish_scoped(db, vault, user_id, workspace_id, store_id, event, sources):
    incident = vault.digest("notification-incident", f"{store_id or workspace_id}:{event['key']}")
    if not service.can_receive(
        db,
        user_id,
        workspace_id,
        store_id,
        event["kind"],
        source_store_ids=sources,
        required_permissions=event.get("required_permissions", []),
    ):
        return 0
    active = db.scalar(
        select(Notification)
        .where(
            Notification.user_id == user_id,
            Notification.incident_key == incident,
            Notification.resolved_at.is_(None),
        )
        .limit(1)
    )
    if active:
        active.source_store_ids = sources
        active.required_permissions = event.get("required_permissions", [])
        # Keep details current without sending the same incident again.
        value = {
            "title": event["title"],
            "body": event["body"],
            "data": {
                **event.get("data", {}),
            },
        }
        active.ciphertext = vault.seal(
            json.dumps(value, ensure_ascii=False, default=str),
            service.notification_aad(user_id, active.id),
        )
        return 0
    return int(
        service.create(
            db,
            vault,
            user_id,
            kind=event["kind"],
            severity=event["severity"],
            dedupe=(
                f"smart-v1:{user_id}:{store_id or workspace_id}:{event['key']}:{now().isoformat()}"
            ),
            title=event["title"],
            body=event["body"],
            data={
                **event.get("data", {}),
            },
            workspace_id=workspace_id,
            store_id=store_id,
            source_store_ids=sources,
            required_permissions=event.get("required_permissions", []),
            incident_key=incident,
        )
    )


def evaluate_store(db, vault, user_id, store, today, settings, redis, data=None):
    data = data if data is not None else facts.read(db, redis, vault, store, today)

    def enabled(category):
        return settings.alerts_enabled and settings.categories.get(category, True)

    events, checked = [], set()
    if enabled("stock") and data["stock_complete"]:
        events += list(rules.stock_events(data["stock"]))
        checked.add("stock")
        checked.add("stock_stale")
    elif (
        enabled("stock")
        and data.get("stock_updated")
        and datetime.fromisoformat(data["stock_updated"]) < now() - timedelta(days=2)
    ):
        events.append(
            {
                "key": "stock-stale",
                "kind": "stock_stale",
                "severity": "medium",
                "title": "Остатки давно не обновлялись",
                "body": "Проверьте подключение кабинета.",
                "data": {
                    "section": "stock",
                    "advice": "Обновите данные перед планированием поставки.",
                },
            }
        )
    if enabled("orders"):
        event = rules.order_event(data["daily"], today, data["currency"])
        if event:
            events.append(event)
    if enabled("finance"):
        events += list(
            rules.financial_events(
                data["finance"], data["previous_finance"], data["finance_period"], data["currency"]
            )
        )
    if enabled("supplies") and data["supplies"] is not None:
        events += list(rules.supply_events(data["supplies"], today))
        checked.add("supply")
    if enabled("connection") and data.get("import_ready"):
        events.append(
            {
                "key": "import-ready",
                "kind": "import_ready",
                "severity": "info",
                "title": "Загрузка кабинета завершена",
                "body": "Заказы, финансы и остатки готовы.",
                "data": {"section": "orders"},
            }
        )
    if enabled("connection"):
        expires = data["token_expires"]
        if expires and datetime.fromisoformat(expires) <= now() + timedelta(days=7):
            events.append(
                {
                    "key": "token",
                    "kind": "token_expiring",
                    "severity": "high",
                    "title": "Ключ доступа истёк"
                    if datetime.fromisoformat(expires) <= now()
                    else "Срок действия ключа скоро закончится",
                    "body": f"Обновите ключ до {datetime.fromisoformat(expires):%d.%m.%Y}.",
                    "data": {
                        "section": "connection",
                        "advice": "Замените ключ, чтобы загрузка данных не остановилась.",
                    },
                }
            )
        elif expires:
            checked.add("token_expiring")
        if data["connection_error"]:
            events.append(
                {
                    "key": "connection",
                    "kind": "sync_failed",
                    "severity": "medium",
                    "title": "Проверьте подключение кабинета",
                    "body": "Не удалось обновить данные. Доступные отчёты сохранены.",
                    "data": {
                        "section": "connection",
                        "advice": "Проверьте состояние загрузки и разрешения API-ключа.",
                    },
                }
            )
        elif data["connection_checked"]:
            checked.add("sync_failed")
    seen = {vault.digest("notification-incident", f"{store.id}:{event['key']}") for event in events}
    # Only confirmed fresh categories can resolve an incident; missing data cannot.
    active = (
        db.scalars(
            select(Notification).where(
                Notification.user_id == user_id,
                Notification.store_id == store.id,
                Notification.kind.in_(checked),
                Notification.resolved_at.is_(None),
            )
        ).all()
        if checked
        else []
    )
    for row in active:
        if row.incident_key not in seen:
            row.resolved_at = now()
    return sum(publish(db, vault, user_id, store, event) for event in events)
