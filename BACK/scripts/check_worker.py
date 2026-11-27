import json

from app.workers.tasks import ping


def main() -> None:
    result = ping.apply_async(retry=False)
    try:
        response = result.get(timeout=15)
        if response != {"status": "ok", "service": "perk-worker"}:
            raise RuntimeError("Unexpected worker response")
        print(json.dumps(response))
    finally:
        result.forget()


if __name__ == "__main__":
    main()
