import logging
import re

from fastapi import HTTPException
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import Headers
from starlette.middleware.gzip import GZipMiddleware
from starlette.responses import JSONResponse

from app.core import errors
from app.security.limits import rate_limit


class CompressionMiddleware:
    """GZip large report payloads. Auth responses carry tokens and are never compressed
    (BREACH: secrets must not share a compressed body with attacker-influenced input)."""

    def __init__(self, app):
        self.app = app
        self.gzip = GZipMiddleware(app, minimum_size=1024, compresslevel=5)

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and not scope.get("path", "").startswith("/api/v1/auth/"):
            await self.gzip(scope, receive, send)
        else:
            await self.app(scope, receive, send)


class SecurityMiddleware:
    def __init__(self, app, settings):
        self.app = app
        self.settings = settings

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def secure_send(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.extend(
                    [
                        (b"cache-control", b"no-store"),
                        (b"x-content-type-options", b"nosniff"),
                        (b"referrer-policy", b"no-referrer"),
                        (b"x-frame-options", b"DENY"),
                    ]
                )
                if self.settings.app_env == "production":
                    headers.append(
                        (
                            b"strict-transport-security",
                            b"max-age=31536000; includeSubDomains",
                        )
                    )
                message["headers"] = headers
            await send(message)

        async def error(status, detail, headers=None):
            await JSONResponse(errors.body(status, detail), status_code=status, headers=headers)(
                scope, receive, secure_send
            )

        async def invoke(receiver):
            try:
                await self.app(scope, receiver, secure_send)
            except Exception as exc:
                # Type and code location only: no message, SQL parameters, bodies or locals.
                logging.getLogger("perk.security").error(
                    "request_failed type=%s at=%s path=%s",
                    type(exc).__name__,
                    errors.failure_location(exc),
                    scope.get("route").path if scope.get("route") else "-",
                )
                await error(500, "Не удалось выполнить действие. Попробуйте позже.")

        path = scope.get("path", "")
        if path.startswith("/api/v1/") and not path.startswith("/api/v1/health/"):
            if self.settings.app_env == "production" and scope["scheme"] != "https":
                await error(400, "Используйте защищённое соединение HTTPS.")
                return
            headers = Headers(scope=scope)
            # Body-token login must not become a way to bypass browser CSRF protections.
            origin = headers.get("origin")
            if origin and origin not in self.settings.cors_origins:
                await error(403, "Этот адрес сайта не разрешён. Откройте основной сайт PERK.")
                return
            if scope["method"] != "OPTIONS":
                state = scope["app"].state
                identity = str(scope.get("client", ("unknown",))[0])
                auth = path.startswith("/api/v1/auth/") and scope["method"] == "POST"
                try:
                    await run_in_threadpool(
                        rate_limit,
                        state.redis,
                        state.vault,
                        "auth-ip" if auth else "api-ip",
                        identity,
                        self.settings.auth_limit_per_minute
                        if auth
                        else self.settings.api_limit_per_minute * 10,
                    )
                except HTTPException as exc:
                    await error(exc.status_code, exc.detail, exc.headers)
                    return
            # XLSX gets a narrowly scoped, bounded allowance; other API bodies
            # retain their 64 KiB limit. Origin, rate limits, auth and CSRF remain.
            workbook_upload = scope["method"] == "POST" and re.fullmatch(
                r"/api/v1/workspaces/[0-9a-fA-F-]{36}/(?:stores/[0-9a-fA-F-]{36}/(?:cost-imports|inventory/packaging/import/preview)|catalog/matches/preview|inventory/plans/[0-9a-fA-F-]{36}/(?:template/(?:inspect|fill)|import))",
                path,
            )
            body_limit = 320 * 1024 if workbook_upload else 65536
            body = bytearray()
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return
                body.extend(message.get("body", b""))
                if len(body) > body_limit:
                    await error(
                        413, "Слишком большой объём данных. Уменьшите размер файла или запроса."
                    )
                    return
                if not message.get("more_body", False):
                    break
            sent = False

            async def replay():
                nonlocal sent
                if not sent:
                    sent = True
                    return {
                        "type": "http.request",
                        "body": bytes(body),
                        "more_body": False,
                    }
                return await receive()

            await invoke(replay)
        else:
            await invoke(receive)
