"""Encrypted import checkpoint; independent namespaces, tenant/key/input scoping."""

import json

from cryptography.exceptions import InvalidTag


class StockCoverCheckpoint:
    def __init__(self, redis, vault, workspace_id, store_id, client_id, api_key, namespace="cover"):
        self.redis, self.vault = redis, vault
        self.namespace = namespace
        self.scope = f"{workspace_id}:{store_id}:" + vault.digest(
            "ozon-checkpoint-key", client_id + ":" + api_key
        )
        self.key = self.aad = None

    def load(self, skus):
        signature = self.vault.digest("ozon-checkpoint-skus", ",".join(sorted(skus)))
        self.aad = f"perk-ozon-{self.namespace}-stage:v1:{self.scope}:{signature}"
        self.key = f"perk:ozon:{self.namespace}-stage:" + self.vault.digest(
            "ozon-checkpoint", self.aad
        )
        raw = self.redis.get(self.key)
        if raw:
            try:
                value = json.loads(
                    self.vault.open(raw.decode() if isinstance(raw, bytes) else raw, self.aad)
                )
                if (
                    isinstance(value, dict)
                    and isinstance(value.get("completed"), list)
                    and isinstance(value.get("rows"), list)
                ):
                    return value
            except InvalidTag, ValueError, KeyError, TypeError:
                self.clear()
        return {"completed": [], "rows": []}

    def save(self, value):
        self.redis.set(self.key, self.vault.seal(json.dumps(value, default=str), self.aad), ex=1800)

    def clear(self):
        if self.key:
            self.redis.delete(self.key)
