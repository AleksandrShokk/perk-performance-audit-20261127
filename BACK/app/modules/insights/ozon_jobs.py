"""Durable progressive analytics import: 7 recent days first, older windows in background."""

import json
import logging
import time
from datetime import timedelta
from uuid import UUID, uuid4

from redis import Redis
from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import set_actor
from app.integrations.ozon.checkpoint import StockCoverCheckpoint
from app.integrations.ozon.finance import FinanceClient
from app.integrations.ozon.operations import OperationsClient
from app.integrations.ozon.transport import OzonImportError
from app.modules.accounts.ozon_connection import credential_row, open_credentials
from app.modules.auth.dependencies import now
from app.modules.catalog.ozon_jobs import authorized
from app.modules.catalog.ozon_read import snapshot as catalog_snapshot
from app.modules.finance import realizations
from app.modules.insights import ozon_sales
from app.modules.insights.marketplace_models import (
    MarketplaceSalesDay,
    MarketplaceStockCover,
    OzonAnalyticsSync,
)
from app.modules.inventory import ozon_cover
from app.modules.sync.schemas import moscow_today
from app.security.crypto import SecretVault
from app.workers.celery_app import celery_app
from app.workers.database import release_engine
from app.workers.database import worker_engine as build_engine
from app.workers.outbox import actors

logger = logging.getLogger(__name__)


def sales_aad(workspace_id, store_id, day):
    return f"perk-daily-sales:v1:{workspace_id}:{store_id}:{day}"


def configure(db, store, actor):
    end = moscow_today() - timedelta(days=1)
    for source in ("sales", "stock_cover", "finance", "traffic", "supplies"):
        statement = insert(OzonAnalyticsSync).values(
            workspace_id=store.workspace_id,
            store_id=store.id,
            source=source,
            requested_by=actor,
            status="pending",
            next_attempt_at=now(),
            records_processed=0,
            history_from=end - timedelta(days=89 if source == "traffic" else 179),
            cursor=end,
        )
        db.execute(
            statement.on_conflict_do_update(
                index_elements=["workspace_id", "store_id", "source"],
                set_={
                    "requested_by": actor,
                    "updated_at": None,
                    "status": "pending",
                    "run_id": None,
                    "next_attempt_at": now(),
                    "cursor": end,
                    "error_code": None,
                },
            )
        )


def plan(job):
    if job.source not in {"sales", "finance", "traffic"}:
        return
    yesterday = moscow_today() - timedelta(days=1)
    if job.cursor is not None:
        job.mode = "history"
        job.date_to = min(job.cursor, yesterday)
        chunk = 7 if job.updated_at is None or job.source in {"finance", "traffic"} else 28
        job.date_from = max(job.history_from, job.date_to - timedelta(days=chunk - 1))
    else:
        # Recheck the recent two 28-day cohorts even when the app is closed.
        job.mode = "refresh"
        job.date_from, job.date_to = (
            yesterday
            - timedelta(
                days=6 if job.source == "traffic" else 34 if job.source == "finance" else 55
            ),
            yesterday,
        )


