from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from redis import Redis
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import JSONResponse

from app.api.router import api_router
from app.core import errors
from app.core.config import Settings, get_settings
from app.core.error_messages import validation_message
from app.core.errors import RequestIdMiddleware
from app.core.logging import configure_logging
from app.db.session import build_engine
from app.integrations.notifications import build_messenger, build_notifier
from app.integrations.ozon.client import OzonClient
from app.integrations.wildberries.client import WildberriesClient
from app.security.crypto import SecretVault
from app.security.middleware import CompressionMiddleware, SecurityMiddleware


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        configure_logging(settings.log_level)
        application.state.settings = settings
        application.state.vault = SecretVault(settings.security_file)
        application.state.wb_client = WildberriesClient()
        application.state.ozon_client = OzonClient()
        application.state.notifier = build_notifier(settings)
        application.state.telegram_bot, application.state.push = build_messenger(settings)
        engine = build_engine(settings)
        redis = Redis.from_url(
            settings.redis_broker_url,
            socket_connect_timeout=2,
            socket_timeout=2,
            decode_responses=True,
        )
        application.state.db_engine = engine
        application.state.redis = redis
        try:
            yield
        finally:
            redis.close()
            engine.dispose()

    application = FastAPI(
        title="PERK API",
        version="0.3.0",
        description="PERK private beta: MFA, secure stores and resumable read-only WB imports.",
        lifespan=lifespan,
        docs_url="/docs" if settings.app_env != "production" else None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.app_env != "production" else None,
        responses={
            status: {"model": errors.ErrorResponse}
            for status in (400, 401, 403, 404, 409, 410, 413, 422, 429, 500, 502, 503)
        },
    )
    # Last added runs first: TrustedHost → CORS → Security → GZip. CORS wraps security errors
    # too, so browsers see 429/413/503 instead of an opaque network failure.
    application.add_middleware(CompressionMiddleware)
    application.add_middleware(SecurityMiddleware, settings=settings)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "X-CSRF-Token",
            "If-None-Match",
            "X-Request-ID",
        ],
        expose_headers=["Retry-After", "ETag", "X-Request-ID"],
    )
    application.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)
    application.add_middleware(RequestIdMiddleware)

    @application.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        # Pydantic errors include original inputs by default (passwords/tokens included).
        fields = [
            {"loc": error["loc"], "type": error["type"], "msg": validation_message(error["type"])}
            for error in exc.errors()
        ]
        content = errors.body(422, fields)
        content["message"] = "Проверьте поля запроса."
        return JSONResponse(status_code=422, content=content)

    @application.exception_handler(StarletteHTTPException)
    async def http_error(request, exc):
        return JSONResponse(
            status_code=exc.status_code,
            content=errors.body(exc.status_code, exc.detail),
            headers=getattr(exc, "headers", None),
        )

    application.include_router(api_router)
    return application


app = create_app()
