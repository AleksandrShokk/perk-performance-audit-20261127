"""Independent jobs: traffic quota or supply failure cannot block sales/finance snapshots."""

import json
from datetime import timedelta

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.modules.accounts.ozon_connection import credential_row, open_credentials
from app.modules.auth.dependencies import now
from app.modules.catalog.ozon_jobs import authorized
from app.modules.insights.extra_models import MarketplaceSupplySnapshot, MarketplaceTrafficDay
from app.modules.insights.marketplace_models import OzonAnalyticsSync
from app.modules.sync.schemas import moscow_today


def aad(wid, sid, source, day="snapshot"):
    return f"perk-ozon-extra:v1:{wid}:{sid}:{source}:{day}"


def execute(engine, vault, wid, sid, source, actor, run_id, client_factory):
    key = (wid, sid, source)
    with Session(engine) as db, db.begin():
        store = authorized(db, wid, sid, actor)
        if not store:
            from app.workers.outbox import reject_ozon

            reject_ozon(db, wid, sid, source, actor, run_id)
            return
        job = db.get(OzonAnalyticsSync, key, with_for_update=True)
        if not job or job.run_id != run_id or job.status != "queued":
            return
        credential = credential_row(db, store)
        original = credential.ciphertext
        secret = open_credentials(vault, store, credential)
        start, end, mode = job.date_from, job.date_to, job.mode
        prior = db.get(MarketplaceSupplySnapshot, (wid, sid)) if source == "supplies" else None
        prior = json.loads(vault.open(prior.ciphertext, aad(wid, sid, source))) if prior else None
        job.status = "running"
        job.next_attempt_at = now() + timedelta(minutes=12)
    client = client_factory(secret["client_id"], secret["api_key"])
    payload = (
        client.days(start, end) if source == "traffic" else client.snapshot(moscow_today(), prior)
    )
    stamp = now()
    with Session(engine) as db, db.begin():
        store = authorized(db, wid, sid, actor)
        job = db.get(OzonAnalyticsSync, key, with_for_update=True)
        if (
            not store
            or not job
            or job.run_id != run_id
            or job.status != "running"
            or credential_row(db, store).ciphertext != original
        ):
            return
        if source == "traffic":
            for day, values in payload.items():
                statement = insert(MarketplaceTrafficDay).values(
                    workspace_id=wid,
                    store_id=sid,
                    day=day,
                    ciphertext=vault.seal(json.dumps(values), aad(wid, sid, source, day)),
                    updated_at=stamp,
                )
                db.execute(
                    statement.on_conflict_do_update(
                        index_elements=["workspace_id", "store_id", "day"],
                        set_={"ciphertext": statement.excluded.ciphertext, "updated_at": stamp},
                    )
                )
            if mode == "history":
                job.cursor = start - timedelta(days=1) if start > job.history_from else None
            count = len(payload)
        else:
            statement = insert(MarketplaceSupplySnapshot).values(
                workspace_id=wid,
                store_id=sid,
                ciphertext=vault.seal(json.dumps(payload), aad(wid, sid, source)),
                updated_at=stamp,
            )
            db.execute(
                statement.on_conflict_do_update(
                    index_elements=["workspace_id", "store_id"],
                    set_={"ciphertext": statement.excluded.ciphertext, "updated_at": stamp},
                )
            )
            job.cursor = None
            count = len(payload["items"])
        job.status = "ready"
        job.error_code = None
        job.updated_at = stamp
        job.records_processed = count
        job.next_attempt_at = (
            stamp + timedelta(seconds=61)
            if source == "traffic" and job.cursor is not None
            else stamp + timedelta(hours=1 if source == "supplies" else 6)
        )

    if source in {"supplies", "traffic"} and getattr(client, "checkpoint", None):
        from redis.exceptions import RedisError

        try:
            client.checkpoint.clear()
        except RedisError:
            pass
