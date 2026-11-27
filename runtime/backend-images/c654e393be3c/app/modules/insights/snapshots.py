"""Stale-while-revalidate snapshots: reads never wait for a heavy recalculation.

A request returns the stored snapshot at once. If store data changed since it was computed,
the response is marked stale and a background task recomputes it. A snapshot that never
existed is computed inline exactly once: concurrent first readers wait on a per-key
transaction lock and then reuse the published result.
"""

import json
import logging
from uuid import uuid4

from fastapi import Response
from redis.exceptions import RedisError
from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert

from app.db.session import set_actor
from app.db.tenant import scope
from app.modules.auth.dependencies import now
from app.modules.finance.models import ExternalExpense, FinanceProjection, ProductCost, TaxSetting
from app.modules.insights.models import InsightSnapshot, StoreGoal
from app.modules.inventory.models import InventorySnapshot
from app.modules.sync.models import SyncRun, WBMetricVersion
from app.modules.sync.schemas import moscow_today

logger = logging.getLogger(__name__)
LEASE_SECONDS = 600
RELEASE = (
    "if redis.call('GET', KEYS[1]) == ARGV[1] then return redis.call('DEL', KEYS[1]) end return 0"
)


def params_key(vault, kind, params):
    version = ":labels-v1" if kind == "funnel" else ""
    return vault.digest("insight-params", kind + version + ":" + json.dumps(params, sort_keys=True))


def aad(workspace_id, store_id, kind, key):
    return f"perk-insight:v1:{workspace_id}:{store_id}:{kind}:{key}"


def store_revision(vault, db, workspace_id, store_id):
    """Everything a derived report depends on. Cheap indexed aggregates only.

    Every input table contributes a count and its last modification time, so edits
    in place (same row, new value) change the revision as well as inserts and deletes.
    """
    metric = db.get(WBMetricVersion, (workspace_id, store_id), populate_existing=True)
    projection = db.get(FinanceProjection, (workspace_id, store_id), populate_existing=True)
    parts = [
        moscow_today().isoformat(),
        str(metric.version) if metric else "",
        f"{projection.source_run_id}:{projection.updated_at}" if projection else "",
    ]
    aggregates = (
        (InventorySnapshot, [func.count(), func.max(InventorySnapshot.updated_at)]),
        (ProductCost, [func.count(), func.max(ProductCost.created_at)]),
        (
            ExternalExpense,
            [
                func.count(),
                func.max(ExternalExpense.created_at),
                func.max(ExternalExpense.deleted_at),
            ],
        ),
        (TaxSetting, [func.count(), func.max(TaxSetting.updated_at)]),
        (StoreGoal, [func.count(), func.max(StoreGoal.updated_at)]),
    )
    for model, columns in aggregates:
        row = db.execute(select(*columns).where(*scope(model, workspace_id, store_id))).one()
        parts += map(str, row)
    running = db.execute(
        select(SyncRun.id, SyncRun.pages_processed).where(
            *scope(SyncRun, workspace_id, store_id), SyncRun.status.in_(["queued", "running"])
        )
    ).all()
    parts += sorted(f"{run_id}:{pages}" for run_id, pages in running)
    return vault.digest("insight-revision", "|".join(parts))


def lock_id(vault, workspace_id, store_id, kind, key):
    # 60 bits of a keyed digest: fits PostgreSQL's signed bigint advisory lock key.
    return int(vault.digest("insight-lock", f"{workspace_id}:{store_id}:{kind}:{key}")[:15], 16)


def meta(db, workspace_id, store_id, kind, key):
    """Revision and time only: an unchanged client copy is answered without decryption."""
    return db.execute(
        select(InsightSnapshot.revision, InsightSnapshot.computed_at).where(
            InsightSnapshot.workspace_id == workspace_id,
            InsightSnapshot.store_id == store_id,
            InsightSnapshot.kind == kind,
            InsightSnapshot.params_key == key,
        )
    ).first()


def load(db, vault, workspace_id, store_id, kind, key):
    row = db.get(InsightSnapshot, (workspace_id, store_id, kind, key), populate_existing=True)
    if not row:
        return None, None
    return row, json.loads(vault.open(row.ciphertext, aad(workspace_id, store_id, kind, key)))


