"""Slow WB regional reads stay off the first-load path and share seller quotas."""

import json
from datetime import timedelta
from uuid import UUID, uuid4

from redis import Redis
from sqlalchemy import case, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import set_actor
from app.integrations.wildberries.client import inspect_token
from app.integrations.wildberries.data import Source, WBDataClient, WBError
from app.modules.accounts.models import Store, StoreCredential
from app.modules.auth.dependencies import now
from app.modules.auth.models import Membership, User
from app.modules.supplies.destinations.models import (
    SupplyDestinationSnapshot,
    SupplyDestinationSync,
)
from app.modules.supplies.destinations.normalize import wb_regions
from app.modules.sync.models import SyncRun
from app.modules.sync.quota import gate_key
from app.modules.sync.schemas import moscow_today
from app.security.crypto import SecretVault
from app.workers.celery_app import celery_app
from app.workers.database import release_engine
from app.workers.database import worker_engine as build_engine
from app.workers.outbox import actors


def aad(wid, sid, key):
    return f"supply-destination:v1:{wid}:{sid}:{key}"


def authorized(db, wid, sid, actor):
    set_actor(db, actor)
    member, user, store = db.get(Membership, (actor, wid)), db.get(User, actor), db.get(Store, sid)
    if (
        not member
        or member.role not in {"owner", "admin"}
        or not user
        or not user.is_active
        or not user.email_verified_at
    ):
        return None
    if (
        not store
        or store.workspace_id != wid
        or not store.is_active
        or store.marketplace != "wildberries"
        or store.connection_status != "connected"
    ):
        return None
    return store


def execute(engine, redis, vault, settings, wid, sid, key, actor, run_id, client=None):
    identity = (wid, sid, key)
    with Session(engine) as db, db.begin():
        set_actor(db, actor)
        job = db.get(SupplyDestinationSync, identity, with_for_update=True)
        if not job or job.run_id != run_id or job.status != "queued":
            return
        store = authorized(db, wid, sid, actor)
        if not store:
            job.status, job.error_code, job.next_attempt_at = (
                "error",
                "access_revoked",
                now() + timedelta(hours=6),
            )
            return
        credential = db.scalar(
            select(StoreCredential).where(
                StoreCredential.workspace_id == wid, StoreCredential.store_id == sid
            )
        )
        if (
            not credential
            or credential.expires_at <= now()
            or "analytics" not in credential.scopes.split(",")
        ):
            job.status, job.error_code, job.next_attempt_at = (
                "error",
                "wb_scope_missing",
                now() + timedelta(hours=6),
            )
            return
        # Give the existing bulk reports priority whenever their pages are due.
        busy = db.scalar(
            select(SyncRun.id)
            .where(
                SyncRun.workspace_id == wid,
                SyncRun.store_id == sid,
                SyncRun.source.in_(
                    [Source.STOCK_HISTORY, Source.SUPPLY_DEMAND, Source.SUPPLY_DEMAND_FBS]
                ),
                SyncRun.status.in_(["queued", "running"]),
            )
            .limit(1)
        )
        if busy:
            job.status, job.next_attempt_at = "pending", now() + timedelta(seconds=60)
            return
        original = credential.ciphertext
        token = vault.open(original, f"wb:{wid}:{sid}")
        metadata = inspect_token(
            token,
            production=settings.app_env == "production",
            service_id=settings.wb_service_id,
            allow_personal=settings.allows_personal_wb_token(wid),
        )
        if metadata.seller_id != store.external_seller_id:
            raise WBError("wb_token_rejected")
        gate = gate_key(redis, vault, Source.SUPPLY_DEMAND, metadata)
        if not redis.set(gate, "1", nx=True, ex=1800 if metadata.token_type == 1 else 20):
            job.status, job.next_attempt_at = (
                "pending",
                now() + timedelta(seconds=max(1, redis.ttl(gate))),
            )
            return
        start, end = job.date_from, job.date_to
        job.status, job.next_attempt_at = "running", now() + timedelta(minutes=3)
    reader = client or WBDataClient()
    try:
        data = reader.request(
            Source.SUPPLY_DEMAND,
            Source.SUPPLY_DEMAND_FBS,
            token,
            stock_detail=int(key),
            body={
                "nmID": int(key),
                "currentPeriod": {"start": str(start), "end": str(end)},
                "stockType": "wb",
                "includeOffice": True,
                "orderBy": {"field": "avgOrders", "mode": "asc"},
            },
        )
        if reader.cooldown_seconds:
            redis.eval(
                "local t=redis.call('TTL',KEYS[1]); if t<tonumber(ARGV[1]) then "
                "redis.call('SET',KEYS[1],'1','EX',ARGV[1]) end; return 1",
                1,
                gate,
                reader.cooldown_seconds,
            )
        payload = wb_regions(data["data"], start, end)
    except WBError as error:
        if error.retry_after:
            redis.eval(
                "local t=redis.call('TTL',KEYS[1]); if t<tonumber(ARGV[1]) then "
                "redis.call('SET',KEYS[1],'1','EX',ARGV[1]) end; return 1",
                1,
                gate,
                error.retry_after,
            )
        raise
    stamp = now()
    with Session(engine) as db, db.begin():
        store = authorized(db, wid, sid, actor)
        set_actor(db, actor)
        job = db.get(SupplyDestinationSync, identity, with_for_update=True)
        if not store or not job or job.run_id != run_id or job.status != "running":
            return
        credential = db.scalar(
            select(StoreCredential).where(
                StoreCredential.workspace_id == wid, StoreCredential.store_id == sid
            )
        )
        if not credential or credential.ciphertext != original:
            job.status, job.next_attempt_at = "pending", now() + timedelta(minutes=1)
            return
        statement = insert(SupplyDestinationSnapshot).values(
            workspace_id=wid,
            store_id=sid,
            product_key=key,
            ciphertext=vault.seal(json.dumps(payload), aad(wid, sid, key)),
            updated_at=stamp,
        )
        db.execute(
            statement.on_conflict_do_update(
                index_elements=["workspace_id", "store_id", "product_key"],
                set_={"ciphertext": statement.excluded.ciphertext, "updated_at": stamp},
            )
        )
        job.status, job.updated_at, job.error_code = "ready", stamp, None
        job.next_attempt_at = stamp + timedelta(hours=6)


