import hashlib
import hmac
import json
import time
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, Field, SecretStr
from redis import Redis
from sqlalchemy import select
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import FileResponse, JSONResponse

from app.db.session import build_engine
from app.devconsole.access import (
    COOKIE,
    ConsoleIdentity,
    ConsoleSettings,
    GrantDependency,
    csrf_token,
    read_grant,
)
from app.integrations.wildberries.data import Source
from app.modules.accounts.models import Store, StoreCredential
from app.modules.auth.dependencies import DB
from app.modules.finance.router import SellerBalance
from app.modules.sync.capabilities import sync_capabilities
from app.modules.sync.models import WBRecord
from app.modules.sync.router import (
    configure_sync,
    imported_data,
    start_sync,
    store_analytics,
    sync_schedule,
)
from app.modules.sync.schemas import (
    CatalogItem,
    ConfigureSchedule,
    DataPage,
    FinanceItem,
    FunnelItem,
    OrderItem,
    ReturnItem,
    RunStatus,
    SaleItem,
    SalesBasis,
    ScheduleStatus,
    StartSync,
    StockItem,
    history_limits,
)
from app.modules.sync.service import context
from app.security.crypto import SecretVault
from app.security.middleware import SecurityMiddleware

ORIGINS = {"http://localhost:8010", "http://127.0.0.1:8010"}
MODELS = {
    Source.BALANCE: SellerBalance,
    Source.CATALOG: CatalogItem,
    Source.SALES: SaleItem,
    Source.ORDERS: OrderItem,
    Source.FUNNEL: FunnelItem,
    Source.RETURNS: ReturnItem,
    Source.STOCKS: StockItem,
    Source.FINANCE: FinanceItem,
}
ASSETS = Path(__file__).parent / "static"


class BrowserGuard:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = dict(scope["headers"])
        origin = headers.get(b"origin", b"").decode()
        foreign = (origin and origin not in ORIGINS) or headers.get(
            b"sec-fetch-site"
        ) == b"cross-site"
        unsafe = scope["method"] not in {"GET", "HEAD", "OPTIONS"}
        if foreign or (unsafe and not origin and not headers.get(b"authorization")):
            await JSONResponse({"detail": "Local same-origin request required"}, 403)(
                scope, receive, send
            )
            return
        if unsafe and headers.get(b"content-type", b"").split(b";")[0] != b"application/json":
            await JSONResponse({"detail": "JSON required"}, 415)(scope, receive, send)
            return

        async def secure_send(message):
            if message["type"] == "http.response.start":
                message["headers"] = list(message.get("headers", [])) + [
                    (
                        b"content-security-policy",
                        b"default-src 'none'; script-src 'self'; style-src 'self'; "
                        b"connect-src 'self'; img-src 'self'; frame-ancestors 'none'; "
                        b"base-uri 'none'; form-action 'none'",
                    )
                ]
            await send(message)

        await self.app(scope, receive, secure_send)


class Bootstrap(BaseModel):
    code: SecretStr = Field(min_length=40, max_length=100)


