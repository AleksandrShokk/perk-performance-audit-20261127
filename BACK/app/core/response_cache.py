"""Shared cache of finished read responses: one recalculation serves every API process.

Used only for reads whose inputs are completely described by the key. The caller passes
a fingerprint of everything the response depends on (see ``wb_fingerprint``), so new or
changed data always produces a different key and the lifetime only decides how long an
unused answer survives. Keys are keyed digests and bodies are sealed with the vault, like
every other report cached in Redis. A Redis outage only means a recalculation.
"""

import json
from collections.abc import Callable
from datetime import timedelta

from cryptography.exceptions import InvalidTag
from fastapi import Response
from pydantic import BaseModel
from redis.exceptions import RedisError
from sqlalchemy import func, select

from app.db.tenant import scope
from app.modules.auth.dependencies import now
from app.modules.sync.schemas import moscow_today

# Bump when the shape or the calculation of a cached response changes.
VERSION = 1
CACHE_SECONDS = 12 * 3600
# Free-text searches produce many distinct keys; keep them briefly.
SEARCH_CACHE_SECONDS = 600
STALE_AFTER = timedelta(days=2)


def wb_fingerprint(db, workspace_id, stores, sources):
    """Every input of the WB catalog/stock read models, or None when not cacheable.

    Snapshot sources (catalog, stocks, prices, FBS, stock history) are replaced as a whole
    by the publication of a successful sync run, so the latest successful run identifies
    their records. Product costs are append-only (count + newest row). Queued/running
    markers change "is_loading"; the 2-day staleness flag is part of the key as well.
    """
    from app.modules.finance.models import ProductCost
    from app.modules.sync.read import source_states

    if not stores or any(store.marketplace != "wildberries" for store in stores):
        return None
    parts = [moscow_today().isoformat()]
    current = now()
    for store in sorted(stores, key=lambda row: str(row.id)):
        parts.append([str(store.id), store.name])
        states = source_states(db, workspace_id, store.id, sources)
        for source in sorted(states, key=str):
            state = states[source]
            run = state.success
            parts.append(
                [
                    str(source),
                    state.loading,
                    str(run.id) if run else None,
                    str(run.finished_at) if run else None,
                    bool(run and run.finished_at and current - run.finished_at > STALE_AFTER),
                    str(run.date_from) if run else None,
                    str(run.date_to) if run else None,
                ]
            )
        costs = db.execute(
            select(func.count(), func.max(ProductCost.created_at)).where(
                *scope(ProductCost, workspace_id, store.id)
            )
        ).one()
        parts.append([str(value) for value in costs])
    return parts


def respond(
    request,
    namespace: str,
    fingerprint,
    params: dict,
    build: Callable[[], BaseModel],
    seconds: int | None = None,
):
    """Return the cached JSON body for (fingerprint, params) or build, store and return it.

    Without a fingerprint the response is built normally and nothing is stored.
    """
    if fingerprint is None:
        return build()
    seconds = seconds or CACHE_SECONDS
    state = request.app.state
    vault, redis = state.vault, state.redis
    material = json.dumps(
        [namespace, VERSION, fingerprint, params],
        default=str,
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = vault.digest("response-cache", material)
    key, aad = f"perk:response:{namespace}:{digest}", f"perk-response:v{VERSION}:{digest}"
    try:
        sealed = redis.get(key)
        if isinstance(sealed, (str, bytes)):
            body = vault.open(sealed.decode() if isinstance(sealed, bytes) else sealed, aad)
            redis.expire(key, seconds)
            return Response(body, media_type="application/json")
    except RedisError, InvalidTag, ValueError:
        pass
    body = build().model_dump_json()
    try:
        redis.set(key, vault.seal(body, aad), ex=seconds)
    except RedisError:
        pass
    return Response(body, media_type="application/json")
