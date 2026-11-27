from fastapi import HTTPException
from redis.exceptions import RedisError

LUA_FIXED_WINDOW = """
local n = redis.call('INCR', KEYS[1])
if n == 1 then redis.call('EXPIRE', KEYS[1], ARGV[1]) end
return n
"""


def rate_limit(redis, vault, scope: str, identity: str, limit: int, seconds: int = 60) -> None:
    key = "perk:limit:" + vault.digest(scope, identity)
    try:
        count = redis.eval(LUA_FIXED_WINDOW, 1, key, seconds)
    except RedisError:
        raise HTTPException(
            503, "Сервис проверки доступа временно недоступен. Попробуйте позже."
        ) from None
    if count > limit:
        raise HTTPException(
            429, "Слишком много попыток. Попробуйте позже.", headers={"Retry-After": str(seconds)}
        )