def save(db, vault, workspace_id, store_id, kind, key, revision, data):
    """Upsert: a concurrent publication of the same key can never raise IntegrityError."""
    values = {
        "workspace_id": workspace_id,
        "store_id": store_id,
        "kind": kind,
        "params_key": key,
        "revision": revision,
        "computed_at": now(),
        "ciphertext": vault.seal(
            json.dumps(data, separators=(",", ":"), ensure_ascii=False, default=str),
            aad(workspace_id, store_id, kind, key),
        ),
    }
    statement = insert(InsightSnapshot).values(**values)
    db.execute(
        statement.on_conflict_do_update(
            index_elements=["workspace_id", "store_id", "kind", "params_key"],
            set_={
                field: statement.excluded[field]
                for field in ("revision", "computed_at", "ciphertext")
            },
        )
    )
    return values["revision"], values["computed_at"]


def lease_key(vault, workspace_id, store_id, kind, key):
    digest = vault.digest("insight-job", f"{workspace_id}:{store_id}:{kind}:{key}")
    return "perk:insight-job:" + digest


def schedule(redis, vault, workspace_id, store_id, actor_id, kind, params):
    """Deduplicated background refresh. A Redis or broker outage only delays freshness."""
    from app.workers.tasks import compute_insight

    key = params_key(vault, kind, params)
    lease, token = lease_key(vault, workspace_id, store_id, kind, key), str(uuid4())
    try:
        if not redis.set(lease, token, nx=True, ex=LEASE_SECONDS):
            return False
        try:
            compute_insight.apply_async(
                args=[str(workspace_id), str(store_id), str(actor_id), kind, params, token],
                retry=False,
            )
        except Exception:
            redis.eval(RELEASE, 1, lease, token)
            return False
    except RedisError:
        return False
    return True


def release(redis, vault, workspace_id, store_id, kind, params, token):
    key = params_key(vault, kind, params)
    redis.eval(RELEASE, 1, lease_key(vault, workspace_id, store_id, kind, key), token)


def refresh(db, vault, workspace_id, store_id, kind, params, compute):
    """Worker side: recompute only if outdated, and never twice at the same time."""
    key = params_key(vault, kind, params)
    locked = db.scalar(
        text("SELECT pg_try_advisory_xact_lock(:key)"),
        {"key": lock_id(vault, workspace_id, store_id, kind, key)},
    )
    if not locked:
        return False  # A request or another worker is computing this snapshot now.
    revision = store_revision(vault, db, workspace_id, store_id)
    current = meta(db, workspace_id, store_id, kind, key)
    if current and current.revision == revision:
        return False
    save(db, vault, workspace_id, store_id, kind, key, revision, compute(db))
    return True


def etag_for(revision, computed_at, stale):
    return f'"{revision[:16]}-{int(computed_at.timestamp())}-{int(stale)}"'


def serve(
    request, response, db, identity, workspace_id, store_id, kind, params, compute, conditional=True
):
    """Return (data, freshness), or (304 response, None) when the client copy is current.

    The caller's transaction is committed only on a cold start. The RLS actor is
    transaction-local, so it is set again before any further query in the handler.
    """
    state = request.app.state
    vault = state.vault
    key = params_key(vault, kind, params)
    revision = store_revision(vault, db, workspace_id, store_id)
    current = meta(db, workspace_id, store_id, kind, key)
    data = None
    if current is None:
        db.execute(
            text("SELECT pg_advisory_xact_lock(:key)"),
            {"key": lock_id(vault, workspace_id, store_id, kind, key)},
        )
        current = meta(db, workspace_id, store_id, kind, key)  # Published while we waited?
        if current is None:
            data = compute(db)
            current_revision, computed_at = save(
                db, vault, workspace_id, store_id, kind, key, revision, data
            )
            data = json.loads(json.dumps(data, default=str))
        db.commit()
        set_actor(db, identity.user.id)
        if data is not None:
            response.headers["ETag"] = etag_for(current_revision, computed_at, False)
            return data, {"computed_at": computed_at, "stale": False}
    stale = current.revision != revision
    if stale:
        schedule(state.redis, vault, workspace_id, store_id, identity.user.id, kind, params)
    etag = etag_for(current.revision, current.computed_at, stale)
    if conditional and request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag}), None
    _, data = load(db, vault, workspace_id, store_id, kind, key)
    response.headers["ETag"] = etag
    return data, {"computed_at": current.computed_at, "stale": stale}
