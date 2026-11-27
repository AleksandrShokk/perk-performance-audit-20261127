"""Remove obsolete development credential copies; never revoke the encrypted connected-store key."""

import argparse
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    root = Path(".secrets").resolve()
    for name in ("wb-connect.json", "perk-access-token.tmp"):
        path = (root / name).resolve()
        if path.parent != root:
            raise RuntimeError("Unexpected credential path")
        if path.is_file():
            if args.apply:
                path.unlink()
            print(("Removed: " if args.apply else "Obsolete copy: ") + name)
    env = Path(".env")
    if env.exists() and args.apply:
        lines = env.read_text(encoding="utf-8-sig").splitlines()
        lines = [
            line for line in lines if not line.startswith(("POSTGRES_PASSWORD=", "API_BIND_HOST="))
        ]
        if not any(line.startswith("POSTGRES_PASSWORD_FILE=") for line in lines):
            lines.append("POSTGRES_PASSWORD_FILE=.secrets/db-app-password")
        env.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
