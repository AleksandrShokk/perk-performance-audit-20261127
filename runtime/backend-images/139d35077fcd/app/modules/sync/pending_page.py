"""Keep a validated WB page while a report holds the store publication lock.

Only normalized fields are cached, encrypted and bound to the tenant, run,
cursor and current credential. A retry can publish without another WB request.
"""

import json
from dataclasses import dataclass

from cryptography.exceptions import InvalidTag

TTL_SECONDS = 600
MAX_BYTES = 8 * 1024 * 1024


@dataclass
class PendingPage:
    records: dict[str, dict]
    cursor: dict
    complete: bool


def address(vault, run, credential):
    identity = json.dumps(
        [str(run.workspace_id), str(run.store_id), str(run.id), run.source, run.cursor, credential],
        sort_keys=True,
        separators=(",", ":"),
    )
    return "perk:wb-pending-page:" + vault.digest("wb-pending-page:v1", identity)


def load(redis, vault, key):
    ciphertext = redis.get(key)
    if not isinstance(ciphertext, str):
        return None
    try:
        if len(ciphertext) > MAX_BYTES:
            return None
        data = json.loads(vault.open(ciphertext, key))
        if (
            not isinstance(data, dict)
            or set(data) != {"records", "cursor", "complete"}
            or not isinstance(data["records"], dict)
            or not all(isinstance(value, dict) for value in data["records"].values())
            or not isinstance(data["cursor"], dict)
            or type(data["complete"]) is not bool
        ):
            return None
        return PendingPage(**data)
    except InvalidTag, ValueError, KeyError, TypeError:
        # A missing, expired or unreadable cache never bypasses the WB quota.
        return None


def save(redis, vault, key, records, page):
    data = json.dumps(
        {"records": records, "cursor": page.cursor, "complete": page.complete},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    if len(data.encode()) > MAX_BYTES * 3 // 4 - 100:
        return False
    ciphertext = vault.seal(data, key)
    if len(ciphertext) > MAX_BYTES:
        return False
    redis.set(key, ciphertext, ex=TTL_SECONDS)
    return True