@celery_app.task(name="perk.supply.destinations.dispatch", ignore_result=True)
def dispatch():
    engine = build_engine(get_settings())
    try:
        with Session(engine) as db, db.begin():
            pending = []
            for actor in actors(db, "destinations"):
                rows = db.scalars(
                    select(SupplyDestinationSync)
                    .where(
                        SupplyDestinationSync.requested_by == actor,
                        SupplyDestinationSync.next_attempt_at <= now(),
                    )
                    .order_by(
                        case((SupplyDestinationSync.status == "pending", 0), else_=1),
                        SupplyDestinationSync.next_attempt_at,
                    )
                    .limit(8)
                    .with_for_update(skip_locked=True)
                ).all()
                for job in rows:
                    job.date_to = moscow_today() - timedelta(days=1)
                    job.date_from = job.date_to - timedelta(days=27)
                    job.status, job.run_id = "queued", uuid4()
                    job.next_attempt_at = now() + timedelta(minutes=3)
                    pending.append(
                        [
                            str(v)
                            for v in (
                                job.workspace_id,
                                job.store_id,
                                job.product_key,
                                job.requested_by,
                                job.run_id,
                            )
                        ]
                    )
        for args in pending:
            load.apply_async(args=args, retry=False)
    finally:
        release_engine(engine)


@celery_app.task(
    name="perk.supply.destinations.load", ignore_result=True, soft_time_limit=60, time_limit=90
)
def load(workspace_id, store_id, product_key, actor_id, run_id):
    settings = get_settings()
    engine, vault = build_engine(settings), SecretVault(settings.security_file)
    redis = Redis.from_url(settings.redis_broker_url, socket_timeout=3, socket_connect_timeout=3)
    wid, sid, actor, run = [UUID(v) for v in (workspace_id, store_id, actor_id, run_id)]
    try:
        execute(engine, redis, vault, settings, wid, sid, product_key, actor, run)
    except Exception as error:
        with Session(engine) as db, db.begin():
            set_actor(db, actor)
            job = db.get(SupplyDestinationSync, (wid, sid, product_key), with_for_update=True)
            if job and job.run_id == run:
                job.status = "error"
                job.error_code = error.code if isinstance(error, WBError) else "wb_invalid_response"
                job.next_attempt_at = now() + timedelta(
                    seconds=max(60, error.retry_after or 300) if isinstance(error, WBError) else 300
                )
    finally:
        release_engine(engine)
