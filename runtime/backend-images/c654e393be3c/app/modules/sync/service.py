import json
import logging
from datetime import timedelta
from uuid import UUID

from cryptography.exceptions import InvalidTag
from fastapi import HTTPException
from redis.exceptions import RedisError
from sqlalchemy import delete, func, literal, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.db.session import set_actor
from app.integrations.wildberries.client import inspect_token
from app.integrations.wildberries.data import (
    INTERVALS,
    SCOPES,
    Source,
    WBDataClient,
    WBError,
)
from app.modules.accounts.models import Store, StoreCredential
from app.modules.audit.service import audit
from app.modules.auth.dependencies import now
from app.modules.auth.models import Membership, User
from app.modules.sync import funnel_summary, pending_page
from app.modules.sync.analytics import discard_preview, stage_metrics, update_metrics
from app.modules.sync.models import SyncRun, WBRecord, WBStagedRecord
from app.modules.sync.normalize import normalize
from app.modules.sync.planner import completed
from app.modules.sync.quota import gate_key

logger = logging.getLogger(__name__)

MAX_RECORDS = 1000000
MAX_PAGES = 5000
MAX_ATTEMPTS = 8
PUBLISH_BATCH_SIZE = 1000


def context(workspace_id, store_id, source, key):
    return f"wb-data:v1:{workspace_id}:{store_id}:{source}:{key}"


def same_store(model, run):
    return (model.workspace_id == run.workspace_id, model.store_id == run.store_id)


def publish(db: Session, run: SyncRun, vault):
    """One transaction: incomplete downloads never replace the published dataset."""
    store = db.scalar(
        select(Store)
        .where(Store.id == run.store_id, Store.workspace_id == run.workspace_id)
        .with_for_update(key_share=True)
        .execution_options(populate_existing=True)
    )
    if not store or not store.is_active or store.connection_status != "connected":
        raise WBError("store_not_connected")
    if run.source == funnel_summary.SOURCE:
        funnel_summary.publish(db, vault, run)
        run.status, run.finished_at, run.error_code = "succeeded", now(), None
        return
    update_metrics(db, vault, run)
    stage = (
        select(WBStagedRecord)
        .where(*same_store(WBStagedRecord, run), WBStagedRecord.run_id == run.id)
        .subquery()
    )
    if run.source in {
        Source.CATALOG,
        Source.STOCKS,
        Source.BALANCE,
        Source.PRICES,
        Source.FBS,
        Source.STOCK_HISTORY,
        Source.SUPPLY_DEMAND,
        Source.SUPPLY_DEMAND_FBS,
        Source.SUPPLIES,
    }:
        db.execute(
            delete(WBRecord).where(*same_store(WBRecord, run), WBRecord.source == run.source)
        )
    run.records_processed = db.scalar(select(func.count()).select_from(stage))
    last_key = ""
    # Keep each SQL statement below the runtime timeout even for a million-row
    # report. All batches still commit together; no partial publication is visible.
    while True:
        keys = db.scalars(
            select(stage.c.record_key)
            .where(stage.c.record_key > last_key)
            .order_by(stage.c.record_key)
            .limit(PUBLISH_BATCH_SIZE)
        ).all()
        if not keys:
            break
        statement = insert(WBRecord).from_select(
            [
                "workspace_id",
                "store_id",
                "source",
                "record_key",
                "ciphertext",
                "updated_at",
            ],
            select(
                stage.c.workspace_id,
                stage.c.store_id,
                literal(run.source),
                stage.c.record_key,
                stage.c.ciphertext,
                literal(now()),
            ).where(stage.c.record_key.between(keys[0], keys[-1])),
        )
        db.execute(
            statement.on_conflict_do_update(
                index_elements=["workspace_id", "store_id", "source", "record_key"],
                set_={
                    "ciphertext": statement.excluded.ciphertext,
                    "updated_at": statement.excluded.updated_at,
                },
            )
        )
        db.execute(
            delete(WBStagedRecord).where(
                *same_store(WBStagedRecord, run),
                WBStagedRecord.run_id == run.id,
                WBStagedRecord.record_key.in_(keys),
            )
        )
        last_key = keys[-1]
    run.status, run.finished_at, run.error_code = "succeeded", now(), None
    if run.source == Source.FBS:
        from app.modules.inventory.channel_history import record_stock

        record_stock(db, vault, run)
    discard_preview(db, run)
    completed(db, run, True)
    audit(
        db,
        "sync.completed",
        workspace_id=run.workspace_id,
        user_id=run.requested_by,
        target_id=run.id,
    )


