"""Durable Ozon outbox. Only complete snapshots replace published seller data."""

import json
import logging
import time
from datetime import timedelta
from uuid import UUID, uuid4

from redis import Redis
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import set_actor
from app.integrations.ozon.catalog import normalize
from app.integrations.ozon.catalog_client import CatalogClient, ImportError
from app.modules.accounts.models import Store
from app.modules.accounts.ozon_connection import credential_row, open_credentials
from app.modules.auth.dependencies import now
from app.modules.auth.models import Membership, User
from app.modules.catalog.marketplace_models import MarketplaceCatalogSnapshot, OzonCatalogSync
from app.security.crypto import SecretVault
from app.workers.celery_app import celery_app
from app.workers.database import release_engine
from app.workers.database import worker_engine as build_engine
from app.workers.outbox import actors

logger = logging.getLogger(__name__)


def aad(workspace_id, store_id):
    return f"perk-marketplace-catalog:v1:{workspace_id}:{store_id}"


def configure(db, store, actor):
    statement = insert(OzonCatalogSync).values(
        workspace_id=store.workspace_id,
        store_id=store.id,
        requested_by=actor,
        status="pending",
        next_attempt_at=now(),
        records_processed=0,
    )
    db.execute(
        statement.on_conflict_do_update(
            index_elements=["workspace_id", "store_id"],
            set_={
                "requested_by": actor,
                "status": "pending",
                "run_id": None,
                "next_attempt_at": now(),
                "error_code": None,
            },
        )
    )


def authorized(db, wid, sid, actor):
    set_actor(db, actor)
    member = db.get(Membership, (actor, wid))
    user = db.get(User, actor)
    store = db.get(Store, sid)
    if (
        not member
        or member.role not in {"owner", "admin"}
        or not user
        or not user.is_active
        or not user.email_verified_at
        or not store
        or store.workspace_id != wid
        or not store.is_active
        or store.marketplace != "ozon"
        or store.connection_status != "connected"
    ):
        return None
    return store


def execute(engine, vault, wid, sid, actor, run_id, client_factory=CatalogClient):
    """Rechecked on claim and publication; stale workers cannot overwrite a new key/run."""
    key = (wid, sid)
    with Session(engine) as db, db.begin():
        store = authorized(db, wid, sid, actor)
        if not store:
            from app.workers.outbox import reject_ozon

            reject_ozon(db, wid, sid, "catalog", actor, run_id)
            return
        job = db.get(OzonCatalogSync, key, with_for_update=True)
        if not job or job.run_id != run_id or job.status != "queued":
            return
        row = credential_row(db, store)
        original = row.ciphertext
        secret = open_credentials(vault, store, row)
        job.status, job.records_processed = "running", 0
        job.next_attempt_at = now() + timedelta(minutes=12)

    def progress(count):
        with Session(engine) as db, db.begin():
            set_actor(db, actor)
            job = db.get(OzonCatalogSync, key, with_for_update=True)
            if not job or job.run_id != run_id or job.status != "running":
                raise ImportError("import_replaced", 30)
            job.records_processed = count

    records = client_factory(secret["client_id"], secret["api_key"]).fetch(normalize, progress)
    ciphertext = vault.seal(json.dumps(records, ensure_ascii=False), aad(wid, sid))
    with Session(engine) as db, db.begin():
        store = authorized(db, wid, sid, actor)
        if not store:
            raise ImportError("access_revoked", 21600)
        db.refresh(store, with_for_update=True)
        current = credential_row(db, store)
        job = db.get(OzonCatalogSync, key, with_for_update=True)
        if not job or job.run_id != run_id or job.status != "running":
            return
        if (
            current.ciphertext != original
            or not store.is_active
            or store.connection_status != "connected"
        ):
            raise ImportError("credential_changed", 30)
        stamp = now()
        statement = insert(MarketplaceCatalogSnapshot).values(
            workspace_id=wid,
            store_id=sid,
            ciphertext=ciphertext,
            updated_at=stamp,
        )
        db.execute(
            statement.on_conflict_do_update(
                index_elements=["workspace_id", "store_id"],
                set_={"ciphertext": ciphertext, "updated_at": stamp},
            )
        )
        job.status, job.error_code = "ready", None
        job.updated_at, job.records_processed = stamp, len(records)
        job.next_attempt_at = stamp + timedelta(hours=1)


@celery_app.task(
    name="perk.ozon.catalog.dispatch", ignore_result=True, soft_time_limit=40, time_limit=50
)
def dispatch():
    engine = build_engine(get_settings())
    try:
        with Session(engine) as db, db.begin():
            pending = []
            for actor in actors(db, "ozon_catalog"):
                jobs = db.scalars(
                    select(OzonCatalogSync)
                    .where(
                        OzonCatalogSync.requested_by == actor,
                        OzonCatalogSync.next_attempt_at <= now(),
                    )
                    .order_by(OzonCatalogSync.next_attempt_at)
                    .limit(20)
                    .with_for_update(skip_locked=True)
                ).all()
                for job in jobs:
                    job.run_id, job.status = uuid4(), "queued"
                    job.error_code = None
                    job.next_attempt_at = now() + timedelta(minutes=3)
                    pending.append(
                        [
                            str(value)
                            for value in (
                                job.workspace_id,
                                job.store_id,
                                job.requested_by,
                                job.run_id,
                            )
                        ]
                    )
        for args in pending:
            # Failed broker delivery stays durable and is requeued after the lease expires.
            import_catalog.apply_async(args=args, retry=False)
    except Exception:
        logger.error("ozon_catalog_dispatch_unavailable")
    finally:
        release_engine(engine)


@celery_app.task(
    name="perk.ozon.catalog.import", ignore_result=True, soft_time_limit=540, time_limit=600
)
def import_catalog(workspace_id, store_id, actor_id, run_id):
    settings = get_settings()
    engine, vault = build_engine(settings), SecretVault(settings.security_file)
    redis = Redis.from_url(settings.redis_broker_url, socket_timeout=3, socket_connect_timeout=3)
    wid, sid, actor, run = [UUID(value) for value in (workspace_id, store_id, actor_id, run_id)]

    def client_factory(client_id, api_key):
        # Same Seller account across workspaces shares a request gate, no key in Redis.
        gate = "perk:ozon:read:" + vault.digest("ozon-read", client_id)

        def wait():
            deadline = time.monotonic() + 20
            while not redis.set(gate, "1", nx=True, px=350):
                if time.monotonic() >= deadline:
                    raise ImportError("ozon_rate_limited", 30)
                time.sleep(0.1)

        return CatalogClient(client_id, api_key, wait=wait)

    try:
        execute(engine, vault, wid, sid, actor, run, client_factory)
    except Exception as error:
        code = error.code if isinstance(error, ImportError) else "ozon_import_failed"
        delay = error.retry_after if isinstance(error, ImportError) else 300
        logger.warning("ozon_catalog_import_failed:%s", code)
        with Session(engine) as db, db.begin():
            set_actor(db, actor)
            job = db.get(OzonCatalogSync, (wid, sid), with_for_update=True)
            if job and job.run_id == run:
                job.status, job.error_code = "error", code
                job.next_attempt_at = now() + timedelta(seconds=delay)
    finally:
        redis.close()
        release_engine(engine)
