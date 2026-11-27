"""Create local secrets once. Never print them or replace existing keys."""

import base64
import json
import os
import secrets
from pathlib import Path


def create(path: Path, content: str):
    if path.exists():
        return
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as file:
        file.write(content)


def main():
    directory = Path(".secrets")
    directory.mkdir(mode=0o700, exist_ok=True)
    create(directory / "db-admin-password", secrets.token_urlsafe(48))
    create(directory / "db-app-password", secrets.token_urlsafe(48))
    create(directory / "redis-password", secrets.token_urlsafe(48))
    create(
        directory / "security.json",
        json.dumps(
            {
                "active_key": "v1",
                "keys": {"v1": base64.b64encode(secrets.token_bytes(32)).decode()},
                "token_hmac_key": base64.b64encode(secrets.token_bytes(32)).decode(),
            }
        ),
    )
    redis_password = (directory / "redis-password").read_text().strip()
    create(directory / "redis.conf", f"appendonly yes\nrequirepass {redis_password}\n")
    print("Local secrets created/preserved. Back them up securely; never commit or share them.")


if __name__ == "__main__":
    main()