def execute(
    engine, vault, workspace_id, store_id, source, actor, run_id, client_factory=OperationsClient
):
    if source in {"traffic", "supplies"}:
        from app.modules.insights.extra_jobs import execute as execute_extra

        return execute_extra(
            engine, vault, workspace_id, store_id, source, actor, run_id, client_factory
        )
    if source == "finance":
        from app.modules.finance.ozon_jobs import execute as execute_finance

        return execute_finance(engine, vault, workspace_id, store_id, actor, run_id, client_factory)
    key = (workspace_id, store_id, source)
    with Session(engine) as db, db.begin():
        store = authorized(db, workspace_id, store_id, actor)
        if not store:
            from app.workers.outbox import reject_ozon

            reject_ozon(db, workspace_id, store_id, source, actor, run_id)
            return
        job = db.get(OzonAnalyticsSync, key, with_for_update=True)
        if not job or job.run_id != run_id or job.status != "queued":
            return
        credential = credential_row(db, store)
        original = credential.ciphertext
        secret = open_credentials(vault, store, credential)
        start, end, mode = job.date_from, job.date_to, job.mode
        catalog = None
        if source == "stock_cover":
            catalog, _ = catalog_snapshot(db, vault, workspace_id, store)
            if catalog is None or any("channel_skus" not in row for row in catalog):
                raise OzonImportError("catalog_not_ready", 30)
        job.status, job.records_processed = "running", 0
        job.next_attempt_at = now() + timedelta(minutes=12)

    def progress(count):
        with Session(engine) as db, db.begin():
            set_actor(db, actor)
            current = db.get(OzonAnalyticsSync, key, with_for_update=True)
            if not current or current.run_id != run_id or current.status != "running":
                raise OzonImportError("import_replaced", 30)
            current.records_processed = count

    client = client_factory(secret["client_id"], secret["api_key"])
    if source == "sales":
        postings, returns = client.sales(
            start, end, ozon_sales.posting, ozon_sales.returned, progress
        )
        days = ozon_sales.aggregate(postings, returns, start, end)
        for value in days.values():
            for item in value["price_items"]:
                item["key"] = realizations.posting_key(vault, workspace_id, store_id, item["key"])
        encoded = {
            day: vault.seal(json.dumps(value), sales_aad(workspace_id, store_id, day))
            for day, value in days.items()
        }
        count = len(postings)
    else:
        skus = sorted(
            {sku for row in catalog for sku in row.get("channel_skus", {}).get("fbo", [])}
        )
        products = ozon_cover.normalize(client.stock_cover(skus))
        encoded = vault.seal(json.dumps(products), ozon_cover.aad(workspace_id, store_id))
        count = len(products)

    with Session(engine) as db, db.begin():
        store = authorized(db, workspace_id, store_id, actor)
        if not store:
            raise OzonImportError("access_revoked", 21600)
        db.refresh(store, with_for_update=True)
        current = credential_row(db, store)
        job = db.get(OzonAnalyticsSync, key, with_for_update=True)
        if not job or job.run_id != run_id or job.status != "running":
            return
        if (
            current.ciphertext != original
            or not store.is_active
            or store.connection_status != "connected"
        ):
            raise OzonImportError("credential_changed", 30)
        stamp = now()
        if source == "sales":
            statement = insert(MarketplaceSalesDay).values(
                [
                    dict(
                        workspace_id=workspace_id,
                        store_id=store_id,
                        day=day,
                        ciphertext=ciphertext,
                        updated_at=stamp,
                    )
                    for day, ciphertext in encoded.items()
                ]
            )
            db.execute(
                statement.on_conflict_do_update(
                    index_elements=["workspace_id", "store_id", "day"],
                    set_={"ciphertext": statement.excluded.ciphertext, "updated_at": stamp},
                )
            )
            if mode == "history":
                job.cursor = start - timedelta(days=1) if start > job.history_from else None
        else:
            statement = insert(MarketplaceStockCover).values(
                workspace_id=workspace_id, store_id=store_id, ciphertext=encoded, updated_at=stamp
            )
            db.execute(
                statement.on_conflict_do_update(
                    index_elements=["workspace_id", "store_id"],
                    set_={"ciphertext": encoded, "updated_at": stamp},
                )
            )
        job.status, job.error_code, job.records_processed = "ready", None, count
        job.updated_at = stamp
        job.next_attempt_at = (
            stamp
            if source in {"sales", "finance"} and job.cursor is not None
            else stamp + timedelta(hours=6)
        )

    if source == "stock_cover" and getattr(client, "checkpoint", None):
        try:
            client.checkpoint.clear()
        except RedisError:
            logger.warning("ozon_checkpoint_cleanup_unavailable")