def defer_error(db: Session, run: SyncRun, error: WBError):
    run.attempts += 1
    run.error_code = error.code
    run.task_id = None
    if error.retryable and run.attempts < MAX_ATTEMPTS:
        seconds = max(error.retry_after, min(3600, 60 * 2 ** (run.attempts - 1)))
        run.next_attempt_at = now() + timedelta(seconds=seconds)
    else:
        run.status, run.finished_at = "failed", now()
        discard_preview(db, run)
        completed(db, run, False)
        db.execute(
            delete(WBStagedRecord).where(
                *same_store(WBStagedRecord, run), WBStagedRecord.run_id == run.id
            )
        )
        audit(
            db,
            "sync.failed",
            workspace_id=run.workspace_id,
            user_id=run.requested_by,
            target_id=run.id,
            success=False,
        )


def run_page(engine, redis, vault, settings, run_id: UUID, task_id: str, client=None):
    """A task contains only identifiers. Credentials are read afresh for each page."""
    with Session(engine, expire_on_commit=False) as db:
        try:
            result = _run_page(db, redis, vault, settings, run_id, task_id, client)
            db.commit()
            # Remove only after commit: a rolled-back publication must keep its page.
            for key in db.info.pop("wb_pending_pages", []):
                try:
                    redis.delete(key)
                except RedisError:
                    pass  # Bounded TTL remains the fallback cleanup.
            return result
        except Exception:
            db.rollback()
            raise


