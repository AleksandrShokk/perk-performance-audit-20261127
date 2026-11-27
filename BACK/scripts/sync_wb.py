"""Local operator client. Uses normal MFA-protected API; never accesses the DB or WB key."""

import argparse
import json
from pathlib import Path

import httpx


def main():
    parser = argparse.ArgumentParser(description="PERK local Wildberries synchronization")
    parser.add_argument("action", choices=["start", "status", "data"])
    parser.add_argument("--workspace")
    parser.add_argument("--store")
    parser.add_argument(
        "--source", choices=["catalog", "sales", "orders", "stocks", "finance", "funnel", "returns"]
    )
    parser.add_argument("--date-from")
    parser.add_argument("--date-to")
    args = parser.parse_args()
    token_file = Path(".secrets/perk-access-token.tmp")
    if not token_file.is_file():
        print("Save a current PERK access token in .secrets/perk-access-token.tmp first.")
        return 1
    token = token_file.read_text(encoding="utf-8-sig").strip()
    try:
        with httpx.Client(
            base_url="http://127.0.0.1:8000/api/v1",
            timeout=30,
            follow_redirects=False,
            trust_env=False,
            headers={"Authorization": "Bearer " + token},
        ) as client:

            def call(method, path, **kwargs):
                response = client.request(method, path, **kwargs)
                if response.status_code == 401:
                    raise ValueError(
                        "PERK access token expired. Log in with MFA "
                        "and update the local token file."
                    )
                if response.status_code == 403:
                    raise ValueError("MFA verification is required for this session.")
                if response.status_code >= 400:
                    raise ValueError(
                        f"PERK HTTP {response.status_code}: check the request in Swagger."
                    )
                return response.json()

            workspace = args.workspace
            if not workspace:
                spaces = call("GET", "/workspaces")
                if len(spaces) != 1:
                    raise ValueError(
                        "Specify --workspace: more than one or no workspace is available."
                    )
                workspace = spaces[0]["id"]
            store = args.store
            if not store:
                stores = [
                    s
                    for s in call("GET", f"/workspaces/{workspace}/stores")
                    if s["marketplace"] == "wildberries"
                ]
                if len(stores) != 1:
                    raise ValueError("Specify --store: more than one or no WB store is available.")
                store = stores[0]["id"]
            base = f"/workspaces/{workspace}/stores/{store}"
            if args.action == "start":
                payload = {}
                if args.source:
                    payload["sources"] = [args.source]
                if args.date_from:
                    payload["date_from"] = args.date_from
                if args.date_to:
                    payload["date_to"] = args.date_to
                result = call("POST", base + "/sync", json=payload)
            elif args.action == "data":
                if not args.source:
                    raise ValueError("Specify --source for data.")
                result = call("GET", base + "/data/" + args.source, params={"limit": 5})
                # Counts/metadata only: the operator log must not expose shop records.
                result.pop("items", None)
            else:
                result = call("GET", base + "/sync-runs")
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
    except httpx.HTTPError:
        print("PERK is unreachable. Check that the local API is running.")
        return 1
    except ValueError as error:
        print(str(error))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
