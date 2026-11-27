"""Issue/revoke a local-only operator grant. Never changes regular user sessions or MFA."""

import argparse
import hashlib
import json
import os
import secrets
import time
from pathlib import Path
from uuid import UUID

from app.core.config import Settings


def write_private(path, value):
    temporary = path.with_suffix(".new")
    with os.fdopen(
        os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w", encoding="utf-8"
    ) as stream:
        stream.write(value)
    temporary.replace(path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["init", "open", "rotate", "revoke"])
    parser.add_argument("--user", type=UUID)
    parser.add_argument("--workspace", type=UUID)
    parser.add_argument("--store", type=UUID)
    args = parser.parse_args()
    if Settings().app_env != "local":
        parser.error("Local grants are forbidden outside APP_ENV=local")
    directory = Path(".secrets/dev-console")
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = directory / "grant.json"
    if args.action == "revoke":
        for name in ("grant.json", "token.txt", "open.url"):
            (directory / name).unlink(missing_ok=True)
        print("Local development access revoked. Regular sessions are unchanged.")
        return
    if args.action == "init":
        if path.exists():
            parser.error("A grant already exists; use open or rotate")
        if not all((args.user, args.workspace, args.store)):
            parser.error("Specify --user, --workspace and --store")
        grant = {
            "user_id": str(args.user),
            "workspace_id": str(args.workspace),
            "store_id": str(args.store),
            "token": "pd_" + secrets.token_urlsafe(32),
        }
    else:
        grant = json.loads(path.read_text())
        if args.action == "rotate":
            grant["token"] = "pd_" + secrets.token_urlsafe(32)
    code = secrets.token_urlsafe(32)
    grant.update(
        bootstrap_digest=hashlib.sha256(code.encode()).hexdigest(),
        bootstrap_expires_at=time.time() + 300,
    )
    write_private(path, json.dumps(grant))
    write_private(directory / "token.txt", grant["token"])
    write_private(directory / "open.url", "http://127.0.0.1:8010/#launch=" + code)
    print(
        "Local access ready. Private launch link: .secrets/dev-console/open.url "
        "(5 minutes, one use)."
    )


if __name__ == "__main__":
    main()
