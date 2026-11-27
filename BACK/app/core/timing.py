"""Per-request timing: where an API request spends its time, without any data.

Every API response carries a ``Server-Timing`` header (visible in the browser's
DevTools → Network → Timing) with three parts:

- ``db``     — time inside PostgreSQL calls, with the number of statements;
- ``crypto`` — time spent encrypting/decrypting stored reports;
- ``total``  — the whole request as seen by the API process.

Slow requests are also logged as one line with the route template (no identifiers,
parameters or bodies), so production timings can be collected from
``docker compose logs api``. Authentication responses get no header: timing
details must not help anyone probe accounts.
"""

import logging
import time
from contextvars import ContextVar

from sqlalchemy import event

logger = logging.getLogger("perk.timing")
SLOW_REQUEST_MS = 1000

# A mutable per-request accumulator. Sync handlers run in a thread pool with a copy of
# the request context, so they share this object and their measurements reach the
# middleware. Outside a request (workers, scripts) the value is None and nothing is kept.
current: ContextVar[dict | None] = ContextVar("perk_timing", default=None)


def add(name: str, seconds: float) -> None:
    values = current.get()
    if values is not None:
        values[name] = values.get(name, 0.0) + seconds
        values[name + "_count"] = values.get(name + "_count", 0) + 1


def instrument_engine(engine) -> None:
    @event.listens_for(engine, "before_cursor_execute")
    def started(conn, cursor, statement, parameters, context, executemany):
        if current.get() is not None:
            conn.info.setdefault("perk_timing_started", []).append(time.perf_counter())

    @event.listens_for(engine, "after_cursor_execute")
    def finished(conn, cursor, statement, parameters, context, executemany):
        stack = conn.info.get("perk_timing_started")
        if stack:
            add("db", time.perf_counter() - stack.pop())

    @event.listens_for(engine, "handle_error")
    def failed(context):
        connection = context.connection
        stack = connection.info.get("perk_timing_started") if connection is not None else None
        if stack:
            add("db", time.perf_counter() - stack.pop())


def header(values: dict, total: float) -> bytes:
    db, crypto = values.get("db", 0.0), values.get("crypto", 0.0)
    parts = [
        f'db;dur={db * 1000:.1f};desc="{values.get("db_count", 0)} SQL"',
        f'crypto;dur={crypto * 1000:.1f};desc="{values.get("crypto_count", 0)} ops"',
        f"app;dur={max(0.0, total - db - crypto) * 1000:.1f}",
        f"total;dur={total * 1000:.1f}",
    ]
    return ", ".join(parts).encode()


class TimingMiddleware:
    def __init__(self, app, slow_ms: int = SLOW_REQUEST_MS):
        self.app = app
        self.slow_ms = slow_ms

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "") if scope["type"] == "http" else ""
        if not path.startswith("/api/v1/") or path.startswith("/api/v1/health/"):
            await self.app(scope, receive, send)
            return
        values: dict = {}
        token = current.set(values)
        started = time.perf_counter()
        status = 0
        private = path.startswith("/api/v1/auth/")

        async def timed_send(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                if not private:
                    message["headers"] = [
                        *message.get("headers", []),
                        (b"server-timing", header(values, time.perf_counter() - started)),
                    ]
            await send(message)

        try:
            await self.app(scope, receive, timed_send)
        finally:
            current.reset(token)
            total_ms = (time.perf_counter() - started) * 1000
            if total_ms >= self.slow_ms:
                route = scope.get("route")
                logger.warning(
                    "slow_request method=%s route=%s status=%s total_ms=%.0f db_ms=%.0f "
                    "sql=%d crypto_ms=%.0f crypto_ops=%d",
                    scope.get("method", "-"),
                    getattr(route, "path", "-"),
                    status,
                    total_ms,
                    values.get("db", 0.0) * 1000,
                    values.get("db_count", 0),
                    values.get("crypto", 0.0) * 1000,
                    values.get("crypto_count", 0),
                )