@celery_app.task(
    name="perk.ozon.analytics.dispatch", ignore_result=True, soft_time_limit=40, time_limit=50
)
def dispatch():
    engine = build_engine(get_settings())
    try:
        with Session(engine) as db, db.begin():
            pending = []
            for actor in actors(db, "ozon_analytics"):
                jobs = db.scalars(
                    select(OzonAnalyticsSync)
                    .where(
                        OzonAnalyticsSync.requested_by == actor,
                        OzonAnalyticsSync.next_attempt_at <= now(),
                    )
                    .order_by(OzonAnalyticsSync.next_attempt_at)
                    .limit(20)
                    .with_for_update(skip_locked=True)
                ).all()
                for job in jobs:
                    plan(job)
                    job.run_id, job.status, job.error_code = uuid4(), "queued", None
                    job.next_attempt_at = now() + timedelta(minutes=3)
                    pending.append(
                        [
                            str(value)
                            for value in (
                                job.workspace_id,
                                job.store_id,
                                job.source,
                                job.requested_by,
                                job.run_id,
                            )
                        ]
                    )
        for args in pending:
            import_analytics.apply_async(args=args, retry=False)
    except Exception:
        logger.error("ozon_analytics_dispatch_unavailable")
    finally:
        release_engine(engine)


@celery_app.task(
    name="perk.ozon.analytics.import", ignore_result=True, soft_time_limit=540, time_limit=600
)
def import_analytics(workspace_id, store_id, source, actor_id, run_id):
    settings = get_settings()
    engine, vault = build_engine(settings), SecretVault(settings.security_file)
    redis = Redis.from_url(settings.redis_broker_url, socket_timeout=3, socket_connect_timeout=3)
    wid, sid, actor, run = [UUID(value) for value in (workspace_id, store_id, actor_id, run_id)]

    def factory(client_id, api_key):
        from app.integrations.ozon.supplies import SupplyClient
        from app.integrations.ozon.traffic import TrafficClient

        gate = "perk:ozon:read:" + vault.digest("ozon-read", client_id)

        def wait():
            if source == "traffic":
                quota = "perk:ozon:traffic:" + vault.digest("ozon-traffic", client_id)
                if not redis.set(quota, "1", nx=True, ex=61):
                    raise OzonImportError("ozon_rate_limited", max(1, redis.ttl(quota)))
            deadline = time.monotonic() + 20
            while not redis.set(gate, "1", nx=True, px=500):
                if time.monotonic() >= deadline:
                    raise OzonImportError("ozon_rate_limited", 60)
                time.sleep(0.1)

        if source == "traffic":
            return TrafficClient(
                client_id,
                api_key,
                wait=wait,
                checkpoint=StockCoverCheckpoint(
                    redis, vault, wid, sid, client_id, api_key, namespace="traffic"
                ),
            )
        if source == "supplies":

            def supply_wait():
                group = "perk:ozon:supplies:" + vault.digest("ozon-supplies", client_id)
                deadline = time.monotonic() + 20
                while not redis.set(group, "1", nx=True, px=1100):
                    if time.monotonic() >= deadline:
                        raise OzonImportError("ozon_rate_limited", 30)
                    time.sleep(0.1)
                wait()

            return SupplyClient(
                client_id,
                api_key,
                wait=supply_wait,
                checkpoint=StockCoverCheckpoint(
                    redis, vault, wid, sid, client_id, api_key, namespace="supplies"
                ),
            )
        checkpoint = (
            StockCoverCheckpoint(redis, vault, wid, sid, client_id, api_key)
            if source == "stock_cover"
            else None
        )
        if source == "finance":
            return FinanceClient(client_id, api_key, wait=wait)
        return OperationsClient(
            client_id,
            api_key,
            wait=wait,
            checkpoint=checkpoint,
            price_checkpoint=StockCoverCheckpoint(
                redis, vault, wid, sid, client_id, api_key, namespace="order-prices"
            ),
        )

    try:
        execute(engine, vault, wid, sid, source, actor, run, factory)
    except Exception as error:
        code = error.code if isinstance(error, OzonImportError) else "ozon_import_failed"
        delay = error.retry_after if isinstance(error, OzonImportError) else 300
        logger.warning("ozon_analytics_import_failed:%s:%s", code, type(error).__name__)
        with Session(engine) as db, db.begin():
            set_actor(db, actor)
            job = db.get(OzonAnalyticsSync, (wid, sid, source), with_for_update=True)
            if job and job.run_id == run:
                job.status, job.error_code = "error", code
                job.next_attempt_at = now() + timedelta(seconds=delay)
    finally:
        redis.close()
        release_engine(engine)
