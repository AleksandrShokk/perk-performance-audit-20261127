"""Seller-wide WB quotas, separated by token type; no secrets in Redis keys."""

from datetime import timedelta

from sqlalchemy import select

from app.integrations.wildberries.data import SCOPES, Source
from app.modules.auth.dependencies import now
from app.modules.sync.models import SyncRun, SyncSchedule


def addresses(vault, source, metadata):
    # Both historical reads share one WB endpoint and its seller-wide limit.
    if source in {Source.SUPPLY_DEMAND, Source.SUPPLY_DEMAND_FBS}:
        source = Source.STOCK_HISTORY
    legacy = "perk:wb-gate:" + vault.digest(source, metadata.seller_id)
    current = "perk:wb-gate:v2:" + vault.digest(
        "wb-quota", f"{source}:{metadata.token_type}:{metadata.seller_id}"
    )
    return current, legacy, legacy + ":type"


def gate_key(redis, vault, source, metadata):
    current, legacy, origin = addresses(vault, source, metadata)
    # Unknown legacy quotas are inherited conservatively. A confirmed type change
    # preserves the old type's quota without imposing it on an independent type.
    redis.eval(
        "local t=redis.call('PTTL',KEYS[2]); "
        "if t>0 then local owner=redis.call('GET',KEYS[3]); "
        "if not owner then redis.call('SET',KEYS[3],ARGV[1],'PX',t,'NX'); "
        "owner=redis.call('GET',KEYS[3]); end; "
        "if owner==ARGV[1] and redis.call('PTTL',KEYS[1])<t then "
        "redis.call('SET',KEYS[1],'1','PX',t); end; end; return 1",
        3,
        current,
        legacy,
        origin,
        str(metadata.token_type),
    )
    return current


def preserve_legacy(redis, vault, metadata):
    """Record the known previous type before a credential transition."""
    for source in Source:
        _, legacy, origin = addresses(vault, source, metadata)
        redis.eval(
            "local t=redis.call('PTTL',KEYS[1]); if t>0 then "
            "redis.call('SET',KEYS[2],ARGV[1],'PX',t,'NX'); end; return 1",
            2,
            legacy,
            origin,
            str(metadata.token_type),
        )
        gate_key(redis, vault, source, metadata)


def credential_changed(db, redis, vault, store, previous, current, *, actor_id=None):
    from app.modules.sync import funnel_summary

    if previous and previous.token_type != current.token_type:
        preserve_legacy(redis, vault, previous)
        runs = db.scalars(
            select(SyncRun)
            .where(
                SyncRun.workspace_id == store.workspace_id,
                SyncRun.store_id == store.id,
                SyncRun.status.in_(["queued", "running"]),
                SyncRun.error_code == "wb_rate_limited",
            )
            .with_for_update(skip_locked=True)
        ).all()
        for run in runs:
            source = Source.FUNNEL if run.source == funnel_summary.SOURCE else Source(run.source)
            key = gate_key(redis, vault, source, current)
            run.next_attempt_at = now() + timedelta(seconds=max(0, redis.ttl(key)))
            run.task_id, run.error_code, run.attempts = None, None, 0
    recoverable = {
        "wb_token_rejected",
        "wb_token_policy_rejected",
        "wb_token_type_unsupported",
        "wb_scope_missing",
        "credential_unavailable",
        "store_not_connected",
        "wb_access_denied",
    }
    for plan in db.scalars(
        select(SyncSchedule)
        .where(
            SyncSchedule.workspace_id == store.workspace_id,
            SyncSchedule.store_id == store.id,
        )
        .with_for_update(skip_locked=True)
    ):
        # A manually disabled import stays disabled. Credential failures can recover.
        if not plan.enabled and plan.error_code not in recoverable:
            continue
        source = Source(plan.source)
        error = None
        if SCOPES[source] not in current.scopes:
            error = "wb_scope_missing"
        elif source == Source.STOCKS and current.token_type not in {3, 4}:
            error = "wb_token_type_unsupported"
        plan.enabled, plan.error_code = error is None, error
        if not error:
            plan.next_attempt_at = plan.next_refresh_at = now()
            if actor_id is not None:
                plan.requested_by = actor_id