def create_console(settings: ConsoleSettings | None = None):
    settings = settings or ConsoleSettings()
    # Never inherit frontend origins/hosts from the normal API environment.
    settings = settings.model_copy(
        update={"cors_origins": sorted(ORIGINS), "allowed_hosts": ["localhost", "127.0.0.1"]}
    )

    @asynccontextmanager
    async def lifespan(application):
        application.state.settings = settings
        application.state.vault = SecretVault(settings.security_file)
        application.state.db_engine = build_engine(settings)
        application.state.redis = Redis.from_url(
            settings.redis_broker_url,
            socket_connect_timeout=2,
            socket_timeout=2,
            decode_responses=True,
        )
        try:
            yield
        finally:
            application.state.redis.close()
            application.state.db_engine.dispose()

    app = FastAPI(
        title="PERK Local Console",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.add_middleware(SecurityMiddleware, settings=settings)
    app.add_middleware(BrowserGuard)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)

    @app.exception_handler(RequestValidationError)
    async def invalid(request, exc):
        return JSONResponse({"detail": "Invalid request fields"}, 422)

    @app.get("/", include_in_schema=False)
    def home():
        return FileResponse(ASSETS / "index.html")

    @app.get("/assets/{name}", include_in_schema=False)
    def asset(name: str):
        if name not in {"app.js", "style.css"}:
            raise HTTPException(404)
        return FileResponse(ASSETS / name)

    @app.post("/api/v1/dev/bootstrap")
    def bootstrap(data: Bootstrap, request: Request, response: Response):
        grant = read_grant(request)
        digest = hashlib.sha256(data.code.get_secret_value().encode()).hexdigest()
        if time.time() > grant.bootstrap_expires_at or not hmac.compare_digest(
            digest, grant.bootstrap_digest
        ):
            raise HTTPException(401, "Ссылка запуска истекла. Создайте новую ссылку.")
        # One use across threads/processes/restarts; fails closed if Redis is unavailable.
        if not request.app.state.redis.set("dev-console:used:" + digest, "1", nx=True, ex=600):
            raise HTTPException(401, "Ссылка запуска уже использована.")
        response.set_cookie(
            COOKIE,
            grant.token.get_secret_value(),
            httponly=True,
            samesite="strict",
            secure=False,
            max_age=31536000,
            path="/",
        )
        return {"status": "ok"}

    @app.get("/api/v1/dev/session")
    def session(grant: GrantDependency, identity: ConsoleIdentity):
        defaults = StartSync()
        return {
            "mode": "local",
            "csrf": csrf_token(grant),
            "date_from": defaults.date_from,
            "date_to": defaults.date_to,
            "history_limits": history_limits(),
            "fields": {s: list(model.model_fields) for s, model in MODELS.items()},
        }

    @app.get("/api/v1/dev/summary")
    def summary(request: Request, db: DB, grant: GrantDependency, identity: ConsoleIdentity):
        sources = {
            s: imported_data(
                grant.workspace_id, grant.store_id, s, request, db, identity, limit=1, offset=0
            ).model_dump(exclude={"items"})
            for s in Source
        }
        store = db.get(Store, grant.store_id)
        credential = db.scalar(
            select(StoreCredential).where(
                StoreCredential.workspace_id == grant.workspace_id,
                StoreCredential.store_id == grant.store_id,
            )
        )
        stocks = None
        # Never turn a partial page into a misleading total. Bound this local preview workload.
        if (
            sources[Source.STOCKS]["last_successful_run"]
            and sources[Source.STOCKS]["total"] <= 5000
        ):
            rows = db.scalars(
                select(WBRecord)
                .where(
                    WBRecord.workspace_id == grant.workspace_id,
                    WBRecord.store_id == grant.store_id,
                    WBRecord.source == Source.STOCKS,
                )
                .limit(5001)
            ).all()
            values = [
                json.loads(
                    request.app.state.vault.open(
                        r.ciphertext,
                        context(grant.workspace_id, grant.store_id, Source.STOCKS, r.record_key),
                    )
                )
                for r in rows
            ]
            stocks = {
                "quantity": sum(r["quantity"] for r in values),
                "warehouses": len({r["warehouse_id"] for r in values}),
                "in_way_to_client": sum(r["in_way_to_client"] for r in values),
                "in_way_from_client": sum(r["in_way_from_client"] for r in values),
            }
        return {
            "store": {
                "name": store.name,
                "status": store.connection_status,
                "scopes": credential.scopes.split(",") if credential else [],
            },
            "sources": sources,
            "stocks": stocks,
            "schedules": [
                ScheduleStatus.model_validate(plan)
                for plan in sync_schedule(grant.workspace_id, grant.store_id, db, identity)
            ],
            "capabilities": sync_capabilities(
                credential,
                request.app.state.vault,
                request.app.state.settings,
                grant.workspace_id,
                grant.store_id,
            ),
        }

    @app.get("/api/v1/dev/data/{source}", response_model=DataPage)
    def data(
        source: Source,
        request: Request,
        db: DB,
        grant: GrantDependency,
        identity: ConsoleIdentity,
        offset: Annotated[int, Query(ge=0, le=250000)] = 0,
    ):
        return imported_data(
            grant.workspace_id,
            grant.store_id,
            source,
            request,
            db,
            identity,
            limit=25,
            offset=offset,
        )

    @app.post("/api/v1/dev/sync", response_model=list[RunStatus], status_code=202)
    def sync(
        data: StartSync, request: Request, db: DB, grant: GrantDependency, identity: ConsoleIdentity
    ):
        return start_sync(grant.workspace_id, grant.store_id, data, request, db, identity)

    @app.put("/api/v1/dev/sync-schedule", response_model=list[ScheduleStatus])
    def schedule(
        data: ConfigureSchedule,
        request: Request,
        db: DB,
        grant: GrantDependency,
        identity: ConsoleIdentity,
    ):
        return configure_sync(grant.workspace_id, grant.store_id, data, request, db, identity)

    @app.get("/api/v1/dev/analytics")
    def analytics(
        request: Request,
        db: DB,
        grant: GrantDependency,
        identity: ConsoleIdentity,
        date_from: date | None = None,
        date_to: date | None = None,
        sales_basis: SalesBasis = "auto",
    ):
        return store_analytics(
            grant.workspace_id,
            grant.store_id,
            request,
            db,
            identity,
            date_from,
            date_to,
            100,
            sales_basis,
        )

    return app
