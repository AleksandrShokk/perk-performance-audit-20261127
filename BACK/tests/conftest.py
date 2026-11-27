import base64
import json
import secrets

import pytest

from app.core.config import Settings
from app.security.crypto import SecretVault


@pytest.fixture
def isolated_settings(tmp_path):
    security = tmp_path / "test-security.json"
    security.write_text(
        json.dumps(
            {
                "active_key": "test",
                "keys": {"test": base64.b64encode(secrets.token_bytes(32)).decode()},
                "token_hmac_key": base64.b64encode(secrets.token_bytes(32)).decode(),
            }
        )
    )
    password = tmp_path / "test-redis-password"
    password.write_text("test-password")
    return Settings(
        _env_file=None,
        app_env="test",
        security_file=security,
        redis_password_file=password,
        postgres_password="test-password",
    )


@pytest.fixture
def vault(isolated_settings):
    return SecretVault(isolated_settings.security_file)
