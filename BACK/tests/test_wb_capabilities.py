import base64
import json
import time
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.integrations.wildberries.data import Source
from app.modules.sync.capabilities import sync_capabilities


@pytest.mark.parametrize("token_type,stocks_available", [(1, False), (3, True), (4, True)])
def test_stocks_requires_personal_or_service_token_without_exposing_secret(
    vault, token_type, stocks_available
):
    ws, store = uuid4(), uuid4()

    def encode(data):
        return base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=")

    token = (
        encode({"alg": "HS256"})
        + "."
        + encode(
            {
                "s": (1 << 30) | (1 << 1) | (1 << 2) | (1 << 5) | (1 << 13),
                "exp": int(time.time()) + 3600,
                "sid": str(uuid4()),
                "t": False,
                "acc": token_type,
            }
        )
        + ".synthetic-secret"
    )
    credential = SimpleNamespace(ciphertext=vault.seal(token, f"wb:{ws}:{store}"))
    result = sync_capabilities(
        credential, vault, SimpleNamespace(app_env="test", wb_service_id=None), ws, store
    )
    assert result["sources"][Source.STOCKS]["available"] is stocks_available
    assert result["sources"][Source.SALES]["available"]
    assert token not in str(result)
    assert "synthetic-secret" not in str(result)
