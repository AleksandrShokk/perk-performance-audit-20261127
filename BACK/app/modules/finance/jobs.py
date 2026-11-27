"""Scoped preparation queue with a finite deduplication lease; no seller facts in messages."""

from uuid import uuid4

from redis.exceptions import RedisError

RELEASE = (
    "if redis.call('GET', KEYS[1]) == ARGV[1] then return redis.call('DEL', KEYS[1]) end return 0"
)


def job_key(vault, workspace_id, store_id):
    return "perk:finance-prepare:" + vault.digest("finance-job", f"{workspace_id}:{store_id}")


def enqueue(redis, vault, workspace_id, store_id, actor_id):
    from app.workers.tasks import prepare_finance

    key, token = job_key(vault, workspace_id, store_id), str(uuid4())
    try:
        if not redis.set(key, token, nx=True, ex=720):
            return False
        try:
            prepare_finance.apply_async(
                args=[str(workspace_id), str(store_id), str(actor_id), token], retry=False
            )
        except Exception:
            redis.eval(RELEASE, 1, key, token)
            return False
    except RedisError:
        return False
    return True