def _run_page(db, redis, vault, settings, run_id, task_id, client):
    from app.workers.outbox import bind_sync

    if not bind_sync(db, run_id, task_id):
        return
    if db.scalar(text("SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname=current_user")):
        raise RuntimeError("unsafe_worker_database_role")
    run = db.scalar(
        select(SyncRun)
        .where(
            SyncRun.id == run_id,
            SyncRun.task_id == task_id,
            SyncRun.status.in_(["queued", "running"]),
        )
        .with_for_update()
    )
    if run is None:
        return
    set_actor(db, run.requested_by)
    run.started_at = run.started_at or now()
    run.status = "running"
    gate = None

    def fail(error):
        nonlocal run
        from app.workers.outbox import bind_sync

        with db.no_autoflush:
            if not bind_sync(db, run_id, task_id):
                return
            current = db.scalar(
                select(SyncRun)
                .where(
                    SyncRun.id == run_id,
                    SyncRun.task_id == task_id,
                    SyncRun.status.in_(["queued", "running"]),
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        if current is not None:
            run = current
            defer_error(db, run, error)

    try:
        owner = db.scalar(
            select(User.id)
            .join(Membership, Membership.user_id == User.id)
            .where(
                Membership.workspace_id == run.workspace_id,
                Membership.role.in_(["owner", "admin"]),
                User.id == run.requested_by,
                User.is_active.is_(True),
                User.email_verified_at.is_not(None),
            )
        )
        if not owner:
            raise WBError("sync_permission_revoked")
        store = db.scalar(
            select(Store).where(Store.id == run.store_id, Store.workspace_id == run.workspace_id)
        )
        credential = db.scalar(select(StoreCredential).where(*same_store(StoreCredential, run)))
        if (
            not store
            or not store.is_active
            or store.connection_status != "connected"
            or not credential
            or credential.expires_at <= now()
        ):
            raise WBError("store_not_connected")
        summary = run.source == funnel_summary.SOURCE
        source = Source.FUNNEL if summary else Source(run.source)
        if SCOPES[source] not in credential.scopes.split(","):
            raise WBError("wb_scope_missing")
        token = vault.open(credential.ciphertext, f"wb:{run.workspace_id}:{run.store_id}")
        metadata = inspect_token(
            token,
            production=settings.app_env == "production",
            service_id=settings.wb_service_id,
            allow_personal=settings.allows_personal_wb_token(run.workspace_id),
        )
        if metadata.seller_id != store.external_seller_id:
            raise WBError("wb_seller_mismatch")
        if source == Source.STOCKS and metadata.token_type not in {3, 4}:
            raise WBError("wb_token_type_unsupported")
        gate = gate_key(redis, vault, source, metadata)
        interval = INTERVALS[source]
        if (
            source
            in {
                Source.STOCK_HISTORY,
                Source.SUPPLY_DEMAND,
                Source.SUPPLY_DEMAND_FBS,
                Source.SUPPLIES,
            }
            and metadata.token_type == 1
        ):
            interval = 1800
        if source == Source.PRICES and metadata.token_type == 1:
            interval = 900
        if source == Source.BALANCE and metadata.token_type == 1:
            interval = 86400
        pending_key = pending_page.address(vault, run, credential.ciphertext)
        cached = pending_page.load(redis, vault, pending_key)
        if cached is None and not redis.set(gate, "1", nx=True, ex=interval):
            run.next_attempt_at = now() + timedelta(seconds=max(1, redis.ttl(gate)))
            run.task_id = None
            return
        transport = client or WBDataClient()
        cursor = run.cursor
        if source == Source.FBS and "warehouses" in cursor:
            from hashlib import sha256

            from app.modules.inventory.channel_history import catalog_sizes

            sizes = catalog_sizes(db, vault, run)
            version = sha256(json.dumps(sizes, sort_keys=True).encode()).hexdigest()
            if cursor.get("catalog_version", version) != version:
                raise WBError("wb_catalog_changed")
            cursor = {**cursor, "_sizes": sizes, "catalog_version": version}
        original_cursor = dict(run.cursor)
        original_credential = credential.ciphertext
        run.next_attempt_at = now() + timedelta(minutes=12 if source == Source.FINANCE else 3)
        db.commit()
        page = cached or transport.page(source, token, cursor, run.date_from, run.date_to)
        set_actor(db, run.requested_by)
        current = db.scalar(
            select(SyncRun)
            .where(
                SyncRun.id == run_id,
                SyncRun.task_id == task_id,
                SyncRun.status == "running",
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if current is None or current.cursor != original_cursor:
            return
        credential = db.scalar(select(StoreCredential).where(*same_store(StoreCredential, run)))
        owner = db.scalar(
            select(Membership.user_id)
            .join(User, User.id == Membership.user_id)
            .where(
                Membership.user_id == run.requested_by,
                Membership.workspace_id == run.workspace_id,
                Membership.role.in_(["owner", "admin"]),
                User.is_active.is_(True),
            )
        )
        if not owner:
            raise WBError("sync_permission_revoked")
        if not credential or credential.ciphertext != original_credential:
            raise WBError("credential_changed")
        if cached is None and page.cooldown_seconds:
            redis.eval(
                "local t=redis.call('TTL',KEYS[1]); if t < tonumber(ARGV[1]) then "
                "redis.call('SET',KEYS[1],'1','EX',ARGV[1]) end; return 1",
                1,
                gate,
                page.cooldown_seconds,
            )
        # Normalize the WHOLE page before writing any part of it.
        if cached is not None:
            records = cached.records
        else:
            records = {}
            for index, row in enumerate(page.rows):
                try:
                    key, value = (
                        funnel_summary.normalize_row(row) if summary else normalize(source, row)
                    )
                    records[key] = value
                except WBError, ValueError, KeyError, TypeError, ArithmeticError:
                    from app.modules.sync.issues import retain

                    identifier = (
                        row.get(
                            "rrd_id",
                            row.get(
                                "nmId", row.get("nm_id", f"page-{run.pages_processed}-row-{index}")
                            ),
                        )
                        if isinstance(row, dict)
                        else f"page-{run.pages_processed}-row-{index}"
                    )
                    retain(
                        db,
                        vault,
                        run.workspace_id,
                        run.store_id,
                        str(source),
                        identifier,
                        "wb_invalid_record",
                    )
                    # Financial completeness cannot be inferred after dropping a provider row.
                    # Retain the last successful report, and expose a scoped diagnostic instead.
                    raise WBError("wb_invalid_record") from None
        # Serialize publication, preview aggregates and plan changes after the HTTP call.
        store = db.scalar(
            select(Store)
            .where(Store.id == run.store_id, Store.workspace_id == run.workspace_id)
            .with_for_update(skip_locked=True, key_share=True)
            .execution_options(populate_existing=True)
        )
        if store is None:
            # Preserve the received page instead of spending another provider request.
            # Cached retries only wait for publication; they do not reset the WB cooldown.
            saved = cached is not None or pending_page.save(
                redis, vault, pending_key, records, page
            )
            if saved and cached is None:
                logger.info("wb_page_preserved_while_store_busy")
            seconds = 2 if saved else max(2, redis.ttl(gate))
            run.next_attempt_at = now() + timedelta(seconds=seconds)
            run.task_id, run.error_code = None, "sync_store_busy"
            return
        if not store.is_active or store.connection_status != "connected":
            raise WBError("store_not_connected")
        existing = db.scalar(
            select(func.count())
            .select_from(WBStagedRecord)
            .where(*same_store(WBStagedRecord, run), WBStagedRecord.run_id == run.id)
        )
        keys = list(records)
        duplicates = 0
        for offset in range(0, len(keys), 1000):
            duplicates += db.scalar(
                select(func.count())
                .select_from(WBStagedRecord)
                .where(
                    *same_store(WBStagedRecord, run),
                    WBStagedRecord.run_id == run.id,
                    WBStagedRecord.record_key.in_(keys[offset : offset + 1000]),
                )
            )
        if (
            source in {Source.STOCK_HISTORY, Source.SUPPLY_DEMAND, Source.SUPPLY_DEMAND_FBS}
            and duplicates
        ):
            raise WBError("wb_pagination_stalled")
        if existing + len(records) - duplicates > MAX_RECORDS or run.pages_processed >= MAX_PAGES:
            raise WBError("sync_size_limit")
        values = [
            {
                "workspace_id": run.workspace_id,
                "store_id": run.store_id,
                "run_id": run.id,
                "record_key": key,
                "ciphertext": vault.seal(
                    json.dumps(data, ensure_ascii=False, separators=(",", ":")),
                    context(run.workspace_id, run.store_id, run.source, key),
                ),
            }
            for key, data in records.items()
        ]
        if not page.complete:
            stage_metrics(db, vault, run, values)
        for offset in range(0, len(values), 250):
            stmt = insert(WBStagedRecord).values(values[offset : offset + 250])
            db.execute(
                stmt.on_conflict_do_update(
                    index_elements=["run_id", "record_key"],
                    set_={"ciphertext": stmt.excluded.ciphertext},
                )
            )
        run.cursor = page.cursor
        run.pages_processed += 1
        run.records_processed = db.scalar(
            select(func.count())
            .select_from(WBStagedRecord)
            .where(*same_store(WBStagedRecord, run), WBStagedRecord.run_id == run.id)
        )
        run.attempts, run.error_code, run.task_id = 0, None, None
        # The quota starts when the request is sent, not after database processing.
        run.next_attempt_at = now() + timedelta(seconds=max(0, redis.ttl(gate)))
        if page.complete:
            publish(db, run, vault)
        if cached is not None:
            db.info.setdefault("wb_pending_pages", []).append(pending_key)
            logger.info("wb_pending_page_applied_without_refetch")
    except WBError as error:
        set_actor(db, run.requested_by)
        if gate and error.retry_after:
            # Extend the seller-wide cooldown atomically; never shorten another worker's limit.
            redis.eval(
                "local t=redis.call('TTL',KEYS[1]); if t < tonumber(ARGV[1]) then "
                "redis.call('SET',KEYS[1],'1','EX',ARGV[1]) end; return 1",
                1,
                gate,
                error.retry_after,
            )
        fail(error)
    except HTTPException:
        fail(WBError("wb_token_policy_rejected"))
    except InvalidTag:
        fail(WBError("credential_unavailable"))
    except ValueError, KeyError, TypeError, ArithmeticError:
        fail(WBError("wb_invalid_record"))
    except RedisError:
        fail(WBError("sync_rate_limiter_unavailable", retryable=True))
    return (
        (str(run.workspace_id), str(run.store_id), str(run.requested_by))
        if run.status == "succeeded" and not summary
        else None
    )
